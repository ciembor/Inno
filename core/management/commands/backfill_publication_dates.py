"""Uzupełnia daty publikacji dla wcześniej zaimportowanych innowacji."""

from django.core.management.base import BaseCommand

from core.models import Idea
from core.services.publication_dates import PublicationDateService


class Command(BaseCommand):
    help = "Pobiera przez LLM daty publikacji źródłowych artykułów innowacji."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        ideas = Idea.objects.filter(published_at__isnull=True).exclude(source_url__isnull=True)
        ideas = ideas.exclude(source_url="").order_by("pk")
        if options["limit"]:
            ideas = ideas[: options["limit"]]
        service = PublicationDateService()
        updated = missing = 0
        for idea in ideas:
            published_at = service.extract(idea.name, idea.source_url)
            if published_at:
                idea.published_at = published_at
                idea.save(update_fields=["published_at"])
                updated += 1
            else:
                missing += 1
        self.stdout.write(self.style.SUCCESS(f"Zapisano daty: {updated}. Bez daty: {missing}."))
