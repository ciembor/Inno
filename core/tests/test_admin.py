import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from core.models import Institution, InstitutionNewsSource
from core.services.institution_csv import import_institutions_csv
from core.tests.test_integration import create_locality

HEADER = "name,address,institution_type,locality_simc,news_url,additional_news_urls\n"
ROW = "Uczelnia,Rzeszów,university,0654321,https://example.org/news,https://example.org/extra\n"


def csv_upload(text):
    return SimpleUploadedFile("institutions.csv", text.encode("utf-8"))


@pytest.mark.django_db
def test_bootstrap_password_change_survives_repeated_bootstrap(client):
    call_command("bootstrap_admin")
    assert client.login(username="admin", password="admin")
    response = client.post(
        reverse("control_credentials"),
        {
            "username": "admin",
            "password1": "NewPass-12345",
            "password2": "NewPass-12345",
        },
    )
    assert response.status_code == 302
    call_command("bootstrap_admin")
    user = get_user_model().objects.get(username="admin")
    assert user.check_password("NewPass-12345")
    assert user.is_superuser and user.is_staff


@pytest.mark.django_db
def test_legacy_django_admin_address_redirects_to_custom_panel(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert response.url == reverse("control_dashboard")


@pytest.mark.django_db
def test_csv_is_idempotent_and_accepts_bom_semicolon():
    create_locality()
    for text in [HEADER + ROW, "\ufeff" + (HEADER + ROW).replace(",", ";")]:
        assert import_institutions_csv(csv_upload(text)) == 1
    assert Institution.objects.count() == 1
    assert InstitutionNewsSource.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "text",
    [
        "",
        "wrong",
        HEADER + ROW + ROW.replace("0654321", "0000000"),
        HEADER + ROW + ROW.replace("https://example.org/extra", "bad-url"),
    ],
)
def test_invalid_csv_rolls_back_every_row(text):
    create_locality()
    with pytest.raises(ValidationError):
        import_institutions_csv(csv_upload(text))
    assert Institution.objects.count() == 0


@pytest.mark.django_db
def test_csv_rejects_invalid_encoding():
    with pytest.raises(ValidationError, match="UTF-8"):
        import_institutions_csv(SimpleUploadedFile("bad.csv", b"\xff"))


@pytest.mark.django_db
def test_csv_accepts_missing_optional_links():
    create_locality()
    assert (
        import_institutions_csv(
            csv_upload(
                HEADER.replace(",additional_news_urls", "")
                + ROW.replace(",https://example.org/extra", "")
            )
        )
        == 1
    )
    assert InstitutionNewsSource.objects.count() == 0
