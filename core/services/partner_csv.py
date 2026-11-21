"""Atomowy import bazy partnerów z pliku CSV UTF-8."""

import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from core.models import Locality, PartnerOrganization, PartnerTag

REQUIRED_COLUMNS = {"name", "organization_type", "description"}


@transaction.atomic
def import_partners_csv(upload) -> int:
    """Importuje partnerów oraz ich tagi, zastępując rekordy o tej samej nazwie."""
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationError("Plik musi mieć kodowanie UTF-8.") from error
    delimiter = ";" if ";" in text.partition("\n")[0] else ","
    reader = csv.DictReader(StringIO(text), delimiter=delimiter, strict=True)
    if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
        raise ValidationError("Wymagane kolumny: " + ", ".join(sorted(REQUIRED_COLUMNS)))
    for number, row in enumerate(reader, 2):
        try:
            _import_partner_row(row)
        except (ValidationError, Locality.DoesNotExist) as error:
            raise ValidationError(f"Wiersz {number}: {error}") from error
    return reader.line_num - 1


def _import_partner_row(row: dict[str, str | None]) -> None:
    values = {key: (row.get(key) or "").strip() for key in row}
    locality = None
    if values.get("locality_simc"):
        locality = Locality.objects.get(pk=values["locality_simc"])
    partner, _ = PartnerOrganization.objects.update_or_create(
        name=values["name"],
        defaults={
            "organization_type": values["organization_type"],
            "description": values["description"],
            "contact": values.get("contact", ""),
            "contact_url": values.get("contact_url", ""),
            "locality": locality,
            "areas": values.get("areas", ""),
            "is_active": values.get("is_active", "true").lower() not in {"0", "false", "nie"},
        },
    )
    partner.full_clean()
    tags = []
    for name in {item.strip() for item in values.get("tags", "").split("|") if item.strip()}:
        tag, _ = PartnerTag.objects.get_or_create(key=slugify(name), defaults={"name": name})
        tags.append(tag)
    partner.tags.set(tags)
