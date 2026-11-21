"""Utworzenie, status i wznowienie badania kolejności ocen końcowych."""

import json

from django.core.management.base import BaseCommand, CommandError

from core.models import OverallOrderStudy
from core.services.overall_order_study import (
    REPEAT_COUNT,
    SAMPLE_PER_STRATUM,
    SEED,
    create_study,
    study_summary,
)
from core.tasks import run_overall_order_study


class Command(BaseCommand):
    help = "Badanie końcowej kolejności: start, --status ID, --pause ID, --resume ID."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=SEED)
        parser.add_argument("--sample-per-stratum", type=int, default=SAMPLE_PER_STRATUM)
        parser.add_argument("--repeat-count", type=int, default=REPEAT_COUNT)
        parser.add_argument("--status", type=int)
        parser.add_argument("--pause", type=int)
        parser.add_argument("--resume", type=int)

    def handle(self, *args, **options):
        actions = [name for name in ("status", "pause", "resume") if options[name] is not None]
        if len(actions) > 1:
            raise CommandError("Wybierz tylko jedną akcję.")
        if actions:
            return self._existing(actions[0], options[actions[0]])
        if OverallOrderStudy.objects.filter(status__in=("pending", "running")).exists():
            raise CommandError("Badanie już działa.")
        try:
            study = create_study(
                options["seed"], options["sample_per_stratum"], options["repeat_count"]
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        run_overall_order_study.delay(study.pk)
        self.stdout.write(
            f"Badanie {study.pk}: {study.pairs.count()} porównań "
            f"({study.sample_per_stratum * 3} par + {study.repeat_count} powtórek)."
        )

    def _existing(self, action, study_id):
        study = OverallOrderStudy.objects.filter(pk=study_id).first()
        if study is None:
            raise CommandError("Nie znaleziono badania.")
        if action == "status":
            self.stdout.write(json.dumps({
                "id": study.pk, "status": study.status,
                "completed": study.pairs.exclude(outcome="").count(),
                "total": study.pairs.count(), "error": study.error,
                "summary": study_summary(study),
            }, ensure_ascii=False))
            return
        if action == "pause":
            if study.status not in ("pending", "running"):
                raise CommandError("Nie można wstrzymać nieaktywnego badania.")
            study.status = "paused"
            study.save(update_fields=["status"])
            self.stdout.write(f"Badanie {study.pk} wstrzymane.")
            return
        if study.status not in ("paused", "failed"):
            raise CommandError("Można wznowić tylko wstrzymane lub błędne badanie.")
        study.status, study.error = "pending", ""
        study.save(update_fields=["status", "error"])
        run_overall_order_study.delay(study.pk)
        self.stdout.write(f"Badanie {study.pk} wznowione.")
