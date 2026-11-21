"""Import projektów z publicznej wyszukiwarki sukcesów NCBR."""

from dataclasses import dataclass
from html.parser import HTMLParser

from django.db import transaction

from core.models import Idea
from core.services.news_html import fetch_html

NCBR_URL = "https://www.gov.pl/web/ncbr/wyszukiwarka-sukcesow-beneficjentow"
NCBR_LABEL = "NCBR — Wyszukiwarka sukcesów beneficjentów"


@dataclass(frozen=True)
class NCBRProject:
    """Jeden projekt opisany w publicznym katalogu NCBR."""

    title: str
    content: str
    url: str


@dataclass(frozen=True)
class NCBRImportResult:
    created: int
    skipped: int


class _ProjectsParser(HTMLParser):
    """Czyta samowystarczalne bloki ``details`` z katalogu NCBR."""

    def __init__(self):
        super().__init__()
        self.projects: list[tuple[list[str], list[tuple[str, str]]]] = []
        self._details_depth = 0
        self._text: list[str] = []
        self._anchors: list[tuple[str, str]] = []
        self._anchor_url = ""
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            if not self._details_depth:
                self._text = []
                self._anchors = []
            self._details_depth += 1
        elif tag == "a" and self._details_depth:
            self._anchor_url = dict(attrs).get("href", "")
            self._anchor_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor_url:
            self._anchors.append((" ".join(self._anchor_text), self._anchor_url))
            self._anchor_url = ""
        elif tag == "details" and self._details_depth:
            self._details_depth -= 1
            if not self._details_depth:
                self.projects.append((self._text, self._anchors))

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and self._details_depth:
            self._text.append(text)
            if self._anchor_url:
                self._anchor_text.append(text)


class NCBRDiscoveryService:
    """Pobiera wszystkie publicznie opisane projekty z katalogu NCBR."""

    def __init__(self, fetcher=fetch_html):
        self.fetcher = fetcher

    def discover(self) -> tuple[NCBRProject, ...]:
        parser = _ProjectsParser()
        parser.feed(self.fetcher(NCBR_URL))
        return tuple(
            project
            for text, anchors in parser.projects
            if (project := self._project(text, anchors)) is not None
        )

    @staticmethod
    def _project(text: list[str], anchors: list[tuple[str, str]]) -> NCBRProject | None:
        url = next(
            (href for label, href in anchors if "dowiedz się więcej" in label.casefold()), ""
        )
        if not text or not url:
            return None
        title = text[0].strip()[:160]
        content = "\n\n".join(text).strip()
        return NCBRProject(title=title, content=content, url=url)


class NCBRImportService:
    """Zapisuje projekty NCBR i zleca ich ocenę istniejącemu pipeline'owi."""

    def __init__(self, discovery=None, queue_score=None):
        self.discovery = discovery or NCBRDiscoveryService()
        self.queue_score = queue_score or _queue_score

    def import_projects(self, *, dry_run=False, projects=None) -> NCBRImportResult:
        created = skipped = 0
        for project in projects if projects is not None else self.discovery.discover():
            if Idea.objects.filter(source_url=project.url).exists():
                skipped += 1
            elif dry_run:
                created += 1
            else:
                idea = self._save(project)
                transaction.on_commit(lambda idea_id=idea.pk: self.queue_score(idea_id))
                created += 1
        return NCBRImportResult(created=created, skipped=skipped)

    @staticmethod
    def _save(project: NCBRProject) -> Idea:
        return Idea.objects.create(
            name=project.title,
            submitter_name="Narodowe Centrum Badań i Rozwoju",
            email="kontakt@ncbr.gov.pl",
            content=project.content,
            source_url=project.url,
            source_label=NCBR_LABEL,
        )


def _queue_score(idea_id: int) -> None:
    """Opóźniony import unika cyklicznego importu modułów Celery."""
    from core.tasks import score_idea

    score_idea.delay(idea_id)
