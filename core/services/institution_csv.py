"""Atomowy import instytucji i dodatkowych źródeł z CSV UTF-8."""

import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from core.models import Institution, InstitutionNewsSource, Locality


@transaction.atomic
def import_institutions_csv(upload):
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationError("Plik musi mieć kodowanie UTF-8.") from error
    delimiter = ";" if ";" in text.partition("\n")[0] else ","
    reader = csv.DictReader(StringIO(text), delimiter=delimiter, strict=True)
    required = {"name", "address", "institution_type", "locality_simc", "news_url"}
    if not required.issubset(reader.fieldnames or []):
        raise ValidationError("Wymagane kolumny: " + ", ".join(sorted(required)))
    count = 0
    for number, row in enumerate(reader, 2):
        try:
            count += import_row(row)
        except (
            ValidationError,
            Locality.DoesNotExist,
            Institution.MultipleObjectsReturned,
        ) as error:
            raise ValidationError(f"Wiersz {number}: {error}") from error
    return count


def import_row(row):
    values = {
        key: (row.get(key) or "").strip()
        for key in (
            "name",
            "address",
            "institution_type",
            "news_url",
            "locality_simc",
            "additional_news_urls",
        )
    }
    locality = Locality.objects.get(pk=values.pop("locality_simc"))
    links = [url.strip() for url in values.pop("additional_news_urls").split("|") if url.strip()]
    candidate = Institution(**values, locality=locality)
    candidate.full_clean()
    for url in links:
        URLValidator(schemes=["http", "https"])(url)
        InstitutionNewsSource(url=url).full_clean(exclude=["institution"])
    institution, _ = Institution.objects.update_or_create(
        name=values.pop("name"),
        address=values.pop("address"),
        defaults={**values, "locality": locality},
    )
    for url in links:
        InstitutionNewsSource.objects.get_or_create(institution=institution, url=url)
    return 1
