"""Widoki stron HTML Innoradar."""

from urllib.parse import urlencode

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from .forms import IdeaForm
from .innovation_catalog import INNOVATION_SORTS, annotate_criteria, assessment_rows
from .models import Idea, InnovationIndicator, Institution
from .security import client_ip, consume_attempt, too_many_requests
from .services.idea_similarity import similar_ideas
from .services.partner_matching import recommended_partners
from .tasks import score_idea


@never_cache
def home(request):
    institution_counts = Institution.objects.aggregate(
        total=Count("pk"),
        schools=Count("pk", filter=Q(institution_type=Institution.Type.SCHOOL)),
        universities=Count("pk", filter=Q(institution_type=Institution.Type.UNIVERSITY)),
        local_governments=Count(
            "pk", filter=Q(institution_type=Institution.Type.LOCAL_GOVERNMENT)
        ),
        other=Count("pk", filter=Q(institution_type=Institution.Type.OTHER)),
    )
    return render(
        request,
        "core/home.html",
        {"active_page": "home", "institution_counts": institution_counts},
    )


@never_cache
def submit_idea(request):
    if request.method == "POST":
        if consume_attempt("idea-submission", client_ip(request), limit=5, timeout=900):
            return too_many_requests(
                '{"errors": {"__all__": ["Zbyt wiele prób. Spróbuj ponownie za 15 minut."]}}'
            )
        form = IdeaForm(request.POST)
        if form.is_valid():
            idea = form.save()
            score_idea.delay(idea.pk)
            return JsonResponse(
                {
                    "id": idea.id,
                    "redirect_url": reverse("innovation_detail", args=[idea.pk]),
                },
                status=201,
            )
        return JsonResponse({"errors": form.errors}, status=400)
    return render(request, "core/submit_idea.html", {"form": IdeaForm(), "active_page": "submit"})


@never_cache
def privacy(request):
    return render(
        request,
        "core/privacy.html",
        {
            "active_page": "privacy",
            "privacy_contact_email": settings.PRIVACY_CONTACT_EMAIL,
            "privacy_controller_name": settings.PRIVACY_CONTROLLER_NAME,
        },
    )


@never_cache
def innovation_map(request):
    map_ideas = (
        Idea.objects.select_related("locality")
        .filter(
            Q(innovation_score__isnull=False) | Q(scored_at__isnull=False),
            locality__isnull=False,
            locality__latitude__isnull=False,
            locality__longitude__isnull=False,
        )
        .order_by("-innovation_score", "-created_at")
    )
    return render(
        request,
        "core/innovation_map.html",
        {"active_page": "map", "map_ideas": map_ideas},
    )


@never_cache
def innovations(request):
    """Wyświetla ocenione innowacje pobrane ze źródeł zewnętrznych."""
    return _innovation_catalog(
        request,
        ideas=Idea.objects.exclude(source_url__isnull=True).exclude(source_url=""),
        active_page="innovations",
        title="Pobrane innowacje",
        empty_message="Pobrane innowacje pojawią się tutaj po zakończeniu analizy.",
        caption="Oceny innowacyjności pobranych inicjatyw",
    )


@never_cache
def submitted_innovations(request):
    """Wyświetla ocenione inicjatywy zgłoszone bezpośrednio przez formularz."""
    return _innovation_catalog(
        request,
        ideas=Idea.objects.filter(Q(source_url__isnull=True) | Q(source_url="")),
        active_page="submitted_innovations",
        title="Zgłoszone innowacje",
        empty_message="Zgłoszone innowacje pojawią się tutaj po zakończeniu analizy.",
        caption="Oceny innowacyjności zgłoszonych inicjatyw",
        date_label="Data dodania",
        date_sort_label="Data dodania",
        date_field="created_at",
        show_institution_filter=False,
    )


