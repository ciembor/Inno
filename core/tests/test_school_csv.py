from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands import import_schools_csv as import_schools_command
from core.models import Institution, InstitutionNewsSource
from core.services.school_csv import import_schools_csv
from core.tests.test_integration import create_locality

HEADER = "Nazwa szkoły,Miejscowość,Zweryfikowany URL aktualności,Poprzedni URL,locality_simc\n"


def rows(*values):
    return StringIO(HEADER + "\n".join(values))


@pytest.mark.django_db
def test_school_csv_imports_verified_url_and_falls_back_to_previous_url():
    create_locality()
    count = import_schools_csv(
        rows(
            "Szkoła A,Rzeszów,https://school-a.example/news,https://old.example,0654321",
            "Szkoła B,Rzeszów,,https://school-b.example/news,0654321",
            "Szkoła C,Rzeszów,,,0654321",
        )
    )
    assert count == 3
    assert list(Institution.objects.values_list("institution_type", flat=True)) == [
        "school",
        "school",
        "school",
    ]
    assert Institution.objects.get(name="Szkoła A").news_url == "https://school-a.example/news"
    assert Institution.objects.get(name="Szkoła B").news_url == "https://school-b.example/news"
    assert Institution.objects.get(name="Szkoła C").news_url == ""
    assert InstitutionNewsSource.objects.count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [
        "wrong\n",
        HEADER + ",Rzeszów,,,0654321\n",
        HEADER + "Szkoła,Rzeszów,,,0000000\n",
        HEADER + "Szkoła,Rzeszów,bad-url,,0654321\n",
    ],
)
def test_school_csv_rejects_invalid_rows_atomically(content):
    create_locality()
    with pytest.raises(ValidationError):
        import_schools_csv(StringIO(content))
    assert Institution.objects.count() == 0


@pytest.mark.django_db
def test_school_csv_command_imports_file_and_reports_missing_file(tmp_path, capsys):
    create_locality()
    csv_path = tmp_path / "schools.csv"
    csv_path.write_text(HEADER + "Szkoła,Rzeszów,,,0654321\n", encoding="utf-8")
    call_command("import_schools_csv", csv_path)
    assert "Zapisano 1 szkół" in capsys.readouterr().out
    with pytest.raises(CommandError, match="Nie znaleziono"):
        call_command("import_schools_csv", tmp_path / "missing.csv")


def test_school_csv_command_rejects_non_utf8(monkeypatch, tmp_path):
    path = tmp_path / "schools.csv"
    path.touch()
    monkeypatch.setattr(
        import_schools_command.Path,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")
        ),
    )
    with pytest.raises(CommandError, match="UTF-8"):
        call_command("import_schools_csv", path)
