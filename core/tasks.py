"""Zadania wykonywane poza cyklem żądania HTTP."""

from datetime import timedelta

from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from openai import APITimeoutError

from core.models import (
    DevelopmentRecommendation,
    Idea,
    IdeaIndicatorScore,
    InnovationIndicator,
    InstitutionImportEvent,
    InstitutionImportRun,
    NCBRImportEvent,
    NCBRImportRun,
    OverallOrderStudy,
    RankingRun,
    ScoringOrderStudy,
)
from core.services.crawl_schedule import start_due_crawl
from core.services.development_recommendations import (
    DevelopmentRecommendationError,
    recommend_development,
)
from core.services.idea_similarity import classify_idea as classify_idea_tags
from core.services.innovation_scoring import InnovationScoringRequestError, score_innovation
from core.services.institution_import_run import advance_import_run
from core.services.institution_innovation_import import InstitutionInnovationImportService
from core.services.ncbr import NCBRDiscoveryService, NCBRImportService
from core.services.overall_order_study import compare_pair as compare_overall_pair
from core.services.pairwise_ranking import advance_run
from core.services.partner_needs import add_default_partner_needs
from core.services.scoring_order_study import compare_study_pair, save_result


def retry_study_timeout(task, study_model, study_id, error):
    """Ponawia timeout bez limitu, zachowując pauzę i zapisane wyniki."""
    delay = min(300, 10 * 2 ** min(task.request.retries, 5))
    if not study_model.objects.filter(pk=study_id, status="running").update(
        status="pending", error=f"Timeout API; ponowienie za {delay} s: {error}"
    ):
        return
    raise task.retry(exc=error, countdown=delay)


def retry_import_timeout(task, run, error):
    """Wznawia ten sam checkpoint importu po przekroczeniu czasu zadania."""
    delay = min(300, 10 * 2 ** min(task.request.retries, 5))
    message = f"Limit czasu; automatyczne wznowienie za {delay} s."
    retry_after = timezone.now() + timedelta(seconds=delay)
    if not InstitutionImportRun.objects.filter(pk=run.pk, status="running").update(
        status="pending",
        current_action=message,
        error="",
        heartbeat_at=timezone.now(),
        retry_after=retry_after,
    ):
        return
    InstitutionImportEvent.objects.create(run=run, message=message)
    raise task.retry(exc=error, countdown=delay)


@shared_task
def recover_institution_imports() -> None:
    """Wznawia importy utracone po restarcie workera lub twardym limicie czasu."""
    now = timezone.now()
    stale_before = now - timedelta(minutes=3)
    stale_ids = list(
        InstitutionImportRun.objects.filter(status="running")
        .filter(Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=stale_before))
        .values_list("pk", flat=True)
    )
    if stale_ids:
        InstitutionImportRun.objects.filter(pk__in=stale_ids, status="running").update(
            status="pending",
            current_action="Wznawianie po utracie workera",
            heartbeat_at=now,
            retry_after=now,
        )
        InstitutionImportEvent.objects.bulk_create(
            [
                InstitutionImportEvent(run_id=run_id, message="Wznawianie po utracie workera.")
                for run_id in stale_ids
            ]
        )
    pending_ids = (
        InstitutionImportRun.objects.filter(status="pending")
        .filter(Q(retry_after__isnull=True) | Q(retry_after__lte=now))
        .values_list("pk", flat=True)
    )
    for run_id in pending_ids:
        import_institution_news.delay(run_id)


@shared_task
def start_scheduled_institution_import() -> None:
    """Uruchamia należny pełny crawling, bez nakładania go na aktywny przebieg."""
    run = start_due_crawl()
    if run is not None:
        import_institution_news.delay(run.pk)


@shared_task(bind=True, max_retries=None, soft_time_limit=100, time_limit=120)
def score_idea(
    self, idea_id: int, *, schedule_followups: bool = True
) -> dict[str, float | None | dict[str, int | None] | dict[str, str]]:
    """Ocenia zapisany pomysł i utrwala wynik, aby mógł trafić na listę innowacji."""
    try:
        return _score_idea(idea_id, schedule_followups=schedule_followups)
    except (APITimeoutError, InnovationScoringRequestError, SoftTimeLimitExceeded) as error:
        delay = min(300, 10 * 2 ** min(self.request.retries, 5))
        raise self.retry(exc=error, countdown=delay) from error


