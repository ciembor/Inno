from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from celery.exceptions import Retry
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.control_forms import (
    CrawlScheduleForm,
    CredentialsForm,
    InstitutionPanelForm,
    PartnerOrganizationForm,
)
from core.control_views import _format_duration, _locality_label
from core.models import (
    CrawlSchedule,
    DevelopmentRecommendation,
    Idea,
    InnovationIndicator,
    Institution,
    InstitutionImportEvent,
    InstitutionImportRun,
    InstitutionNewsSource,
    Locality,
    NCBRImportRun,
    PartnerOrganization,
    PartnerTag,
    PromptTemplate,
    ScoringCalibration,
    ScoringCalibrationExample,
)
from core.services.crawl_schedule import next_crawl_at, start_due_crawl
from core.services.institution_import_run import (
    continue_import_run,
    deserialize_article,
    serialize_article,
)
from core.services.institution_innovation_import import (
    InstitutionImportResult,
    InstitutionInnovationImportService,
)
from core.services.institution_news import NewsArticle
from core.services.news_llm import SelectedNewsArticle
from core.services.partner_csv import import_partners_csv
from core.services.prompt_registry import PROMPT_DEFINITIONS
from core.services.prompt_store import PromptNotConfiguredError, get_prompt
from core.tasks import (
    import_institution_news,
    recover_institution_imports,
    start_scheduled_institution_import,
)
from core.tests.test_integration import create_locality


@pytest.fixture
def admin_client(client):
    call_command("bootstrap_admin")
    assert client.login(username="admin", password="admin")
    return client


@pytest.mark.django_db
def test_control_login_logout_and_dashboard(client):
    login_url = reverse("control_login")
    assert client.get(reverse("control_dashboard")).url == f"{login_url}?next=/administracja/"
    assert client.get(login_url).status_code == 200
    call_command("bootstrap_admin")
    assert client.login(username="admin", password="admin")
    assert client.get(login_url).url == reverse("control_dashboard")
    client.post(reverse("control_logout"))
    assert client.get(reverse("control_dashboard")).status_code == 302
    response = client.post(login_url, {"username": "admin", "password": "admin"})
    assert response.url == reverse("control_dashboard")
    assert "Panel administracyjny" in client.get(response.url).content.decode()
    client.post(reverse("control_logout"))
    assert client.post(login_url, {"username": "admin", "password": "wrong"}).status_code == 200


@pytest.mark.django_db
def test_non_staff_user_cannot_log_in_or_access_the_control_panel(client):
    user = get_user_model().objects.create_user("reader", password="ReaderPass-123")

    login = client.post(
        reverse("control_login"), {"username": user.username, "password": "ReaderPass-123"}
    )
    assert "nie ma dostępu" in login.content.decode()
    assert not client.session.get("_auth_user_id")

    client.force_login(user)
    assert client.get(reverse("control_dashboard")).status_code == 403
    assert client.get(reverse("control_prompts")).status_code == 403


@pytest.mark.django_db
def test_csv_export_is_authenticated_and_excludes_submitter_data(admin_client):
    locality = create_locality()
    idea = Idea.objects.create(
        name="Eksportowana innowacja",
        submitter_name="Prywatna osoba",
        email="private@example.org",
        locality=locality,
        content="Opis do eksportu.",
        innovation_score=72,
    )
    response = admin_client.get(reverse("control_csv_export"))

    content = response.content.decode("utf-8-sig")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=\"innoradar-innowacje.csv\"" in response["Content-Disposition"]
    assert "Eksportowana innowacja" in content
    assert "private@example.org" not in content
    assert "Prywatna osoba" not in content
    assert str(idea.pk) in content


