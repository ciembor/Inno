"""Pobieranie oraz deterministyczne przetwarzanie stron aktualności."""

import urllib.request
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse


class PageParser(HTMLParser):
    """Wyciąga widoczny tekst oraz podpisane odnośniki z dokumentu HTML."""

    def __init__(self):
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._anchor_url = ""
        self._anchor_text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "a" and not self._ignored_depth:
            self._anchor_url = dict(attrs).get("href", "")
            self._anchor_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor_url:
            label = " ".join(self._anchor_text).strip()
            if label:
                self.anchors.append((label, self._anchor_url))
            self._anchor_url = ""
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        text = " ".join(data.split())
        if text and not self._ignored_depth:
            self.text.append(text)
            if self._anchor_url:
                self._anchor_text.append(text)


def fetch_html(url: str) -> str:
    """Pobiera dokument jako UTF-8, przedstawiając się jako zwykła przeglądarka."""
    request_url = quote(url, safe=":/?&=#%")
    request = urllib.request.Request(request_url, headers={"User-Agent": "InnoradarBot/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise OSError(f"Pomijam dokument niebędący HTML: {content_type} ({url})")
        return response.read().decode("utf-8", errors="replace")


def article_links(listing_url: str, anchors: list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """Zwraca unikalne odnośniki z tego samego hosta co lista aktualności."""
    host = urlparse(listing_url).netloc
    links = []
    seen_urls = set()
    for title, href in anchors:
        url = urljoin(listing_url, href)
        if href and urlparse(url).netloc == host and url not in seen_urls:
            links.append((title, url))
            seen_urls.add(url)
    return tuple(links)