def _innovation_catalog(
    request,
    *,
    ideas,
    active_page,
    title,
    empty_message,
    caption,
    date_label="Data publikacji",
    date_sort_label="Data publikacji",
    date_field="published_at",
    show_institution_filter=True,
):
    """Renderuje katalog jednego pochodzenia, po dziewięć kart na stronę."""
    sort = request.GET.get("sort", "score")
    if sort not in INNOVATION_SORTS:
        sort = "score"

    scored_ideas = ideas.filter(
        Q(innovation_score__isnull=False) | Q(scored_at__isnull=False)
    )
    institution_type_counts = ()
    institution_type = ""
    unassigned_count = 0
    pagination_parameters = {"sort": sort}
    if show_institution_filter:
        institution_type_counts = tuple(
            scored_ideas.exclude(institution__isnull=True)
            .values("institution__institution_type")
            .annotate(count=Count("pk"))
            .order_by("institution__institution_type")
        )
        institution_types = tuple(
            item["institution__institution_type"] for item in institution_type_counts
        )
        institution_type = request.GET.get("type", "")
        unassigned_count = scored_ideas.filter(institution__isnull=True).count()
        if institution_type not in (*institution_types, "unassigned"):
            institution_type = ""
        if institution_type == "unassigned":
            scored_ideas = scored_ideas.filter(institution__isnull=True)
        elif institution_type:
            scored_ideas = scored_ideas.filter(
                institution__institution_type=institution_type
            )
        pagination_parameters["type"] = institution_type

    indicators = tuple(InnovationIndicator.objects.filter(enabled=True))
    ordering = INNOVATION_SORTS[sort]
    if sort == "date" and date_field == "created_at":
        ordering = ("-created_at",)
    ideas = (
        annotate_criteria(scored_ideas)
        .prefetch_related("indicator_scores__indicator", "similarity_tags")
        .order_by(*ordering)
    )
    page = Paginator(ideas, 9).get_page(request.GET.get("page"))
    return render(
        request,
        "core/innovations.html",
        {
            "active_page": active_page,
            "catalog_title": title,
            "empty_message": empty_message,
            "catalog_caption": caption,
            "date_label": date_label,
            "date_sort_label": date_sort_label,
            "date_field": date_field,
            "page": page,
            "page_range": tuple(
                page.paginator.get_elided_page_range(
                    number=page.number, on_each_side=1, on_ends=1
                )
            ),
            "pagination_query": urlencode(pagination_parameters),
            "sort": sort,
            "institution_type": institution_type,
            "show_institution_filter": show_institution_filter,
            "institution_types": tuple(
                (
                    item["institution__institution_type"],
                    (
                        "{label} ({count} innowacji)".format(
                            label=Institution.Type(
                                item["institution__institution_type"]
                            ).label,
                            count=item["count"],
                        )
                    ),
                )
                for item in institution_type_counts
            ),
            "unassigned_count": unassigned_count,
            "indicators": indicators,
        },
    )


@never_cache
def innovation_detail(request, idea_id):
    """Wyświetla publiczną stronę ocenionej inicjatywy."""
    idea = get_object_or_404(
        Idea.objects.select_related(
            "locality", "recommendation", "institution", "implementing_institution"
        )
        .prefetch_related("indicator_scores__indicator", "similarity_tags")
        .filter(
            Q(innovation_score__isnull=False)
            | Q(scored_at__isnull=False)
            | Q(source_url__isnull=True)
            | Q(source_url="")
        ),
        pk=idea_id,
    )
    assessments = tuple(idea.indicator_scores.select_related("indicator").all())
    if not assessments:
        assessments = assessment_rows(idea.innovation_details, idea.innovation_rationales)
    return render(
        request,
        "core/innovation_detail.html",
        {
            "active_page": "innovations" if idea.source_url else "submitted_innovations",
            "idea": idea,
            "back_page": "innovations" if idea.source_url else "submitted_innovations",
            "back_label": "Pobrane innowacje" if idea.source_url else "Zgłoszone innowacje",
            "assessments": assessments,
            "partner_matches": recommended_partners(idea),
            "similar_ideas": similar_ideas(idea),
        },
    )