def _score_idea(
    idea_id: int, *, schedule_followups: bool
) -> dict[str, float | None | dict[str, int | None] | dict[str, str]]:
    """Utrwala pełną ocenę oraz szczegóły widoczne tak jak dla importowanych innowacji."""
    idea = Idea.objects.get(pk=idea_id)
    score = score_innovation(idea.name, idea.content)
    details = {item.criterion.name: item.value for item in score.criteria}
    rationales = {item.criterion.name: item.rationale for item in score.criteria}
    idea.innovation_score = score.total
    idea.innovation_details = details
    idea.innovation_rationales = rationales
    idea.scored_at = timezone.now()
    idea.relative_novelty = None
    idea.relative_value = None
    idea.relative_replicability = None
    idea.relative_impact = None
    idea.relative_score = None
    idea.relative_scored_at = None
    idea.save(
        update_fields=[
            "innovation_score",
            "innovation_details",
            "innovation_rationales",
            "scored_at",
            "relative_novelty",
            "relative_value",
            "relative_replicability",
            "relative_impact",
            "relative_score",
            "relative_scored_at",
        ]
    )
    indicators = InnovationIndicator.objects.in_bulk(field_name="key")
    IdeaIndicatorScore.objects.filter(idea=idea).delete()
    IdeaIndicatorScore.objects.bulk_create(
        [
            IdeaIndicatorScore(
                idea=idea,
                indicator=indicators[item.criterion.key],
                score=item.value,
                rationale=item.rationale,
            )
            for item in score.criteria
        ]
    )
    if schedule_followups:
        transaction.on_commit(lambda: recommend_idea.delay(idea.pk))
        transaction.on_commit(lambda: classify_idea.delay(idea.pk))
    return {"total": score.total, "criteria": details, "rationales": rationales}


@shared_task(bind=True, max_retries=None, soft_time_limit=100, time_limit=120)
def recommend_idea(self, idea_id: int) -> None:
    """Generuje rekomendację oraz potrzeby partnerstwa po ocenie inicjatywy."""
    idea = Idea.objects.get(pk=idea_id)
    try:
        recommendation = recommend_development(idea)
        DevelopmentRecommendation.objects.update_or_create(
            idea=idea,
            defaults={
                "stage": recommendation.stage,
                "development_path": recommendation.development_path,
                "next_step": recommendation.next_step,
                "rationale": recommendation.rationale,
                "risk": recommendation.risk,
                "status": DevelopmentRecommendation.Status.GENERATED,
                "error": "",
                "approved_at": None,
            },
        )
        add_default_partner_needs(idea, recommendation.development_path)
    except (APITimeoutError, DevelopmentRecommendationError, SoftTimeLimitExceeded) as error:
        delay = min(300, 10 * 2 ** min(self.request.retries, 5))
        raise self.retry(exc=error, countdown=delay) from error


@shared_task
def classify_idea(idea_id: int) -> None:
    """Nadaje ręcznie zgłoszonej inicjatywie tagi podobieństwa."""
    classify_idea_tags(Idea.objects.get(pk=idea_id))


@shared_task(soft_time_limit=180, time_limit=210)
def import_ncbr_projects(run_id: int) -> None:
    """Importuje projekty NCBR niezależnie od crawlingu instytucji."""
    now = timezone.now()
    if not NCBRImportRun.objects.filter(pk=run_id, status="pending").update(
        status="running", heartbeat_at=now
    ):
        return
    run = NCBRImportRun.objects.get(pk=run_id)

    def report(message: str) -> None:
        NCBRImportEvent.objects.create(run=run, message=message)
        NCBRImportRun.objects.filter(pk=run.pk, status="running").update(
            current_action=message,
            heartbeat_at=timezone.now(),
        )

    try:
        report("Pobieranie ogólnopolskiego katalogu sukcesów beneficjentów NCBR")
        projects = NCBRDiscoveryService().discover()
        NCBRImportRun.objects.filter(pk=run.pk, status="running").update(
            projects_total=len(projects),
            current_action="Zapisywanie projektów i kolejowanie ocen",
            heartbeat_at=timezone.now(),
        )
        result = NCBRImportService().import_projects(projects=projects)
        NCBRImportRun.objects.filter(pk=run.pk, status="running").update(
            status="completed",
            finished_at=timezone.now(),
            projects_processed=len(projects),
            ideas_created=result.created,
            ideas_skipped=result.skipped,
            current_action="Import projektów NCBR zakończony",
            heartbeat_at=timezone.now(),
        )
        NCBRImportEvent.objects.create(
            run=run,
            message=f"Zakończono: dodano {result.created}, pominięto {result.skipped}.",
        )
    except Exception as error:
        if NCBRImportRun.objects.filter(pk=run.pk, status="running").update(
            status="failed",
            finished_at=timezone.now(),
            current_action="Import NCBR przerwany",
            error=str(error),
            heartbeat_at=timezone.now(),
        ):
            NCBRImportEvent.objects.create(run=run, message=f"Błąd: {error}")
        raise


