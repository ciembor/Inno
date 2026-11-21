#!/usr/bin/env bash
# Deploy Innoradar to https://maciej-ciemborowicz.eu/inno.
#
# The script synchronizes code only. It deliberately preserves the production
# SQLite database, environment file, virtual environment and collected assets.
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-ciembor@maciej-ciemborowicz.eu}"
REMOTE_DIR="${REMOTE_DIR:-/home/ciembor/innoradar}"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/default}"
RUN_QUALITY="${RUN_QUALITY:-1}"

cd "$(dirname "$0")/.."

if [[ "$RUN_QUALITY" == "1" ]]; then
  make quality
fi

rsync -az --delete \
  --exclude '.env' \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '/data/' \
  --exclude 'db.sqlite3' \
  --exclude 'staticfiles/' \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

ssh "$REMOTE_HOST" "APP_DIR='$REMOTE_DIR' NGINX_SITE='$NGINX_SITE' bash -s" <<'REMOTE'
set -euo pipefail

mkdir -p "$APP_DIR/data"
chmod 700 "$APP_DIR/data"

if ! command -v redis-server >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install --yes redis-server
fi
sudo systemctl enable --now redis-server

if [[ ! -f "$APP_DIR/.env" ]]; then
  umask 077
  django_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
  openai_key=""
  if [[ -f "$HOME/prodietai/.env" ]]; then
    openai_key="$(sed -n 's/^OPENAI_API_KEY=//p' "$HOME/prodietai/.env" | head -n 1)"
  fi
  cat > "$APP_DIR/.env" <<ENVIRONMENT
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=$django_secret
DJANGO_ALLOWED_HOSTS=maciej-ciemborowicz.eu
DJANGO_CSRF_TRUSTED_ORIGINS=https://maciej-ciemborowicz.eu
DJANGO_FORCE_SCRIPT_NAME=/inno
SQLITE_DB_PATH=$APP_DIR/data/db.sqlite3
STATIC_ROOT=/var/www/innoradar/static
CELERY_BROKER_URL=redis://127.0.0.1:6379/3
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/3
DJANGO_CACHE_URL=redis://127.0.0.1:6379/4
OPENAI_MODEL=gpt-6-luna
OPENAI_API_KEY=$openai_key
ENVIRONMENT
  if [[ -z "$openai_key" ]]; then
    echo "WARNING: OPENAI_API_KEY was not found in ~/prodietai/.env; add it to $APP_DIR/.env."
  fi
fi

if grep -q '^DJANGO_FORCE_SCRIPT_NAME=' "$APP_DIR/.env"; then
  sed -i 's|^DJANGO_FORCE_SCRIPT_NAME=.*$|DJANGO_FORCE_SCRIPT_NAME=/inno|' "$APP_DIR/.env"
else
  printf '\nDJANGO_FORCE_SCRIPT_NAME=/inno\n' >> "$APP_DIR/.env"
fi

if ! grep -q '^DJANGO_CACHE_URL=' "$APP_DIR/.env"; then
  printf '\nDJANGO_CACHE_URL=redis://127.0.0.1:6379/4\n' >> "$APP_DIR/.env"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install --requirement "$APP_DIR/requirements.txt"

sudo install -d -m 0755 /var/www/innoradar
sudo install -d -o ciembor -g www-data -m 2775 /var/www/innoradar/static
sudo chown -R ciembor:www-data /var/www/innoradar/static
set -a
source "$APP_DIR/.env"
set +a
"$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" migrate --noinput
"$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" bootstrap_admin
"$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" collectstatic --noinput

for service in innoradar-web innoradar-worker innoradar-beat; do
  sed "s|__APP_DIR__|$APP_DIR|g" "$APP_DIR/deploy/systemd/$service.service" |
    sudo tee "/etc/systemd/system/$service.service" >/dev/null
done

sudo install -m 0644 "$APP_DIR/deploy/nginx/innoradar.conf" /etc/nginx/snippets/innoradar.conf
if ! sudo grep -qF 'include /etc/nginx/snippets/innoradar.conf;' "$NGINX_SITE"; then
  sudo python3 - "$NGINX_SITE" <<'PYTHON'
from pathlib import Path
import sys

path = Path(sys.argv[1])
content = path.read_text()
include = '    include /etc/nginx/snippets/innoradar.conf;\n'
marker = '    location / {\n'
if marker not in content:
    raise SystemExit(f'Cannot add Innoradar include: {marker!r} not found in {path}')
path.write_text(content.replace(marker, include + marker, 1))
PYTHON
fi

sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now innoradar-web innoradar-worker innoradar-beat
sudo systemctl restart innoradar-web innoradar-worker innoradar-beat
sudo systemctl reload nginx
sudo systemctl --no-pager --full status innoradar-web innoradar-worker innoradar-beat
REMOTE
