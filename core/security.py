"""Małe, bezstanowe mechanizmy ochrony dostępne bez zmian w bazie danych."""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect


def client_ip(request) -> str:
    """Zwraca pierwszy adres klienta przekazany przez zaufany reverse proxy."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",", 1)[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")


def request_limit_key(scope: str, identifier: str) -> str:
    return f"innoradar:rate-limit:{scope}:{identifier}"


def consume_attempt(scope: str, identifier: str, *, limit: int, timeout: int) -> bool:
    """Zapisuje próbę i zwraca, czy limit został już przekroczony."""
    key = request_limit_key(scope, identifier)
    if cache.add(key, 1, timeout=timeout):
        return False
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return False
    return attempts > limit


def is_rate_limited(scope: str, identifier: str, *, limit: int) -> bool:
    return cache.get(request_limit_key(scope, identifier), 0) >= limit


def clear_attempts(scope: str, identifier: str) -> None:
    cache.delete(request_limit_key(scope, identifier))


def too_many_requests(message: str) -> HttpResponse:
    response = HttpResponse(message, status=429, content_type="application/json; charset=utf-8")
    response["Retry-After"] = str(settings.RATE_LIMIT_RETRY_AFTER_SECONDS)
    return response


class SecurityHeadersMiddleware:
    """Dodaje nagłówki ochronne oraz nonce dla skryptów osadzonych w szablonie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(18)
        response = self.get_response(request)
        nonce = request.csp_nonce
        response.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}' 'unsafe-eval' https://unpkg.com; "
                "style-src 'self' 'unsafe-inline' https://unpkg.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self'; font-src 'self' data:; "
                "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            ),
        )
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


class EnforceInitialAdminPasswordChangeMiddleware:
    """Nie pozwala używać panelu produkcyjnego z publicznym admin/admin."""

    allowed_paths = {"/administracja/dane-logowania/", "/administracja/wyloguj/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.ENFORCE_INITIAL_ADMIN_PASSWORD_CHANGE
            and request.user.is_authenticated
            and request.user.username == "admin"
            and request.user.check_password("admin")
            and request.path not in self.allowed_paths
        ):
            return redirect("control_credentials")
        return self.get_response(request)
