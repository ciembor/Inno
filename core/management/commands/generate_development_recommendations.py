"""Kolejkuje brakujące rekomendacje rozwoju dla już ocenionych innowacji."""

from django.core.management.base import BaseCommand

from core.models import Idea
from core.tasks import recommend_idea


class Command(BaseCommand):
    help = "Kolejkuje rekomendacje dla ocenionych innowacji bez rekomendacji rozwoju."

    def handle(self, *args, **options):
        ideas = Idea.objects.filter(scored_at__isnull=False, recommendation__isnull=True)
        idea_ids = ideas.values_list("pk", flat=True)
        queued = 0
        for idea_id in idea_ids.iterator():
            recommend_idea.delay(idea_id)
            queued += 1
        self.stdout.write(self.style.SUCCESS(f"Zakolejkowano rekomendacje: {queued}."))
