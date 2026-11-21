"""Importuje referencyjny katalog instytucji i źródeł aktualności."""

from django.core.management.base import BaseCommand

from core.data.institutions import ADDITIONAL_NEWS_SOURCES, INSTITUTIONS
from core.models import Institution, InstitutionNewsSource


class Command(BaseCommand):
    help = "Dodaje katalog podkarpackich uczelni do tabeli instytucji."

    def handle(self, *args, **options):
        for name, address, news_url in INSTITUTIONS:
            institution, _ = Institution.objects.update_or_create(
                name=name,
                address=address,
                defaults={"news_url": news_url, "institution_type": Institution.Type.UNIVERSITY},
            )
            InstitutionNewsSource.objects.get_or_create(institution=institution, url=news_url)
        for name, address, news_url in ADDITIONAL_NEWS_SOURCES:
            institution = Institution.objects.get(name=name, address=address)
            InstitutionNewsSource.objects.get_or_create(institution=institution, url=news_url)
        self.stdout.write(self.style.SUCCESS(f"Zapisano {len(INSTITUTIONS)} uczelni."))
