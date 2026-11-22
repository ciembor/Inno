from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from core.security import EnforceInitialAdminPasswordChangeMiddleware, client_ip


def test_client_ip_uses_the_address_set_by_the_reverse_proxy():
    request = RequestFactory().get(
        "/", HTTP_X_REAL_IP="198.51.100.8", HTTP_X_FORWARDED_FOR="203.0.113.1"
    )

    assert client_ip(request) == "198.51.100.8"


def test_client_ip_falls_back_to_the_direct_peer_address():
    request = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1")

    assert client_ip(request) == "127.0.0.1"


def test_initial_password_middleware_allows_credentials_under_a_script_prefix(db):
    user = get_user_model().objects.create_superuser("renamed-admin", password="initial-secret")
    request = RequestFactory().get(
        "/administracja/dane-logowania/", SCRIPT_NAME="/inno"
    )
    request.user = user
    middleware = EnforceInitialAdminPasswordChangeMiddleware(lambda _: HttpResponse("ok"))

    with override_settings(
        ENFORCE_INITIAL_ADMIN_PASSWORD_CHANGE=True,
        INITIAL_ADMIN_PASSWORD="initial-secret",
    ):
        response = middleware(request)

    assert request.path == "/inno/administracja/dane-logowania/"
    assert response.status_code == 200
