"""Orkiestracja wyszukiwania innowacji w aktualnościach instytucji."""

import logging
import time
from dataclasses import dataclass
from datetime import date
from http.client import HTTPException

from core.models import Idea, Institution
from core.services import news_html
from core.services.news_llm import (
    ExtractedInnovation,
    NewsInnovationLLM,
    SelectedNewsArticle,
)

logger = logging.getLogger(__name__)

# Publiczne aliasy zachowane dla integracji i istniejących rozszerzeń.
PageParser = news_html.PageParser
article_links = news_html.article_links
fetch_html = news_html.fetch_html


@dataclass(frozen=True)
class NewsArticle:
    title: str
    url: str
    body: str
    canonical_name: str = ""
    published_on: date | None = None
    institution_role: str = "creator"
    taxonomy: dict[str, tuple[str, ...]] | None = None


class InstitutionNewsDiscoveryService:
    """Łączy źródła instytucji, HTML i LLM w listę opisanych innowacji."""

    _article_links = staticmethod(article_links)

    def __init__(
        self,
        client=None,
        fetcher=fetch_html,
        model: str | None = None,
        sleeper=time.sleep,
        reporter=None,
    ):
        self.fetcher = fetcher
        self.llm = NewsInnovationLLM(client=client, model=model, sleeper=sleeper)
        self.reporter = reporter or (lambda message: None)

    def discover(
        self, institution: Institution, source_urls: tuple[str, ...] | None = None
    ) -> tuple[NewsArticle, ...]:
        known_urls = set(
            Idea.objects.exclude(source_url__isnull=True).values_list("source_url", flat=True)
        )
        source_urls = source_urls if source_urls is not None else self.source_urls(institution)
        selected_links = {
            link.url: link
            for source_url in source_urls
            for link in self._selected_links(source_url)
            if link.url not in known_urls
        }.values()
        articles = (
            self._extract_innovation(institution.name, link) for link in selected_links
        )
        return tuple(article for article in articles if article is not None)

    @staticmethod
    def _source_urls(institution: Institution) -> tuple[str, ...]:
        source_urls = tuple(institution.news_sources.values_list("url", flat=True))
        return tuple(dict.fromkeys(url for url in (institution.news_url, *source_urls) if url))

    def source_urls(self, institution: Institution) -> tuple[str, ...]:
        """Zwraca stabilną kolejkę źródeł, którą job może checkpointować."""
        return self._source_urls(institution)

    def selected_articles(self, source_url: str) -> tuple[SelectedNewsArticle, ...]:
        """Wybiera artykuły jednego źródła, aby job zapisał ich kolejkę."""
        known_urls = set(
            Idea.objects.exclude(source_url__isnull=True).values_list("source_url", flat=True)
        )
        return tuple(
            link for link in self._selected_links(source_url) if link.url not in known_urls
        )

    def extract_article(
        self, institution: Institution, link: SelectedNewsArticle
    ) -> NewsArticle | None:
        """Wydobywa pojedynczą inicjatywę z artykułu wskazanego w kolejce joba."""
        return self._extract_innovation(institution.name, link)

    def _selected_links(self, source_url: str) -> tuple[SelectedNewsArticle, ...]:
        listing = self._parse(source_url)
        if listing is None:
            return ()
        links = article_links(source_url, listing.anchors)
        return self._select_links(links, " ".join(listing.text))

    def _parse(self, url: str) -> PageParser | None:
        parser = PageParser()
        try:
            parser.feed(self.fetcher(url))
        except (HTTPException, OSError) as error:
            logger.warning("Nie pobrano strony %s: %s", url, error)
            return None
        return parser

    def _extract_innovation(
        self, institution_name: str, link: SelectedNewsArticle
    ) -> NewsArticle | None:
        self.reporter(f"Analizowanie artykułu: {link.title}")
        page = self._parse(link.url)
        if page is None:
            return None
        innovation = self.llm.extract(institution_name, link.title, link.url, " ".join(page.text))
        return self._article_from_extraction(link, innovation)

    @staticmethod
    def _article_from_extraction(
        link: SelectedNewsArticle, innovation: ExtractedInnovation | None
    ) -> NewsArticle | None:
        if innovation is None:
            return None
        return NewsArticle(
            title=innovation.name,
            url=link.url,
            body=innovation.description,
            canonical_name=innovation.canonical_name,
            published_on=link.published_on or innovation.published_on,
            institution_role=innovation.institution_role,
            taxonomy=innovation.taxonomy,
        )

    def _select_links(
        self, links: tuple[tuple[str, str], ...], visible_text: str
    ) -> tuple[SelectedNewsArticle, ...]:
        return self.llm.select_links(links, visible_text)
