"""Dostęp do promptów LLM przechowywanych wyłącznie w bazie danych."""

from core.models import PromptTemplate


class PromptNotConfiguredError(RuntimeError):
    """Brakuje wymaganego promptu w bazie danych."""


def get_prompt(key: str) -> str:
    """Zwraca aktualną treść promptu zapisaną przez panel administracyjny."""
    content = PromptTemplate.objects.filter(key=key).values_list("content", flat=True).first()
    if not content or not content.strip():
        raise PromptNotConfiguredError(f"Brakuje promptu LLM: {key}.")
    return content