@pytest.mark.django_db
def test_metrics_panel_shows_operational_counts_and_import_duration(admin_client):
    institution = Institution.objects.create(
        name="Instytucja z aktualnościami",
        address="Rzeszów",
        news_url="https://example.org/aktualnosci/",
        institution_type="school",
    )
    InstitutionNewsSource.objects.create(institution=institution, url="https://example.org/news/")
    tag = PartnerTag.objects.get(name="Finansowanie")
    partner = PartnerOrganization.objects.create(
        name="Partner finansujący",
        organization_type="funder",
        description="Wsparcie",
    )
    partner.tags.add(tag)
    idea = Idea.objects.create(
        name="Oceniona inicjatywa",
        submitter_name="Anna",
        email="anna@example.org",
        content="Opis",
    )
    idea.partner_needs.add(tag)
    Idea.objects.filter(pk=idea.pk).update(scored_at=timezone.now())
    DevelopmentRecommendation.objects.create(
        idea=idea,
        stage="pilot",
        development_path="partnership",
        next_step="Test.",
        rationale="Uzasadnienie.",
        risk="Ryzyko.",
        status="approved",
    )
    InstitutionImportRun.objects.create(ideas_created=3, ideas_skipped=2, duration_seconds=120)
    ncbr_run = NCBRImportRun.objects.create(ideas_created=4, ideas_skipped=1)
    NCBRImportRun.objects.filter(pk=ncbr_run.pk).update(
        started_at=timezone.now() - timedelta(minutes=3), finished_at=timezone.now()
    )

    response = admin_client.get(reverse("control_dashboard"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Panel administracyjny" in content
    assert "Instytucja z aktualnościami" not in content
    assert ">2<" in content
    assert ">10<" in content
    assert ">1<" in content
    assert "Średni czas importu" in content
    assert "Mierniki dwóch scenariuszy demonstracyjnych" in content
    assert "Automatyczne wykrycie" in content
    assert "Ręczne zgłoszenie" in content
    assert "min</dd>" in content
    assert "Ostatnie importy" in content
    assert reverse("control_csv_export") in content
    assert admin_client.get(reverse("control_metrics")).url == reverse("control_dashboard")


def test_duration_formatter_covers_all_display_forms():
    assert _format_duration(None) == "Brak danych"
    assert _format_duration(0) == "poniżej 1 min"
    assert _format_duration(60) == "1 min"
    assert _format_duration(3600) == "1 godz."
    assert _format_duration(3660) == "1 godz. 1 min"


@pytest.mark.django_db
def test_login_is_rate_limited_and_default_production_password_is_forced_to_change(client):
    cache.clear()
    call_command("bootstrap_admin")
    login_url = reverse("control_login")
    for _ in range(5):
        assert client.post(login_url, {"username": "admin", "password": "wrong"}).status_code == 200

    blocked = client.post(login_url, {"username": "admin", "password": "wrong"})
    assert "Zbyt wiele" in blocked.content.decode()
    cache.clear()

    with override_settings(ENFORCE_INITIAL_ADMIN_PASSWORD_CHANGE=True):
        response = client.post(login_url, {"username": "admin", "password": "admin"})
        assert response.url == reverse("control_credentials")
        assert client.get(reverse("control_dashboard")).url == reverse("control_credentials")


@pytest.mark.django_db
def test_credentials_form_and_view_changes_username_and_password(admin_client):
    response = admin_client.post(
        reverse("control_credentials"),
        {"username": "operator", "password1": "StrongPass-123", "password2": "StrongPass-123"},
    )
    assert response.url == reverse("control_credentials")
    user = get_user_model().objects.get(username="operator")
    assert user.check_password("StrongPass-123")
    duplicate = get_user_model().objects.create_user("taken")
    form = CredentialsForm(
        user, {"username": duplicate.username, "password1": "a", "password2": "b"}
    )
    assert not form.is_valid()
    assert "zajęta" in str(form.errors)
    form = CredentialsForm(user, {"username": "operator", "password1": "", "password2": ""})
    assert form.is_valid()
    form.save()
    assert user.username == "operator"
    assert (
        admin_client.post(
            reverse("control_credentials"),
            {"username": "operator", "password1": "one", "password2": "two"},
        ).status_code
        == 200
    )


@pytest.mark.django_db
def test_credentials_form_requires_a_new_password_for_an_initial_admin():
    user = get_user_model().objects.create_superuser("operator", password="initial-secret")

    with override_settings(INITIAL_ADMIN_PASSWORD="initial-secret"):
        form = CredentialsForm(user, {"username": "renamed", "password1": "", "password2": ""})
        assert not form.is_valid()

    assert "Ustaw nowe hasło" in str(form.errors)


@pytest.mark.django_db
def test_prompt_panel_lists_and_saves_each_prompt_individually(admin_client):
    url = reverse("control_prompts")
    initial_page = admin_client.get(url).content.decode()
    assert "Prompty" in initial_page
    assert all(definition.label in initial_page for definition in PROMPT_DEFINITIONS)
    assert "control_prompts.js" in initial_page
    definition = next(item for item in PROMPT_DEFINITIONS if item.key == "news_selection")
    response = admin_client.post(
        reverse("control_prompt_update", args=[definition.key]),
        {definition.key: "Tekst news_selection"},
        HTTP_ACCEPT="application/json",
    )
    assert response.json()["message"] == "Prompt został zapisany."
    assert get_prompt("news_selection") == "Tekst news_selection"
    assert "Tekst news_selection" in admin_client.get(url).content.decode()


@pytest.mark.django_db
def test_prompt_update_rejects_empty_or_unknown_prompt(admin_client):
    empty_response = admin_client.post(
        reverse("control_prompt_update", args=["news_selection"]),
        {"news_selection": "  "},
        HTTP_ACCEPT="application/json",
    )
    assert empty_response.status_code == 400
    assert empty_response.json() == {"error": "Prompt nie może być pusty."}
    assert (
        admin_client.post(
            reverse("control_prompt_update", args=["nieznany"]),
            {"nieznany": "Tekst"},
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_recommendations_panel_edits_approves_and_regenerates(admin_client, monkeypatch):
    source = Institution.objects.create(
        name="Instytucja źródłowa", address="Rzeszów", institution_type="university"
    )
    implementing = Institution.objects.create(
        name="Instytucja wdrażająca", address="Krosno", institution_type="local_government"
    )
    idea = Idea.objects.create(
        name="Program sąsiedzki",
        submitter_name="Anna",
        email="anna@example.org",
        content="Opis",
        innovation_score=70,
        scored_at=timezone.now(),
    )
    recommendation = DevelopmentRecommendation.objects.create(
        idea=idea,
        stage="pilot",
        development_path="partnership",
        next_step="Porozmawiaj z partnerem.",
        rationale="Pomysł wymaga testu.",
        risk="Brak potwierdzenia zasobów.",
    )
    listing = admin_client.get(reverse("control_recommendations"))
    assert "Program sąsiedzki" in listing.content.decode()
    edit_url = reverse("control_recommendation_edit", args=[idea.pk])
    assert admin_client.get(edit_url).status_code == 200
    response = admin_client.post(
        edit_url,
        {
            "stage": "pilot",
            "development_path": "partnership",
            "next_step": "Ustal termin pilotażu.",
            "rationale": "Opis wskazuje lokalnych odbiorców.",
            "risk": "Nieznany budżet.",
            "status": "approved",
            "creator_name": "Anna Nowak",
            "creator_team": "Zespół sąsiedzki",
            "creator_contact": "anna@example.org",
            "institution": source.pk,
            "institution_role": "co_creator",
            "implementing_institution": implementing.pk,
        },
    )
    assert response.url == edit_url
    recommendation.refresh_from_db()
    assert recommendation.status == DevelopmentRecommendation.Status.APPROVED
    assert recommendation.approved_at is not None
    idea.refresh_from_db()
    assert (idea.creator_name, idea.creator_team, idea.creator_contact) == (
        "Anna Nowak",
        "Zespół sąsiedzki",
        "anna@example.org",
    )
    assert idea.institution == source
    assert idea.institution_role == Idea.InstitutionRole.CO_CREATOR
    assert idea.implementing_institution == implementing
    detail = admin_client.get(reverse("innovation_detail", args=[idea.pk])).content.decode()
    assert "Twórcy i pochodzenie" in detail
    assert "Instytucja źródłowa · Współtwórca" in detail
    assert "Instytucja wdrażająca" in detail
    edit_page = admin_client.get(edit_url).content.decode()
    assert "Institution object" not in edit_page
    assert 'class="provenance-field"' in edit_page
    queued = []
    monkeypatch.setattr("core.control_views.recommend_idea.delay", queued.append)
    response = admin_client.post(reverse("control_recommendation_regenerate", args=[idea.pk]))
    assert response.url == edit_url
    assert queued == [idea.pk]

    ungenerated = Idea.objects.create(
        name="Bez rekomendacji",
        submitter_name="Jan",
        email="jan@example.org",
        content="Opis",
        innovation_score=60,
        scored_at=timezone.now(),
    )
    response = admin_client.get(reverse("control_recommendation_edit", args=[ungenerated.pk]))
    assert response.url == reverse("control_recommendations")


@pytest.mark.django_db
def test_partner_panel_crud_and_csv_import(admin_client):
    add_url = reverse("control_partner_add")
    response = admin_client.post(
        add_url,
        {
            "name": "Partner testowy",
            "organization_type": "expert",
            "description": "Pomaga w badaniach.",
            "contact": "kontakt@example.org",
            "contact_url": "",
            "locality": "",
            "areas": "Badania",
            "tags_text": "badania, pilotaż",
            "is_active": "on",
        },
    )
    assert response.url == reverse("control_partners")
    partner = PartnerOrganization.objects.get(name="Partner testowy")
    assert str(partner) == "Partner testowy"
    assert set(partner.tags.values_list("key", flat=True)) == {"badania", "pilotaz"}
    edit_url = reverse("control_partner_edit", args=[partner.pk])
    assert admin_client.get(edit_url).status_code == 200
    assert "Partner testowy" in admin_client.get(reverse("control_partners")).content.decode()
    assert admin_client.post(
        edit_url,
        {
            "name": "Partner testowy",
            "organization_type": "expert",
            "description": "Pomaga w badaniach.",
            "contact": "",
            "contact_url": "",
            "locality": "",
            "areas": "Badania",
            "tags_text": "transfer",
            "is_active": "on",
        },
    ).status_code == 302
    partner.refresh_from_db()
    assert list(partner.tags.values_list("key", flat=True)) == ["transfer"]
    csv_upload = SimpleUploadedFile(
        "partnerzy.csv",
        (
            b"name,organization_type,description,contact,tags\n"
            b"Partner CSV,funder,Opis,biuro@example.org,finansowanie|transfer\n"
        ),
        content_type="text/csv",
    )
    response = admin_client.post(reverse("control_partners_csv"), {"file": csv_upload})
    assert response.status_code == 302
    assert PartnerOrganization.objects.filter(name="Partner CSV").exists()
    response = admin_client.post(reverse("control_partner_delete", args=[partner.pk]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_partner_csv_validation_and_locality_import(admin_client):
    assert admin_client.get(reverse("control_partners_csv")).status_code == 200
    assert admin_client.post(reverse("control_partners_csv"), {}).status_code == 200
    with pytest.raises(ValidationError, match="UTF-8"):
        import_partners_csv(SimpleUploadedFile("wrong.csv", b"\xff"))
    with pytest.raises(ValidationError, match="Wymagane kolumny"):
        import_partners_csv(SimpleUploadedFile("missing.csv", b"name\nBrak\n"))
    with pytest.raises(ValidationError, match="Wiersz 2"):
        import_partners_csv(
            SimpleUploadedFile(
                "bad-locality.csv",
                b"name,organization_type,description,locality_simc\nPartner,expert,Opis,0000000\n",
            )
        )
    locality = Locality.objects.create(
        simc_code="7777777",
        name="Partnerowo",
        county_code="77",
        municipality_code="77",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date=date(2026, 1, 1),
    )
    upload = SimpleUploadedFile(
        "valid.csv",
        (
            b"name;organization_type;description;locality_simc;is_active\n"
            b"Partner lokalny;user;Opis;7777777;nie\n"
        ),
    )
    assert import_partners_csv(upload) == 1
    partner = PartnerOrganization.objects.get(name="Partner lokalny")
    assert partner.locality == locality
    assert not partner.is_active
    form = PartnerOrganizationForm(
        {
            "name": "Niezapisany",
            "organization_type": "expert",
            "description": "Opis",
            "contact": "",
            "contact_url": "",
            "locality": "",
            "areas": "",
            "tags_text": "",
        }
    )
    assert form.is_valid()
    assert form.save(commit=False).pk is None


@pytest.mark.django_db
def test_prompt_panel_manages_calibration_and_examples(admin_client):
    calibration = ScoringCalibration.objects.first()
    page = admin_client.get(reverse("control_calibration"))
    assert page.status_code == 200
    assert "Kalibracja ocen" in page.content.decode()
    response = admin_client.post(reverse("control_calibration_update"), {"enabled": "on"})
    assert response.url == reverse("control_calibration")
    calibration.refresh_from_db()
    assert calibration.enabled

    payload = {
        "new-criterion": "novelty",
        "new-title": "Przykład",
        "new-description": "Opis przykładu",
        "new-score": "65",
        "new-rationale": "Uzasadnienie",
    }
    assert admin_client.post(reverse("control_calibration_example_add"), payload).status_code == 302
    example = ScoringCalibrationExample.objects.get(title="Przykład")
    assert example.calibration == calibration
    historical_example = ScoringCalibrationExample.objects.create(
        calibration=calibration,
        criterion="archival_indicator",
        title="Archiwalny przykład",
        description="Opis",
        score=40,
        rationale="Uzasadnienie",
    )
    page = admin_client.get(reverse("control_calibration")).content.decode()
    assert "Nowatorstwo — Przykład" in page
    assert f"{historical_example.criterion} — {historical_example.title}" in page
    payload.update({"new-title": "Nie powinno zostać użyte"})
    update_payload = {
        key.replace("new-", f"example-{example.pk}-"): value for key, value in payload.items()
    }
    update_payload[f"example-{example.pk}-title"] = "Zmieniony przykład"
    assert (
        admin_client.post(
            reverse("control_calibration_example_update", args=[example.pk]), update_payload
        ).status_code
        == 302
    )
    example.refresh_from_db()
    assert example.title == "Zmieniony przykład"
    assert (
        admin_client.post(
            reverse("control_calibration_example_delete", args=[example.pk])
        ).status_code
        == 302
    )
    assert not ScoringCalibrationExample.objects.filter(pk=example.pk).exists()


@pytest.mark.django_db
def test_indicator_panel_lists_dynamic_indicators_and_adds_an_indicator(admin_client):
    url = reverse("control_indicators")
    assert "Wskaźniki innowacji" in admin_client.get(url).content.decode()
    assert admin_client.get(reverse("control_indicator_add")).status_code == 200
    response = admin_client.post(
        reverse("control_indicator_add"),
        {
            "key": "accessibility",
            "name": "Dostępność",
            "question": "Czy rozwiązanie jest dostępne?",
            "weight": "0.00",
        },
    )
    assert response.url == url
    indicator = InnovationIndicator.objects.get(key="accessibility")
    assert indicator.name == "Dostępność"
    assert indicator.position == InnovationIndicator.objects.exclude(pk=indicator.pk).count() + 1
    assert str(indicator) == "Dostępność"
    edit_url = reverse("control_indicator_edit", args=[indicator.pk])
    delete_url = reverse("control_indicator_delete", args=[indicator.pk])
    assert admin_client.get(edit_url).status_code == 200
    assert (
        admin_client.post(
            edit_url,
            {
                "key": "accessibility",
                "name": "Dostępność cyfrowa",
                "question": "Czy rozwiązanie jest dostępne?",
                "weight": "0.00",
                "enabled": "on",
            },
        ).status_code
        == 302
    )
    indicator.refresh_from_db()
    assert indicator.name == "Dostępność cyfrowa"
    assert admin_client.post(delete_url).status_code == 302
    assert not InnovationIndicator.objects.filter(pk=indicator.pk).exists()


@pytest.mark.django_db
def test_indicator_panel_moves_indicators_without_exposing_manual_position_field(admin_client):
    first = InnovationIndicator.objects.create(
        key="first", name="Pierwszy", question="Pytanie", weight="0.50", position=100
    )
    second = InnovationIndicator.objects.create(
        key="second", name="Drugi", question="Pytanie", weight="0.50", position=101
    )

    add_page = admin_client.get(reverse("control_indicator_add"))
    assert 'name="position"' not in add_page.content.decode()
    response = admin_client.post(reverse("control_indicator_move", args=[second.pk, "up"]))

    assert response.url == reverse("control_indicators")
    first.refresh_from_db()
    second.refresh_from_db()
    assert (second.position, first.position) == (100, 101)
    first_indicator = InnovationIndicator.objects.first()
    first_position = first_indicator.position
    first_move_url = reverse("control_indicator_move", args=[first_indicator.pk, "up"])
    assert admin_client.post(first_move_url).status_code == 302
    first_indicator.refresh_from_db()
    assert first_indicator.position == first_position
    invalid_direction_url = reverse("control_indicator_move", args=[second.pk, "sideways"])
    assert admin_client.post(invalid_direction_url).status_code == 404


@pytest.mark.django_db
def test_indicator_configuration_updates_all_weights_atomically(admin_client):
    indicators = tuple(InnovationIndicator.objects.all())
    configuration_url = reverse("control_indicator_configuration_update")
    weights = {f"weight_{indicator.pk}": str(indicator.weight) for indicator in indicators}

    assert admin_client.post(configuration_url, weights).status_code == 400

    invalid_weights = {f"weight_{indicator.pk}": "0.00" for indicator in indicators}
    invalid_weights[f"weight_{indicators[0].pk}"] = "0.99"
    invalid_weights[f"enabled_{indicators[0].pk}"] = "on"
    invalid_response = admin_client.post(configuration_url, invalid_weights)
    assert invalid_response.status_code == 400
    assert "Suma wag aktywnych wskaźników musi wynosić dokładnie 1,00." in (
        invalid_response.content.decode()
    )

    valid_weights = {f"weight_{indicator.pk}": "0.00" for indicator in indicators}
    valid_weights[f"weight_{indicators[0].pk}"] = "1.00"
    valid_weights[f"enabled_{indicators[0].pk}"] = "on"
    assert admin_client.post(configuration_url, valid_weights).status_code == 302
    indicators[0].refresh_from_db()
    assert indicators[0].weight == 1
    assert indicators[0].enabled
    other_indicators = InnovationIndicator.objects.exclude(pk=indicators[0].pk)
    assert not other_indicators.filter(enabled=True).exists()


@pytest.mark.django_db
def test_calibration_example_panel_rejects_invalid_add_and_update(admin_client):
    invalid_payload = {
        "new-criterion": "novelty",
        "new-title": "Przykład",
        "new-description": "Opis przykładu",
        "new-score": "101",
        "new-rationale": "Uzasadnienie",
    }
    assert (
        admin_client.post(reverse("control_calibration_example_add"), invalid_payload).status_code
        == 302
    )
    assert not ScoringCalibrationExample.objects.filter(title="Przykład").exists()

    calibration = ScoringCalibration.objects.first()
    example = ScoringCalibrationExample.objects.create(
        calibration=calibration,
        criterion="novelty",
        title="Prawidłowy",
        description="Opis",
        score=50,
        rationale="Powód",
    )
    response = admin_client.post(
        reverse("control_calibration_example_update", args=[example.pk]),
        {f"example-{example.pk}-score": "101"},
    )
    assert response.status_code == 302
    example.refresh_from_db()
    assert example.score == 50


@pytest.mark.django_db
def test_prompt_store_requires_existing_nonempty_content():
    PromptTemplate.objects.filter(key="news_selection").delete()
    with pytest.raises(PromptNotConfiguredError, match="news_selection"):
        get_prompt("news_selection")
    PromptTemplate.objects.create(key="news_selection", content="   ")
    with pytest.raises(PromptNotConfiguredError, match="news_selection"):
        get_prompt("news_selection")


@pytest.mark.django_db
def test_institution_panel_crud_csv_and_listing(admin_client, monkeypatch):
    locality = create_locality()
    payload = {
        "name": "Uczelnia A",
        "address": "Rzeszów",
        "institution_type": "university",
        "locality": locality.pk,
        "news_url": "https://example.org/news",
        "additional_news_urls": "https://example.org/a\nhttps://example.org/b",
    }
    add_url = reverse("control_institution_add")
    assert admin_client.get(add_url).status_code == 200
    assert admin_client.post(add_url, payload).url == reverse("control_institutions")
    institution = Institution.objects.get(name="Uczelnia A")
    assert InstitutionNewsSource.objects.filter(institution=institution).count() == 2
    payload.update({"name": "Uczelnia B", "additional_news_urls": "https://example.org/c"})
    response = admin_client.post(
        reverse("control_institution_edit", args=[institution.pk]), payload
    )
    assert response.status_code == 302
    institution.refresh_from_db()
    assert institution.name == "Uczelnia B"
    assert list(institution.news_sources.values_list("url", flat=True)) == ["https://example.org/c"]
    Idea.objects.create(
        name="Innowacja uczelni",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Opis innowacji.",
        institution=institution,
        published_at=date(2026, 11, 15),
    )
    filtered = admin_client.get(
        reverse("control_institutions"),
        {
            "institution_type": "university",
            "locality": locality.pk,
            "published_from": "2026-11-01",
            "published_to": "2026-11-30",
        },
    ).content.decode()
    assert "Uczelnia B" in filtered
    assert "Dodaj instytucję" in filtered and "Import CSV" in filtered
    assert "Szukaj" not in filtered
    assert "Data publikacji od" in filtered
    for filter_params in (
        {"institution_type": "university"},
        {"locality": locality.pk},
        {"published_from": "2026-11-01"},
        {"published_to": "2026-11-30"},
    ):
        assert admin_client.get(reverse("control_institutions"), filter_params).status_code == 200
    assert (
        "Data końcowa nie może być wcześniejsza"
        in admin_client.get(
            reverse("control_institutions"),
            {"published_from": "2026-12-01", "published_to": "2026-11-01"},
        ).content.decode()
    )
    assert admin_client.get(reverse("control_institutions")).status_code == 200
    assert admin_client.get(reverse("control_institutions_csv")).status_code == 200
    assert admin_client.post(reverse("control_institutions_csv"), {}).status_code == 200
    csv_file = SimpleUploadedFile(
        "institutions.csv",
        b"name,address,institution_type,locality_simc,news_url\nSzkola,Rzeszow,school,0654321,https://example.org/s\n",
    )
    response = admin_client.post(reverse("control_institutions_csv"), {"file": csv_file})
    assert response.status_code == 302
    response = admin_client.post(reverse("control_institution_delete", args=[institution.pk]))
    assert response.status_code == 302
    assert not Institution.objects.filter(pk=institution.pk).exists()
    bad_form = InstitutionPanelForm({**payload, "additional_news_urls": "not-a-url"})
    assert not bad_form.is_valid()
    assert not InstitutionPanelForm({**payload, "locality": ""}).is_valid()
    new_form = InstitutionPanelForm({**payload, "name": "Bez zapisu", "additional_news_urls": ""})
    assert new_form.is_valid()
    assert new_form.save(commit=False).pk is None
    assert _locality_label(institution).startswith("Rzeszów,")
    assert _locality_label(None) == ""


@pytest.mark.django_db
def test_crawling_page_starts_job_and_returns_live_status(admin_client, monkeypatch):
    Institution.objects.create(name="Szkoła", address="Rzeszów", institution_type="school")
    task_calls = []
    monkeypatch.setattr("core.control_views.import_institution_news.delay", task_calls.append)
    url = reverse("control_crawling")
    assert admin_client.get(url).status_code == 200
    CrawlSchedule.objects.filter(pk=1).update(institution_types=["school"])
    response = admin_client.post(url)
    assert response.url == url
    run = InstitutionImportRun.objects.get()
    assert task_calls == [run.pk]
    assert run.institutions_total == 1
    page = admin_client.get(url).content.decode()
    assert "Zakres crawlowania" in page
    assert "Źródła aktualności oraz ich włączenie" not in page
    assert admin_client.post(url).status_code == 200
    InstitutionImportEvent.objects.create(run=run, message="Skanowanie: Szkoła")
    run.status = "running"
    run.institutions_total = 2
    run.institutions_processed = 1
    run.started_at = timezone.now() - timedelta(minutes=10)
    run.save(update_fields=["status", "institutions_total", "institutions_processed", "started_at"])
    data = admin_client.get(reverse("control_crawling_status")).json()["run"]
    assert 599 <= data["eta_seconds"] <= 601
    assert data["total"] == 2
    assert data["events"][0]["message"] == "Skanowanie: Szkoła"
    assert len(data["events"][0]["time"]) == 8
    run.institutions_total = 0
    run.institutions_processed = 8
    run.save(update_fields=["institutions_total", "institutions_processed"])
    final_status = admin_client.get(reverse("control_crawling_status")).json()["run"]
    assert final_status["total"] == 8
    assert final_status["eta_seconds"] is None
    response = admin_client.post(reverse("control_crawling_stop"))
    assert response.url == url
    run.refresh_from_db()
    assert run.status == "stopped"
    assert "zatrzymany" in run.events.first().message
    assert admin_client.post(reverse("control_crawling_stop")).status_code == 302


@pytest.mark.django_db
def test_ncbr_crawling_has_an_independent_run_and_live_status(admin_client, monkeypatch):
    calls = []
    monkeypatch.setattr("core.control_views.import_ncbr_projects.delay", calls.append)

    page = admin_client.get(reverse("control_crawling")).content.decode()
    assert "Crawling NCBR" in page
    assert "Nie uruchomiono jeszcze crawlera NCBR." in page
    assert 'core/js/control_crawling.js?v=2' in page
    assert admin_client.get(reverse("control_ncbr_crawling_status")).json() == {"run": None}

    response = admin_client.post(reverse("control_ncbr_crawling"))
    assert response.url == reverse("control_crawling")
    run = NCBRImportRun.objects.get()
    assert calls == [run.pk]
    assert admin_client.post(reverse("control_ncbr_crawling")).status_code == 302
    assert NCBRImportRun.objects.count() == 1

    run.status = "completed"
    run.projects_total = 3
    run.projects_processed = 3
    run.ideas_created = 2
    run.ideas_skipped = 1
    run.current_action = "Import projektów NCBR zakończony"
    run.save()
    run.events.create(message="Zakończono import")
    status = admin_client.get(reverse("control_ncbr_crawling_status")).json()["run"]
    assert status["total"] == status["processed"] == 3
    assert status["created"] == 2
    assert status["eta_seconds"] is None
    assert status["events"][0]["message"] == "Zakończono import"


@pytest.mark.django_db
def test_crawl_schedule_is_saved_in_the_panel_and_calculates_next_run(admin_client):
    url = reverse("control_crawling_schedule")
    response = admin_client.post(
        url,
        {
            "enabled": "on", "interval_days": "3", "run_at": "04:15",
            "institution_types": ["school"], "voivodeship_code": "18",
        },
    )
    assert response.url == reverse("control_crawling")
    schedule = CrawlSchedule.objects.get(pk=1)
    assert schedule.enabled is True
    assert schedule.interval_days == 3
    assert schedule.run_at == time(4, 15)
    assert schedule.institution_types == ["school"]
    assert schedule.voivodeship_code == "18"
    assert schedule.next_run_at > timezone.now()
    page = admin_client.get(reverse("control_crawling")).content.decode()
    assert "Automatyczny crawling" in page
    assert "Następne uruchomienie" in page

    response = admin_client.post(
        url,
        {"enabled": "on", "interval_days": "0", "run_at": "04:15", "institution_types": ["school"]},
    )
    assert response.url == reverse("control_crawling")
    assert CrawlScheduleForm(
        {"interval_days": "366", "run_at": "04:15", "institution_types": ["school"]}
    ).is_valid() is False
    assert CrawlScheduleForm({"interval_days": "3", "run_at": "04:15"}).is_valid() is False

    response = admin_client.post(
        url, {"interval_days": "3", "run_at": "04:15", "institution_types": ["school"]}
    )
    assert response.url == reverse("control_crawling")
    schedule.refresh_from_db()
    assert schedule.enabled is False
    assert schedule.next_run_at is None


@pytest.mark.django_db
def test_scheduled_crawl_starts_all_types_once_due_and_waits_for_active_run():
    Institution.objects.create(name="Uczelnia", address="Rzeszów", institution_type="university")
    Institution.objects.create(name="Szkoła", address="Krosno", institution_type="school")
    Institution.objects.create(name="Gmina", address="Sanok", institution_type="local_government")
    now = timezone.make_aware(datetime(2026, 11, 20, 10, 0))
    schedule = CrawlSchedule.objects.create(
        pk=1,
        enabled=True,
        interval_days=2,
        run_at=time(9),
        next_run_at=now - timedelta(minutes=1),
    )

    run = start_due_crawl(now)
    assert run is not None
    assert set(run.institution_types) == set(Institution.Type.values)
    assert run.institutions_total == 3
    assert "Automatyczny crawling" in run.events.get().message
    schedule.refresh_from_db()
    assert schedule.last_started_at == now
    assert schedule.next_run_at == timezone.make_aware(datetime(2026, 11, 22, 9))
    assert start_due_crawl(now) is None

    schedule.next_run_at = now - timedelta(minutes=1)
    schedule.save(update_fields=["next_run_at"])
    assert start_due_crawl(now) is None

    run.status = "stopped"
    run.save(update_fields=["status"])
    schedule.next_run_at = now + timedelta(minutes=1)
    schedule.save(update_fields=["next_run_at"])
    assert start_due_crawl(now) is None

    schedule.enabled = False
    schedule.save(update_fields=["enabled"])
    assert start_due_crawl(now + timedelta(days=1)) is None


@pytest.mark.django_db
def test_crawl_configuration_limits_region_and_allows_disabling_a_source():
    podkarpackie = create_locality()
    mazowieckie = Locality.objects.create(
        simc_code="1465432", name="Warszawa", voivodeship_code="14", county_code="65",
        municipality_code="01", municipality_type_code="1", locality_type_code="96",
        registry_date="2026-01-01",
    )
    Institution.objects.create(
        name="Aktywna", address="Rzeszów", institution_type="school", locality=podkarpackie
    )
    Institution.objects.create(
        name="Wyłączona", address="Krosno", institution_type="school", locality=podkarpackie,
        crawl_enabled=False,
    )
    Institution.objects.create(
        name="Poza regionem", address="Warszawa", institution_type="school", locality=mazowieckie
    )
    now = timezone.make_aware(datetime(2026, 11, 20, 10, 0))
    CrawlSchedule.objects.create(
        pk=1, enabled=True, run_at=time(9), next_run_at=now - timedelta(minutes=1),
        institution_types=["school"], voivodeship_code="18",
    )

    run = start_due_crawl(now)

    assert run is not None
    assert run.institution_types == ["school"]
    assert run.voivodeship_code == "18"
    assert run.institutions_total == 1


@pytest.mark.django_db
def test_next_crawl_at_uses_next_day_after_the_configured_hour():
    schedule = CrawlSchedule(run_at=time(9))
    now = timezone.make_aware(datetime(2026, 11, 20, 10))
    assert next_crawl_at(schedule, now) == timezone.make_aware(datetime(2026, 11, 21, 9))
    assert next_crawl_at(schedule, now - timedelta(hours=2)) == timezone.make_aware(
        datetime(2026, 11, 20, 9)
    )


@pytest.mark.django_db
def test_scheduled_crawl_creates_a_disabled_default_schedule_when_missing():
    now = timezone.make_aware(datetime(2026, 11, 20, 10))
    assert start_due_crawl(now) is None
    schedule = CrawlSchedule.objects.get(pk=1)
    assert schedule.enabled is False
    assert schedule.run_at == time(3)


@pytest.mark.django_db
def test_scheduled_crawl_task_queues_only_a_due_run(monkeypatch):
    run = InstitutionImportRun.objects.create(status="pending")
    queued = []
    monkeypatch.setattr("core.tasks.start_due_crawl", lambda: run)
    monkeypatch.setattr("core.tasks.import_institution_news.delay", queued.append)
    start_scheduled_institution_import()
    assert queued == [run.pk]

    monkeypatch.setattr("core.tasks.start_due_crawl", lambda: None)
    start_scheduled_institution_import()
    assert queued == [run.pk]


@pytest.mark.django_db
def test_crawling_status_without_a_run(admin_client):
    assert admin_client.get(reverse("control_crawling_status")).json() == {"run": None}


@pytest.mark.django_db
def test_import_task_tracks_success_failure_and_pending_run(monkeypatch):
    first = Institution.objects.create(name="A", address="Rzeszów", institution_type="school")
    Institution.objects.create(name="B", address="Krosno", institution_type="school")
    run = InstitutionImportRun.objects.create(
        institution_types=["school"],
        institutions_total=2,
        status="pending",
        article_queue=[{"title": "Artykuł", "url": "https://a", "published_on": None}],
    )

    class Service:
        discovery = type(
            "Discovery",
            (),
            {
                "reporter": None,
                "source_urls": lambda *_: ("https://a",),
                "selected_articles": lambda *_: (),
                "extract_article": lambda *_: None,
            },
        )()

        def import_article(self, institution, article, reporter=None):
            return InstitutionImportResult(created=1, skipped=2)

    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", Service)
    scheduled = []
    monkeypatch.setattr("core.tasks.import_institution_news.delay", scheduled.append)
    import_institution_news(run.pk)
    run.refresh_from_db()
    assert (run.status, run.institutions_processed, run.ideas_created, run.ideas_skipped) == (
        "pending",
        0,
        1,
        2,
    )
    assert scheduled == [run.pk]
    for _ in range(7):
        import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.status == "completed"
    assert run.events.count() >= 5
    import_institution_news(run.pk)
    assert first.pk
    failed = InstitutionImportRun.objects.create(institution_types=["school"], status="pending")
    failed.article_queue = [{"title": "Artykuł", "url": "https://a", "published_on": None}]
    failed.save(update_fields=["article_queue"])

    class BrokenService:
        discovery = type(
            "Discovery",
            (),
            {
                "reporter": None,
                "source_urls": lambda *_: ("https://a",),
                "extract_article": lambda *_: None,
            },
        )()

        def import_article(self, institution, article, reporter=None):
            raise RuntimeError("awaria")

    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", BrokenService)
    with pytest.raises(RuntimeError, match="awaria"):
        import_institution_news(failed.pk)
    failed.refresh_from_db()
    assert failed.status == "failed" and "awaria" in failed.error


@pytest.mark.django_db
def test_import_task_does_not_schedule_another_step_after_stopping(monkeypatch):
    Institution.objects.create(name="A", address="Rzeszów", institution_type="school")
    run = InstitutionImportRun.objects.create(
        institution_types=["school"],
        status="pending",
        article_queue=[{"title": "Artykuł", "url": "https://a", "published_on": None}],
    )

    class Service:
        discovery = type(
            "Discovery",
            (),
            {
                "reporter": None,
                "source_urls": lambda *_: ("https://a",),
                "extract_article": lambda *_: None,
            },
        )()

        def import_article(self, institution, article, reporter=None):
            InstitutionImportRun.objects.filter(pk=run.pk).update(status="stopped")
            return InstitutionImportResult(created=1, skipped=0)

    scheduled = []
    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", Service)
    monkeypatch.setattr("core.tasks.import_institution_news.delay", scheduled.append)
    import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.status == "stopped"
    assert scheduled == []


@pytest.mark.django_db
def test_stopped_task_does_not_replace_stopped_status_with_failure(monkeypatch):
    Institution.objects.create(name="A", address="Rzeszów", institution_type="school")
    run = InstitutionImportRun.objects.create(
        institution_types=["school"],
        status="pending",
        article_queue=[{"title": "Artykuł", "url": "https://a", "published_on": None}],
    )

    class Service:
        discovery = type(
            "Discovery",
            (),
            {
                "reporter": None,
                "source_urls": lambda *_: ("https://a",),
                "extract_article": lambda *_: None,
            },
        )()

        def import_article(self, institution, article, reporter=None):
            InstitutionImportRun.objects.filter(pk=run.pk).update(status="stopped")
            raise RuntimeError("awaria po zatrzymaniu")

    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", Service)
    with pytest.raises(RuntimeError, match="awaria po zatrzymaniu"):
        import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.status == "stopped"


@pytest.mark.django_db
def test_import_task_retries_after_soft_timeout(monkeypatch):
    Institution.objects.create(name="A", address="Rzeszów", institution_type="school")
    run = InstitutionImportRun.objects.create(
        institution_types=["school"],
        status="pending",
        article_queue=[{"title": "Artykuł", "url": "https://a", "published_on": None}],
    )

    class Service:
        discovery = type(
            "Discovery",
            (),
            {
                "reporter": None,
                "source_urls": lambda *_: ("https://a",),
                "extract_article": lambda *_: None,
            },
        )()

        def import_article(self, institution, article, reporter=None):
            raise SoftTimeLimitExceeded()

    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", Service)
    with (
        patch.object(import_institution_news, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.status == "pending"
    assert "automatyczne wznowienie za 10 s" in run.current_action
    assert "Limit czasu" in run.events.first().message
    assert retry.call_args.kwargs["countdown"] == 10
    assert import_institution_news.max_retries is None
    assert run.retry_after > timezone.now()


@pytest.mark.django_db
def test_recovery_reschedules_due_and_stalled_imports_without_early_retry(monkeypatch):
    due = InstitutionImportRun.objects.create(institution_types=["school"], status="pending")
    delayed = InstitutionImportRun.objects.create(
        institution_types=["school"],
        status="pending",
        retry_after=timezone.now() + timedelta(minutes=1),
    )
    stale = InstitutionImportRun.objects.create(
        institution_types=["school"],
        status="running",
        heartbeat_at=timezone.now() - timedelta(minutes=4),
    )
    active = InstitutionImportRun.objects.create(
        institution_types=["school"], status="running", heartbeat_at=timezone.now()
    )
    stopped = InstitutionImportRun.objects.create(institution_types=["school"], status="stopped")
    scheduled = []
    monkeypatch.setattr("core.tasks.import_institution_news.delay", scheduled.append)

    recover_institution_imports()

    stale.refresh_from_db()
    assert stale.status == "pending"
    assert "utracie workera" in stale.current_action
    assert "utracie workera" in stale.events.first().message
    assert set(scheduled) == {due.pk, stale.pk}
    assert delayed.pk not in scheduled
    assert active.status == "running"
    assert stopped.status == "stopped"

    InstitutionImportRun.objects.filter(pk__in=[due.pk, stale.pk]).update(status="stopped")
    scheduled.clear()
    recover_institution_imports()
    assert scheduled == []


@pytest.mark.django_db
def test_import_task_skips_institution_without_sources_and_respects_stop_on_timeout(monkeypatch):
    Institution.objects.create(name="Bez źródła", address="Rzeszów", institution_type="school")
    run = InstitutionImportRun.objects.create(institution_types=["school"], status="pending")

    class NoSourceService:
        discovery = type("Discovery", (), {"reporter": None, "source_urls": lambda *_: ()})()

    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", NoSourceService)
    scheduled = []
    monkeypatch.setattr("core.tasks.import_institution_news.delay", scheduled.append)
    import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.institutions_processed == 1
    assert run.status == "pending"
    assert scheduled == [run.pk]

    class NoContinuationService:
        class discovery:
            reporter = None

            @staticmethod
            def source_urls(_institution):
                InstitutionImportRun.objects.filter(pk=run.pk).update(status="stopped")
                return ()

    run.institutions_processed = 0
    run.status = "pending"
    run.save(update_fields=["institutions_processed", "status"])
    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", NoContinuationService)
    import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.status == "stopped"

    class StoppedService:
        discovery = type(
            "Discovery",
            (),
            {
                "reporter": None,
                "source_urls": lambda *_: ("https://a",),
                "extract_article": lambda *_: None,
            },
        )()

        def import_article(self, institution, article, reporter=None):
            InstitutionImportRun.objects.filter(pk=run.pk).update(status="stopped")
            raise SoftTimeLimitExceeded()

    run.institutions_processed = 0
    run.status = "pending"
    run.article_queue = [{"title": "Artykuł", "url": "https://a", "published_on": None}]
    run.save(update_fields=["institutions_processed", "status", "article_queue"])
    monkeypatch.setattr("core.tasks.InstitutionInnovationImportService", StoppedService)
    import_institution_news(run.pk)
    run.refresh_from_db()
    assert run.status == "stopped"


@pytest.mark.django_db
def test_import_single_institution_creates_and_skips_duplicate(monkeypatch):
    institution = Institution.objects.create(
        name="Szkoła", address="Rzeszów", institution_type="school"
    )
    article = NewsArticle("Robot", "https://example.org/robot", "Opis", canonical_name="Robot")
    discovery = type("Discovery", (), {"discover": lambda self, _: (article,)})()
    service = InstitutionInnovationImportService(discovery=discovery)
    monkeypatch.setattr(
        service,
        "_create_idea",
        lambda owner, found: Idea.objects.create(
            name=found.title, institution=owner, source_url=found.url, content=found.body
        ),
    )
    events = []
    result = service.import_institution(institution, reporter=events.append)
    assert result == InstitutionImportResult(created=1, skipped=0)
    assert events == ["Ocenianie innowacji: Robot", "Dodano innowację: Robot"]
    assert service.import_institution(institution) == InstitutionImportResult(created=0, skipped=1)
    second = NewsArticle("Czujnik", "https://example.org/czujnik", "Opis", canonical_name="Czujnik")
    discovery.discover = lambda _: (second,)
    assert service.import_institution(institution) == InstitutionImportResult(created=1, skipped=0)
    assert service.import_article(institution, None) == InstitutionImportResult(
        created=0, skipped=0
    )
    assert service.import_article(institution, article) == InstitutionImportResult(
        created=0, skipped=1
    )
    events = []
    third = NewsArticle("Aplikacja", "https://example.org/aplikacja", "Opis")
    result = service.import_article(institution, third, reporter=events.append)
    assert result == InstitutionImportResult(created=1, skipped=0)
    assert events == ["Ocenianie innowacji: Aplikacja", "Dodano innowację: Aplikacja"]
    fourth = NewsArticle("Platforma", "https://example.org/platforma", "Opis")
    assert service.import_article(institution, fourth) == InstitutionImportResult(
        created=1, skipped=0
    )


def test_article_checkpoint_serialization_preserves_publication_date():
    serialized = serialize_article(
        SelectedNewsArticle("Projekt", "https://example.org/projekt", date(2026, 11, 19))
    )
    assert serialized == {
        "title": "Projekt",
        "url": "https://example.org/projekt",
        "published_on": "2026-11-19",
    }
    assert deserialize_article(serialized) == SelectedNewsArticle(
        "Projekt", "https://example.org/projekt", date(2026, 11, 19)
    )


@pytest.mark.django_db
def test_checkpoint_can_update_queue_without_changing_article_index(monkeypatch):
    run = InstitutionImportRun.objects.create(status="running")
    scheduled = []
    monkeypatch.setattr("core.tasks.import_institution_news.delay", scheduled.append)
    continue_import_run(run, schedule=scheduled.append, article_queue=[])
    run.refresh_from_db()
    assert run.status == "pending"
    assert run.article_queue == []
    assert run.article_index == 0
    assert scheduled == [run.pk]
