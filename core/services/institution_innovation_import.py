"""Import wybranych aktualności instytucji jako ocenianych innowacji."""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Idea, IdeaIndicatorScore, InnovationIndicator, Institution
from core.services.idea_similarity import save_taxonomy
from core.services.innovation_scoring import score_innovation
from core.services.institution_news import InstitutionNewsDiscoveryService, NewsArticle


@dataclass(frozen=True)
class InstitutionImportResult:
    created: int
    skipped: int


class InstitutionInnovationImportService:
    """Pobiera artykuły uczelni, zapisuje je i nadaje im ocenę innowacyjności."""

    def __init__(self, discovery=None, scorer=score_innovation):
        self.discovery = discovery or InstitutionNewsDiscoveryService()
        self.scorer = scorer

    def import_all(
        self, institution_type: str = "university", start_after_id: int | None = None
    ) -> InstitutionImportResult:
        created = skipped = 0
        institutions = Institution.objects.filter(institution_type=institution_type).order_by(
            "name", "pk"
        )
        if start_after_id:
            previous = Institution.objects.get(pk=start_after_id, institution_type=institution_type)
            institutions = institutions.filter(
                Q(name__gt=previous.name) | Q(name=previous.name, pk__gt=previous.pk)
            )
        for institution in institutions:
            for article in self.discovery.discover(institution):
                if Idea.objects.filter(
                    Q(source_url=article.url)
                    | Q(institution=institution, name__iexact=article.title.strip()[:160])
                    | Q(name__iexact=article.canonical_name.strip()[:160])
                ).exists():
                    skipped += 1
                else:
                    self._create_idea(institution, article)
                    created += 1
        return InstitutionImportResult(created=created, skipped=skipped)

    def import_institution(
        self, institution: Institution, reporter=None, source_urls: tuple[str, ...] | None = None
    ) -> InstitutionImportResult:
        """Importuje wskazane źródła instytucji, aby job mógł zapisać checkpoint."""
        created = skipped = 0
        articles = (
            self.discovery.discover(institution, source_urls=source_urls)
            if source_urls is not None
            else self.discovery.discover(institution)
        )
        for article in articles:
            if Idea.objects.filter(
                Q(source_url=article.url)
                | Q(institution=institution, name__iexact=article.title.strip()[:160])
                | Q(name__iexact=article.canonical_name.strip()[:160])
            ).exists():
                skipped += 1
            else:
                if reporter:
                    reporter(f"Ocenianie innowacji: {article.title}")
                self._create_idea(institution, article)
                created += 1
                if reporter:
                    reporter(f"Dodano innowację: {article.title}")
        return InstitutionImportResult(created=created, skipped=skipped)

    def import_article(
        self, institution: Institution, article: NewsArticle | None, reporter=None
    ) -> InstitutionImportResult:
        """Zapisuje i ocenia jeden artykuł, zachowując checkpoint joba."""
        if article is None:
            return InstitutionImportResult(created=0, skipped=0)
        if self._is_duplicate(institution, article):
            return InstitutionImportResult(created=0, skipped=1)
        if reporter:
            reporter(f"Ocenianie innowacji: {article.title}")
        self._create_idea(institution, article)
        if reporter:
            reporter(f"Dodano innowację: {article.title}")
        return InstitutionImportResult(created=1, skipped=0)

    @staticmethod
    def _is_duplicate(institution: Institution, article: NewsArticle) -> bool:
        return Idea.objects.filter(
            Q(source_url=article.url)
            | Q(institution=institution, name__iexact=article.title.strip()[:160])
            | Q(name__iexact=article.canonical_name.strip()[:160])
        ).exists()

    def _create_idea(self, institution: Institution, article: NewsArticle) -> Idea:
        score = self.scorer(article.title, article.body)
        idea = Idea.objects.create(
            name=article.title.strip()[:160],
            submitter_name=institution.name,
            email="import@innoradar.local",
            locality_id=institution.locality_id,
            institution=institution,
            institution_role=article.institution_role,
            source_url=article.url,
            content=article.body,
            published_at=article.published_on,
            innovation_score=score.total,
            scored_at=timezone.now(),
            innovation_details={item.criterion.name: item.value for item in score.criteria},
            innovation_rationales={item.criterion.name: item.rationale for item in score.criteria},
        )
        indicators = InnovationIndicator.objects.in_bulk(field_name="key")
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
        if article.taxonomy:
            save_taxonomy(idea, article.taxonomy)
        from core.tasks import recommend_idea

        transaction.on_commit(lambda: recommend_idea.delay(idea.pk))
        return idea
