"""Pełny katalog promptów dostępnych do edycji w panelu administracyjnym."""

from dataclasses import dataclass

from core.models import PromptTemplate


@dataclass(frozen=True)
class PromptDefinition:
    key: str
    label: str
    description: str


PROMPT_DEFINITIONS = (
    PromptDefinition(
        "innovation_assessment",
        "Ocena innowacyjności",
        "Instrukcja oceny czterech kryteriów i wyniku inicjatywy.",
    ),
    PromptDefinition(
        "development_recommendation",
        "Rekomendacja dalszego rozwoju",
        "Wskazanie etapu, ścieżki, najbliższego kroku i ryzyka inicjatywy.",
    ),
    PromptDefinition(
        "similarity_tagging",
        "Tagowanie podobieństwa inicjatyw",
        "Przypisanie problemu, odbiorców, branży, mechanizmu, typu, etapu i obszaru.",
    ),
    PromptDefinition(
        "innovation_radar_system",
        "System: Radar innowacji",
        "Wspólny kontekst dla wyszukiwania artykułów i ekstrakcji innowacji.",
    ),
    PromptDefinition(
        "news_selection",
        "Wybór artykułów z aktualności",
        "Selekcja linków z widocznej strony aktualności do dalszej analizy.",
    ),
    PromptDefinition(
        "news_extraction",
        "Ekstrakcja innowacji z artykułu",
        "Wydobycie nazwy, opisu, roli instytucji i daty publikacji.",
    ),
    PromptDefinition(
        "publication_date",
        "Data publikacji artykułu",
        "Ustalenie daty publikacji wyłącznie z treści pojedynczego artykułu.",
    ),
    PromptDefinition(
        "pairwise_ranking",
        "Porównywanie kryteriów parami",
        "Prompt dla względnego rankingu innowacji według pojedynczego kryterium.",
    ),
    PromptDefinition(
        "scoring_order_study",
        "Badanie kolejności ocen kryteriów",
        "Prompt badania zgodności kolejności wcześniej nadanych ocen.",
    ),
    PromptDefinition(
        "overall_order_study",
        "Badanie kolejności wyniku łącznego",
        "Prompt badania zgodności kolejności końcowych wyników innowacyjności.",
    ),
)


def configured_prompt_values() -> dict[str, str]:
    """Zwraca aktualne wartości z bazy dla pól w panelu."""
    saved = PromptTemplate.objects.in_bulk(field_name="key")
    return {
        definition.key: saved.get(definition.key, None).content
        if definition.key in saved else ""
        for definition in PROMPT_DEFINITIONS
    }
