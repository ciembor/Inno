# Mechanical split of the former test_core.py by responsibility.

import json
from datetime import date
from http.client import IncompleteRead
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError, OpenAIError

from core.models import Institution
from core.services import institution_news
from core.services.institution_news import (
    InstitutionNewsDiscoveryService,
    NewsArticle,
    PageParser,
    fetch_html,
)
from core.services.news_llm import NewsInnovationLLM
from core.services.publication_dates import PublicationDateService
from core.tests.support import FakeClient


@pytest.mark.django_db
def test_institution_news_discovery_selects_only_articles_chosen_by_llm():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    article_body = "Opis wdrożenia nowego rozwiązania. " * 8
    pages = {
        institution.news_url: '<a href="/innowacja">Innowacyjny projekt</a><a href="https://other.example/x">Pomiń</a>',
        "https://uczelnia.example/innowacja": (
            "<header>Menu uczelni</header><main>"
            + article_body
            + "</main><footer>Stopka uczelni</footer>"
        ),
    }
    client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/innowacja", "published_on": "2026-11-16"}
                    ]
                }
            ),
            json.dumps(
                {
                    "name": "Nowe rozwiązanie",
                    "canonical_name": "Nowe rozwiązanie",
                    "description": article_body.strip(),
                    "published_on": "2026-11-17",
                    "institution_role": "creator",
                }
            ),
        ]
    )

    articles = InstitutionNewsDiscoveryService(client=client, fetcher=pages.__getitem__).discover(
        institution
    )

    assert articles == (
        NewsArticle(
            title="Nowe rozwiązanie",
            url="https://uczelnia.example/innowacja",
            body=article_body.strip(),
            canonical_name="Nowe rozwiązanie",
            published_on=date(2026, 11, 16),
        ),
    )
    call = client.responses.calls[0]
    assert "Jesteś radarem innowacji" in call["instructions"]
    assert (
        "które prawdopodobnie zawierają wewnątrz jakąś ogólniepojętą innowację"
        in call["instructions"]
    )
    assert "artykuły, które tylko wspominają innowacje" in call["instructions"]
    assert "Widoczna treść strony aktualności" in call["input"]
    extraction_call = client.responses.calls[1]
    assert "Jesteś radarem innowacji" in extraction_call["instructions"]
    assert "nazwę samej innowacji" in extraction_call["instructions"]
    assert "Instytucja publikująca artykuł: Uczelnia" in extraction_call["input"]
    assert "Menu uczelni" in extraction_call["input"]


@pytest.mark.django_db
def test_institution_news_discovery_skips_an_unavailable_news_source():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    client = FakeClient([])

    def timed_out_fetcher(_url):
        raise TimeoutError()

    assert (
        InstitutionNewsDiscoveryService(client=client, fetcher=timed_out_fetcher).discover(
            institution
        )
        == ()
    )
    assert client.responses.calls == []


@pytest.mark.django_db
def test_institution_news_discovery_skips_an_incomplete_http_response():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )

    def incomplete_fetcher(_url):
        raise IncompleteRead(b"partial response", 100)

    assert (
        InstitutionNewsDiscoveryService(
            client=FakeClient([]), fetcher=incomplete_fetcher
        ).discover(institution)
        == ()
    )


@pytest.mark.django_db
def test_institution_news_discovery_skips_an_unavailable_article():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/innowacja", "published_on": None}
                    ]
                }
            )
        ]
    )

    def fetcher(url):
        if url == institution.news_url:
            return '<a href="/innowacja">Innowacyjny projekt</a>'
        raise TimeoutError()

    assert (
        InstitutionNewsDiscoveryService(client=client, fetcher=fetcher).discover(institution) == ()
    )
    assert len(client.responses.calls) == 1


