"""Domyślne potrzeby partnerstwa wynikające z rekomendowanej ścieżki rozwoju."""

from core.models import DevelopmentRecommendation, Idea, PartnerTag

PATH_TAG_KEYS = {
    DevelopmentRecommendation.Path.PILOT: ("pilotaz", "badania"),
    DevelopmentRecommendation.Path.TRANSFER: ("transfer", "wdrozenie"),
    DevelopmentRecommendation.Path.PARTNERSHIP: ("wdrozenie", "badania"),
    DevelopmentRecommendation.Path.FINANCING: ("finansowanie",),
    DevelopmentRecommendation.Path.COMMERCIALISATION: ("finansowanie", "wdrozenie"),
    DevelopmentRecommendation.Path.IMPLEMENTATION: ("wdrozenie", "pilotaz"),
}


def add_default_partner_needs(idea: Idea, development_path: str) -> None:
    """Nadaje potrzeby dla nowych inicjatyw, nie zastępując wyboru administratora."""
    if idea.partner_needs.exists():
        return
    tags = PartnerTag.objects.filter(key__in=PATH_TAG_KEYS.get(development_path, ()))
    idea.partner_needs.add(*tags)
