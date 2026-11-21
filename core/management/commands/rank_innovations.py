"""Uruchamianie i wznawianie względnych ocen parami."""

from django.core.management.base import BaseCommand, CommandError

from core.models import RankingRun
from core.services.pairwise_ranking import create_run
from core.tasks import rank_innovations


class Command(BaseCommand):
    help = "Utwórz ranking parami albo wznów checkpoint (--resume ID)."

    def add_arguments(self, parser):
        parser.add_argument("--resume", type=int)

    def handle(self, *args, **options):
        if options["resume"]:
            run = RankingRun.objects.filter(pk=options["resume"]).first()
            if run is None or run.status not in ("failed", "pending"):
                raise CommandError("Można wznowić wyłącznie przebieg failed lub pending.")
            run.status, run.error = "pending", ""
            run.save(update_fields=["status", "error"])
        else:
            if RankingRun.objects.filter(status__in=("pending", "running")).exists():
                raise CommandError("Ranking już trwa. Nie uruchomiono drugiego przebiegu.")
            run = create_run()
        rank_innovations.delay(run.pk)
        self.stdout.write(f"Ranking {run.pk}: {len(run.snapshot)} inicjatyw.")
