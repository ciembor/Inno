"""Dopasowanie partnerów do jawnie opisanych potrzeb inicjatywy."""

from dataclasses import dataclass

from django.db.models import Count, Q

from core.models import Idea, PartnerOrganization


@dataclass(frozen=True)
class PartnerMatch:
    """Partner i zrozumiałe uzasadnienie jego dopasowania."""

    organization: PartnerOrganization
    matching_tags: tuple[str, ...]

    @property
    def rationale(self) -> str:
        return "Wspólne obszary: " + ", ".join(self.matching_tags) + "."


def recommended_partners(idea: Idea, limit: int = 5) -> tuple[PartnerMatch, ...]:
    """Zwraca maksymalnie pięciu aktywnych partnerów o wspólnych tagach."""
    needs = tuple(idea.partner_needs.values_list("pk", "name"))
    if not needs:
        return ()
    need_ids = [tag_id for tag_id, _ in needs]
    partners = (
        PartnerOrganization.objects.filter(is_active=True, tags__in=need_ids)
        .select_related("locality")
        .prefetch_related("tags")
        .annotate(match_count=Count("tags", filter=Q(tags__in=need_ids), distinct=True))
        .order_by("-match_count", "name")[:limit]
    )
    matches = []
    for partner in partners:
        tags = tuple(tag.name for tag in partner.tags.all() if tag.pk in need_ids)
        matches.append(PartnerMatch(organization=partner, matching_tags=tags))
    return tuple(matches)