@pytest.mark.django_db
def test_institution_news_discovery_retries_llm_connection_errors_without_stopping_import():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    pages = {
        institution.news_url: '<a href="/innowacja">Innowacyjny projekt</a>',
        "https://uczelnia.example/innowacja": "Opis rozwiązania.",
    }
    waits = []
    client = FakeClient(
        [
            APIConnectionError(request=MagicMock()),
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/innowacja", "published_on": None}
                    ]
                }
            ),
            json.dumps(
                {
                    "name": "Rozwiązanie",
                    "canonical_name": "Rozwiązanie",
                    "description": "Opis rozwiązania.",
                    "published_on": None,
                    "institution_role": "creator",
                }
            ),
        ]
    )

    articles = InstitutionNewsDiscoveryService(
        client=client, fetcher=pages.__getitem__, sleeper=waits.append
    ).discover(institution)

    assert articles[0].title == "Rozwiązanie"
    assert waits == [1]

    unavailable_client = FakeClient([APIConnectionError(request=MagicMock())] * 3)
    assert (
        InstitutionNewsDiscoveryService(
            client=unavailable_client, fetcher=pages.__getitem__, sleeper=waits.append
        ).discover(institution)
        == ()
    )
    assert waits[-2:] == [1, 2]

    extraction_client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/innowacja", "published_on": None}
                    ]
                }
            ),
            APIConnectionError(request=MagicMock()),
            APIConnectionError(request=MagicMock()),
            APIConnectionError(request=MagicMock()),
        ]
    )
    assert (
        InstitutionNewsDiscoveryService(
            client=extraction_client, fetcher=pages.__getitem__, sleeper=lambda _delay: None
        ).discover(institution)
        == ()
    )


@pytest.mark.django_db
def test_publication_date_llm_and_service_use_only_article_content():
    client = FakeClient(
        [
            json.dumps({"published_on": "2026-11-17"}),
            json.dumps({"published_on": None}),
        ]
    )
    service = PublicationDateService(
        client=client,
        fetcher=lambda _url: "<main>Opublikowano: 17 listopada 2026</main>",
    )

    assert service.extract("Projekt", "https://example.org/a") == date(2026, 11, 17)
    assert service.extract("Projekt", "https://example.org/b") is None
    assert "datę publikacji" in client.responses.calls[0]["instructions"]
    assert "Widoczna treść strony" in client.responses.calls[0]["input"]

    unavailable = PublicationDateService(
        client=FakeClient([]), fetcher=lambda _url: (_ for _ in ()).throw(TimeoutError())
    )
    assert unavailable.extract("Projekt", "https://example.org/c") is None

    llm = NewsInnovationLLM(client=FakeClient([]))
    llm._request = lambda **_kwargs: None
    assert llm.publication_date("Projekt", "https://example.org/d", "Treść") is None
    llm._request = lambda **_kwargs: (_ for _ in ()).throw(OpenAIError("Błąd API"))
    assert llm.publication_date("Projekt", "https://example.org/e", "Treść") is None
    llm._request = lambda **_kwargs: type("Response", (), {"output_text": "{}"})()
    with pytest.raises(RuntimeError, match="daty publikacji"):
        llm.publication_date("Projekt", "https://example.org/f", "Treść")


def test_news_page_parser_ignores_empty_links_and_non_content_tags():
    parser = PageParser()
    parser.feed(
        '<a href=""> </a><a href="/empty"></a><script>pomijane</script>'
        '<style>też</style><a href="/x"> Link </a>'
    )

    assert parser.anchors == [("Link", "/x")]
    assert parser.text == ["Link"]


@pytest.mark.django_db
def test_institution_news_skips_page_rejected_by_llm():
    links = (("Artykuł", "https://uczelnia.example/artykul"),)

    assert (
        InstitutionNewsDiscoveryService(client=FakeClient([OpenAIError("input too long")]))
        ._select_links(links, "Treść")
        == ()
    )


@pytest.mark.django_db
def test_institution_news_skips_article_rejected_by_llm():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    pages = {
        institution.news_url: '<a href="/artykul">Artykuł</a>',
        "https://uczelnia.example/artykul": "Treść artykułu.",
    }
    client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/artykul", "published_on": None}
                    ]
                }
            ),
            OpenAIError("input too long"),
        ]
    )

    assert InstitutionNewsDiscoveryService(client=client, fetcher=pages.__getitem__).discover(
        institution
    ) == ()


