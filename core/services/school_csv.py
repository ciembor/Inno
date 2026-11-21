"""Import szkół z pliku rankingu Podkarpacia do katalogu instytucji."""

import csv

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from core.models import Institution, InstitutionNewsSource, Locality

REQUIRED_COLUMNS = {
    "Nazwa szkoły",
    "Miejscowość",
    "Zweryfikowany URL aktualności",
    "Poprzedni URL",
    "locality_simc",
}


@transaction.atomic
def import_schools_csv(file):
    reader = csv.DictReader(file)
    if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
        raise ValidationError("Plik nie zawiera wymaganych kolumn rankingu szkół.")
    count = 0
    for number, row in enumerate(reader, 2):
        try:
            import_school(row)
        except (Locality.DoesNotExist, ValidationError) as error:
            raise ValidationError(f"Wiersz {number}: {error}") from error
        count += 1
    return count


def import_school(row):
    name = row["Nazwa szkoły"].strip()
    address = row["Miejscowość"].strip()
    if not name or not address:
        raise ValidationError("Brak nazwy szkoły lub miejscowości.")
    locality = Locality.objects.get(pk=row["locality_simc"].strip())
    news_url = (row["Zweryfikowany URL aktualności"] or row["Poprzedni URL"]).strip()
    if news_url:
        URLValidator(schemes=["http", "https"])(news_url)
    institution, _ = Institution.objects.update_or_create(
        name=name,
        address=address,
        defaults={"institution_type": "school", "locality": locality, "news_url": news_url},
    )
    if news_url:
        InstitutionNewsSource.objects.get_or_create(institution=institution, url=news_url)
