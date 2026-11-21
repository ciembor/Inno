# Mechanical split of the former test_core.py by responsibility.


import pytest
from django.core.cache import cache
from django.urls import reverse

from core.models import Idea, Locality
from core.security import consume_attempt


@pytest.mark.django_db
def test_home_page_is_available(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert "Pomysły, które zasługują na szansę." in response.content.decode()
    assert reverse("submit_idea") in response.content.decode()
    assert 'aria-label="Ustawienia dostępności"' in response.content.decode()
    assert "Domyślny" in response.content.decode()
    assert 'data-color-mode="default"' in response.content.decode()
    assert 'class="mode-icon"' in response.content.decode()
    assert 'data-reduce-motion' in response.content.decode()
    assert "core/css/base.css" in response.content.decode()
    assert "core/css/pages/home.css" in response.content.decode()
    assert "innoradar-logo-high-contrast.svg" in response.content.decode()
    assert "Wysoki kontrast – jasny" in response.content.decode()
    assert "inverted-contrast" in response.content.decode()
    assert 'class="hero__clouds" aria-hidden="true"' in response.content.decode()
    assert "core/js/home.js" in response.content.decode()
    assert 'class="city__overlay"' in response.content.decode()
    assert 'rel="icon"' in response.content.decode()
    assert 'window.dispatchEvent(new Event("contrastchange"))' in response.content.decode()
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in response


def test_browser_auxiliary_resources_are_available(client):
    favicon = client.get("/favicon.ico")
    devtools_config = client.get(reverse("chrome_devtools_config"))

    assert favicon.status_code == 302
    assert devtools_config.json() == {}


@pytest.mark.django_db
def test_idea_form_page_is_available(client):
    response = client.get(reverse("submit_idea"))

    assert response.status_code == 200
    assert "core/js/submit_idea.js" in response.content.decode()
    assert 'aria-current="page">Zgłoś pomysł' in response.content.decode()
    assert "core/css/pages/submit_idea.css" in response.content.decode()
    assert 'v-cloak v-if="submitting"' in response.content.decode()
    assert 'autocomplete="name"' in response.content.decode()
    assert 'autocomplete="email"' in response.content.decode()
    assert 'role="combobox"' in response.content.decode()
    assert 'role="listbox"' in response.content.decode()
    assert 'aria-labelledby="idea-editor-label"' in response.content.decode()
    assert "core/images/bulb.webp" in response.content.decode()
    assert reverse("privacy") in response.content.decode()


def test_privacy_page_explains_retention_and_removal(client):
    response = client.get(reverse("privacy"))

    assert response.status_code == 200
    assert "12 miesięcy" in response.content.decode()
    assert "usunięcia zgłoszenia" in response.content.decode()


def test_about_page_explains_data_ai_limits_and_security(client):
    response = client.get(reverse("about"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "O projekcie" in content
    assert "Dane i źródła" in content
    assert "AI i rekomendacje" in content
    assert "Granice systemu" in content
    assert "Skalowanie i integracje" in content
    assert "Prywatność i bezpieczeństwo" in content
    assert reverse("privacy") in content
    assert 'aria-current="page">O projekcie' in content
    assert "core/css/pages/about.css" in content


@pytest.mark.django_db
def test_valid_idea_submission_is_queued_for_scoring_before_redirect(client, monkeypatch):
    scored_ids = []
    monkeypatch.setattr(
        "core.page_views.score_idea.delay", lambda idea_id: scored_ids.append(idea_id)
    )
    locality = Locality.objects.create(
        simc_code="0654321",
        name="Rzeszów",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
    )

    response = client.post(
        reverse("submit_idea"),
        {
            "name": "Biblioteka sąsiedzka",
            "submitter_name": "Anna Kowalska",
            "email": "anna@example.org",
            "locality": locality.pk,
            "content": "<p>Opis</p>",
            "privacy_accepted": "on",
        },
    )

    assert response.status_code == 201
    idea = Idea.objects.get()
    assert response.json()["redirect_url"] == reverse("innovation_detail", args=[idea.pk])
    assert idea.name == "Biblioteka sąsiedzka"
    assert idea.locality == locality
    assert scored_ids == [idea.pk]


@pytest.mark.django_db
def test_idea_submission_requires_privacy_confirmation_and_is_rate_limited(client):
    cache.clear()
    locality = Locality.objects.create(
        simc_code="0654322",
        name="Krosno",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
    )
    payload = {
        "name": "Pomysł",
        "submitter_name": "Anna Kowalska",
        "email": "anna@example.org",
        "locality": locality.pk,
        "content": "<p>Opis</p>",
    }
    missing_confirmation = client.post(reverse("submit_idea"), payload)

    assert missing_confirmation.status_code == 400
    assert "privacy_accepted" in missing_confirmation.json()["errors"]

    for _ in range(4):
        assert client.post(reverse("submit_idea"), payload).status_code == 400
    limited = client.post(reverse("submit_idea"), payload)

    assert limited.status_code == 429
    assert limited["Retry-After"] == "900"
    cache.clear()


def test_rate_limit_recovers_from_an_expired_cache_counter(monkeypatch):
    cache.clear()
    monkeypatch.setattr(cache, "add", lambda *args, **kwargs: False)
    monkeypatch.setattr(cache, "incr", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError))

    assert not consume_attempt("test", "127.0.0.1", limit=5, timeout=1)
    cache.clear()


@pytest.mark.django_db
def test_locality_search_returns_imported_matching_localities(client):
    locality = Locality.objects.create(
        simc_code="0654321",
        name="Rzeszów",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
    )

    matches = client.get(reverse("locality_search"), {"q": "Rz"})
    too_short = client.get(reverse("locality_search"), {"q": "R"})

    assert matches.json() == {
        "results": [{"id": locality.pk, "name": "Rzeszów", "county": "powiat Rzeszów"}]
    }
    assert too_short.json() == {"results": []}


@pytest.mark.django_db
def test_invalid_idea_submission_displays_errors(client):
    response = client.post(reverse("submit_idea"), {"name": "", "content": ""})

    assert response.status_code == 400
    assert response.json()["errors"]["name"] == ["To pole jest wymagane."]


@pytest.mark.django_db
def test_idea_submission_rejects_invalid_email(client):
    response = client.post(
        reverse("submit_idea"),
        {
            "name": "Biblioteka sąsiedzka",
            "submitter_name": "Anna Kowalska",
            "email": "nie-jest-adresem-email",
            "content": "<p>Opis</p>",
        },
    )

    assert response.status_code == 400
    assert "email" in response.json()["errors"]
