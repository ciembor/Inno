"""Uzupełnia taksonomię podobieństwa dla istniejących inicjatyw."""

from django.core.management.base import BaseCommand

from core.models import Idea
from core.services.idea_similarity import IdeaTaxonomyError, classify_idea


class Command(BaseCommand):
    help = "Nadaje przez LLM tagi podobieństwa istniejącym inicjatywom."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Nadaj tagi także już otagowanym.")
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        ideas = Idea.objects.order_by("pk")
        if not options["all"]:
            ideas = ideas.filter(similarity_tags__isnull=True)
        if options["limit"]:
            ideas = ideas[: options["limit"]]
        tagged = failed = 0
        for idea in ideas:
            try:
                classify_idea(idea)
            except IdeaTaxonomyError as error:
                failed += 1
                self.stderr.write(f"{idea.pk}: {error}")
            else:
                tagged += 1
        self.stdout.write(self.style.SUCCESS(f"Otagowano: {tagged}. Błędy: {failed}."))
