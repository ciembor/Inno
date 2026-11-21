"""Uzupełnianie dat publikacji istniejących artykułów źródłowych."""

import logging
from datetime import date
from http.client import HTTPException

from core.services.news_html import PageParser, fetch_html
from core.services.news_llm import NewsInnovationLLM

logger = logging.getLogger(__name__)


class PublicationDateService:
    """Pobiera artykuł i prosi LLM wyłącznie o jego datę publikacji."""

    def __init__(self, client=None, fetcher=fetch_html, model: str | None = None):
        self.fetcher = fetcher
        self.llm = NewsInnovationLLM(client=client, model=model)

    def extract(self, title: str, url: str) -> date | None:
        """Zwraca datę publikacji lub None, gdy artykuł jej nie podaje."""
        parser = PageParser()
        try:
            parser.feed(self.fetcher(url))
        except (HTTPException, OSError) as error:
            logger.warning("Nie pobrano artykułu %s: %s", url, error)
            return None
        return self.llm.publication_date(title, url, " ".join(parser.text))