def test_institution_news_links_keep_visible_page_order_without_duplicates():
    links = InstitutionNewsDiscoveryService._article_links(
        "https://uczelnia.example/aktualnosci",
        [
            ("Pierwszy artykuł", "/pierwszy"),
            ("Duplikat", "/pierwszy"),
            ("Zewnętrzny", "https://inna.example/artykul"),
            ("Drugi artykuł", "/drugi"),
            ("Pusty", ""),
        ],
    )

    assert links == (
        ("Pierwszy artykuł", "https://uczelnia.example/pierwszy"),
        ("Drugi artykuł", "https://uczelnia.example/drugi"),
    )


def test_fetch_html_reads_response_body(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers.get_content_type.return_value = "text/html"
    response.read.return_value = b"<p>Aktualnosc</p>"
    requests = []
    monkeypatch.setattr(
        institution_news.news_html.urllib.request,
        "urlopen",
        lambda request, **kwargs: requests.append(request) or response,
    )

    assert fetch_html("https://uczelnia.example/aktualności") == "<p>Aktualnosc</p>"
    assert requests[0].full_url.endswith("aktualno%C5%9Bci")


@pytest.mark.django_db
def test_institution_news_discovery_raises_when_llm_returns_invalid_json():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    pages = {
        institution.news_url: '<a href="/innowacja">Innowacyjny projekt</a>',
        "https://uczelnia.example/innowacja": "Opis " * 50,
    }

    with pytest.raises(RuntimeError, match="Nie udało"):
        InstitutionNewsDiscoveryService(
            client=FakeClient(["nie jest JSON"]), fetcher=pages.__getitem__
        ).discover(institution)


@pytest.mark.django_db
def test_institution_news_discovery_raises_when_extraction_is_invalid():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    pages = {
        institution.news_url: '<a href="/innowacja">Innowacyjny projekt</a>',
        "https://uczelnia.example/innowacja": "Opis inicjatywy",
    }
    client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/innowacja", "published_on": None}
                    ]
                }
            ),
            "nie jest JSON",
        ]
    )

    with pytest.raises(RuntimeError, match="wyodrębnić"):
        InstitutionNewsDiscoveryService(client=client, fetcher=pages.__getitem__).discover(
            institution
        )


@pytest.mark.django_db
def test_institution_news_discovery_skips_article_without_innovation():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    pages = {
        institution.news_url: '<a href="/aktualnosc">Aktualność uczelni</a>',
        "https://uczelnia.example/aktualnosc": "Komunikat organizacyjny.",
    }
    client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://uczelnia.example/aktualnosc", "published_on": None}
                    ]
                }
            ),
            json.dumps(
                {
                    "name": "",
                    "canonical_name": "",
                    "description": "",
                    "published_on": None,
                    "institution_role": "unknown",
                }
            ),
        ]
    )

    assert (
        InstitutionNewsDiscoveryService(client=client, fetcher=pages.__getitem__).discover(
            institution
        )
        == ()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("institution_role", ["external_reference", "routine_implementation"])
def test_institution_news_discovery_rejects_non_local_initiatives(institution_role):
    institution = Institution.objects.create(
        name="Szkoła",
        address="Tarnobrzeg",
        news_url="https://example.org/aktualnosci",
        institution_type="school",
    )
    pages = {
        institution.news_url: '<a href="/aktualnosc">Aktualność szkoły</a>',
        "https://example.org/aktualnosc": "Szkoła opisuje zewnętrzny program.",
    }
    client = FakeClient(
        [
            json.dumps(
                {
                    "selected_articles": [
                        {"url": "https://example.org/aktualnosc", "published_on": None}
                    ]
                }
            ),
            json.dumps(
                {
                    "name": "Cudzy program",
                    "canonical_name": "Cudzy program",
                    "description": "Opis zewnętrznego programu.",
                    "published_on": None,
                    "institution_role": institution_role,
                }
            ),
        ]
    )

    assert InstitutionNewsDiscoveryService(client=client, fetcher=pages.__getitem__).discover(
        institution
    ) == ()
    assert "Nie traktuj udziału w zajęciach" in client.responses.calls[1]["instructions"]