@shared_task(bind=True, max_retries=None, soft_time_limit=100, time_limit=120)
def import_institution_news(self, run_id: int) -> None:
    """Przetwarza jeden artykuł aktualności i zachowuje trwały checkpoint."""
    now = timezone.now()
    if (
        not InstitutionImportRun.objects.filter(pk=run_id, status="pending")
        .filter(Q(retry_after__isnull=True) | Q(retry_after__lte=now))
        .update(status="running", heartbeat_at=now, retry_after=None)
    ):
        return
    run = InstitutionImportRun.objects.get(pk=run_id)

    def report(message):
        InstitutionImportEvent.objects.create(run=run, message=message)
        InstitutionImportRun.objects.filter(pk=run.pk, status="running").update(
            heartbeat_at=timezone.now()
        )

    try:
        advance_import_run(
            run,
            report=report,
            schedule=import_institution_news.delay,
            service_factory=InstitutionInnovationImportService,
        )
    except (APITimeoutError, SoftTimeLimitExceeded) as error:
        retry_import_timeout(self, run, error)
    except Exception as error:
        failed = InstitutionImportRun.objects.filter(pk=run.pk, status="running").update(
            status="failed",
            error=str(error),
            current_action="Import przerwany",
            heartbeat_at=timezone.now(),
            retry_after=None,
        )
        if failed:
            InstitutionImportEvent.objects.create(run=run, message=f"Błąd: {error}")
        raise


@shared_task(soft_time_limit=240, time_limit=300)
def rank_innovations(run_id):
    """Krótkie checkpointowane kroki zamiast jednego wielogodzinnego zadania."""
    if not RankingRun.objects.filter(pk=run_id, status="pending").update(status="running"):
        return
    run = RankingRun.objects.get(pk=run_id)
    try:
        if not advance_run(run):
            rank_innovations.delay(run_id)
    except Exception as error:
        RankingRun.objects.filter(pk=run_id).update(status="failed", error=str(error))
        raise


@shared_task(bind=True, max_retries=None, soft_time_limit=130, time_limit=150)
def run_scoring_order_study(self, study_id):
    """Przetwarza najwyżej jedną zaplanowaną parę i respektuje pauzę."""
    if not ScoringOrderStudy.objects.filter(pk=study_id, status="pending").update(status="running"):
        return
    study = ScoringOrderStudy.objects.get(pk=study_id)
    pair = study.pairs.filter(outcome="").first()
    if pair is None:
        ScoringOrderStudy.objects.filter(pk=study_id, status="running").update(status="completed")
        return
    try:
        save_result(pair, compare_study_pair(study, pair))
        if ScoringOrderStudy.objects.filter(pk=study_id, status="running").update(
            status="pending", error=""
        ):
            run_scoring_order_study.delay(study_id)
    except (APITimeoutError, SoftTimeLimitExceeded) as error:
        retry_study_timeout(self, ScoringOrderStudy, study_id, error)
    except Exception as error:
        ScoringOrderStudy.objects.filter(pk=study_id, status="running").update(
            status="failed", error=str(error)
        )
        raise


@shared_task(bind=True, max_retries=None, soft_time_limit=130, time_limit=150)
def run_overall_order_study(self, study_id):
    """Zapisuje jedną odpowiedź i planuje następny krok badania końcowej kolejności."""
    if not OverallOrderStudy.objects.filter(pk=study_id, status="pending").update(status="running"):
        return
    study = OverallOrderStudy.objects.get(pk=study_id)
    pair = study.pairs.filter(outcome="").first()
    if pair is None:
        OverallOrderStudy.objects.filter(pk=study_id, status="running").update(status="completed")
        return
    try:
        save_result(pair, compare_overall_pair(study, pair))
        if OverallOrderStudy.objects.filter(pk=study_id, status="running").update(
            status="pending", error=""
        ):
            run_overall_order_study.delay(study_id)
    except (APITimeoutError, SoftTimeLimitExceeded) as error:
        retry_study_timeout(self, OverallOrderStudy, study_id, error)
    except Exception as error:
        OverallOrderStudy.objects.filter(pk=study_id, status="running").update(
            status="failed", error=str(error)
        )
        raise
