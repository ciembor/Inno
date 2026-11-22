"""Normalizacja opisów do czytelnego tekstu bez znaczników HTML."""

from html import unescape
from re import IGNORECASE, compile

from django.utils.html import strip_tags

BLOCK_TAGS = compile(r"</?(?:p|div|h[1-6]|li|ul|ol|blockquote)[^>]*>", IGNORECASE)
BREAK_TAGS = compile(r"<br\s*/?>", IGNORECASE)


def plain_text(value: str) -> str:
    """Usuwa HTML, zachowując logiczne podziały treści."""
    with_line_breaks = BLOCK_TAGS.sub("\n", BREAK_TAGS.sub("\n", value))
    lines = (
        " ".join(unescape(strip_tags(line)).replace("\xa0", " ").split())
        for line in with_line_breaks.splitlines()
    )
    return "\n".join(line for line in lines if line)
