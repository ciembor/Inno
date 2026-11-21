.PHONY: run worker beat check lint smells javascript test quality

run:
	.venv/bin/python manage.py runserver 127.0.0.1:8000

worker:
	.venv/bin/celery -A config worker --loglevel=INFO

beat:
	.venv/bin/celery -A config beat --loglevel=INFO

check:
	.venv/bin/python manage.py check

lint:
	.venv/bin/ruff check .

smells:
	.venv/bin/radon cc core config -s -a
	.venv/bin/radon mi core config -s

javascript:
	for file in core/static/core/js/*.js; do node --check "$$file"; done
	npx --yes prettier@3.10.1 --check core/static/core/js/*.js

test:
	.venv/bin/pytest

quality: lint smells javascript test
