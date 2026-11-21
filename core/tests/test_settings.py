# Mechanical split of the former test_core.py by responsibility.

from importlib import reload

from config import settings as project_settings


def test_production_settings_support_a_path_prefix(monkeypatch):
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "maciej-ciemborowicz.eu, localhost")
    monkeypatch.setenv("DJANGO_CSRF_TRUSTED_ORIGINS", "https://maciej-ciemborowicz.eu")
    monkeypatch.setenv("DJANGO_FORCE_SCRIPT_NAME", "/innoradar/")

    settings_module = reload(project_settings)

    assert settings_module.DEBUG is False
    assert settings_module.ALLOWED_HOSTS == ["maciej-ciemborowicz.eu", "localhost"]
    assert settings_module.FORCE_SCRIPT_NAME == "/innoradar"
    assert settings_module.STATIC_URL == "/innoradar/static/"
    assert settings_module.CSRF_TRUSTED_ORIGINS == ["https://maciej-ciemborowicz.eu"]
    assert settings_module.SECURE_HSTS_SECONDS == 31_536_000
    assert settings_module.ENFORCE_INITIAL_ADMIN_PASSWORD_CHANGE is True
    assert (
        settings_module.CACHES["default"]["BACKEND"]
        == "django.core.cache.backends.redis.RedisCache"
    )
    assert settings_module.env_flag("UNSET_BOOLEAN") is False

    monkeypatch.undo()
    reload(settings_module)






