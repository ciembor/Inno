"""Publiczne, wyłącznie odczytowe API JSON Innoradaru."""

from django.db.models import Q
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .geojson_views import podkarpackie_county_names
from .models import Idea, Locality
from .services.partner_matching import recommended_partners


def chrome_devtools_config(request):
    """Zapobiega nieistotnemu błędowi 404 generowanemu przez Chrome DevTools."""
    return JsonResponse({})


@require_GET
def api_docs(request):
    """Opis publicznych zasobów API bez żadnych operacji zapisu."""
    return JsonResponse(
        {
            "title": "Innoradar API",
            "version": "v1",
            "read_only": True,
            "privacy": "API nie udostępnia danych zgłaszających ani prywatnych kontaktów.",
            "endpoints": [
                {
                    "method": "GET",
                    "url": reverse("api_innovations"),
                    "description": "Stronicowana lista publicznych innowacji.",
                    "parameters": {
                        "page": "Numer strony, domyślnie 1.",
                        "page_size": "Liczba wyników 1–50, domyślnie 20.",
                    },
                },
                {
                    "method": "GET",
                    "url": f"{reverse('api_innovations')}{{id}}/",
                    "description": "Szczegóły publicznej innowacji, ocena i rekomendacje.",
                },
            ],
        }
    )


def locality_search(request):
    """Zwraca podpowiedzi z zaimportowanego słownika SIMC."""
    query = request.GET.get("q", "").strip()
    localities = Locality.objects.filter(name__istartswith=query)[:30] if len(query) >= 2 else []
    county_names = podkarpackie_county_names()
    return JsonResponse(
        {
            "results": [
                {
                    "id": item.pk,
                    "name": item.name,
                    "county": county_names.get(item.county_code, f"powiat {item.county_code}"),
                }
                for item in localities
            ]
        }
    )


@never_cache
@require_GET
def innovations(request):
    """Zwraca stronicowaną listę innowacji widocznych w katalogu publicznym."""
    page = _positive_int(request.GET.get("page"), default=1, maximum=None)
    page_size = _positive_int(request.GET.get("page_size"), default=20, maximum=50)
    ideas = _public_ideas().order_by("-innovation_score", "-created_at")
    start = (page - 1) * page_size
    results = tuple(ideas[start : start + page_size])
    count = ideas.count()
    return JsonResponse(
        {
            "count": count,
            "page": page,
            "page_size": page_size,
            "next": (
                _api_page_url(request, page + 1, page_size)
                if start + page_size < count
                else None
            ),
            "previous": _api_page_url(request, page - 1, page_size) if page > 1 else None,
            "results": [_idea_payload(idea) for idea in results],
        }
    )


@never_cache
@require_GET
def innovation_detail(request, idea_id):
    """Zwraca pełne publiczne dane jednej innowacji."""
    idea = _public_ideas().filter(pk=idea_id).first()
    if idea is None:
        raise Http404("Nie znaleziono innowacji.")
    return JsonResponse(_idea_payload(idea, detailed=True))


def _public_ideas():
    return (
        Idea.objects.select_related(
            "institution", "implementing_institution", "locality", "recommendation"
        )
        .prefetch_related("indicator_scores__indicator", "similarity_tags")
        .filter(
            Q(innovation_score__isnull=False)
            | Q(scored_at__isnull=False)
            | Q(source_url__isnull=True)
            | Q(source_url="")
        )
    )


def _positive_int(value, *, default, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 1:
        return default
    return min(number, maximum) if maximum else number


def _api_page_url(request, page, page_size):
    return f"{request.path}?page={page}&page_size={page_size}"


def _idea_payload(idea, detailed=False):
    payload = {
        "id": idea.pk,
        "name": idea.name,
        "url": reverse("innovation_detail", args=[idea.pk]),
        "api_url": reverse("api_innovation_detail", args=[idea.pk]),
        "score": float(idea.innovation_score) if idea.innovation_score is not None else None,
        "locality": idea.locality.name if idea.locality else None,
        "institution": idea.institution.name if idea.institution else None,
        "published_at": idea.published_at.isoformat() if idea.published_at else None,
        "added_at": idea.created_at.isoformat(),
    }
    if detailed:
        payload.update(
            {
                "content": idea.content,
                "source": {"label": idea.source_label, "url": idea.source_url},
                "institution_role": idea.get_institution_role_display(),
                "implementing_institution": (
                    idea.implementing_institution.name if idea.implementing_institution else None
                ),
                "similarity_tags": [
                    {"category": tag.category, "name": tag.name}
                    for tag in idea.similarity_tags.all()
                ],
                "assessments": [
                    {
                        "criterion": item.indicator.name,
                        "score": item.score,
                        "rationale": item.rationale,
                    }
                    for item in idea.indicator_scores.all()
                ],
                "recommendation": _recommendation_payload(idea),
                "partners": [
                    {
                        "name": match.organization.name,
                        "type": match.organization.get_organization_type_display(),
                        "contact": match.organization.contact,
                        "contact_url": match.organization.contact_url,
                        "rationale": match.rationale,
                    }
                    for match in recommended_partners(idea)
                ],
            }
        )
    return payload


def _recommendation_payload(idea):
    recommendation = getattr(idea, "recommendation", None)
    if not recommendation:
        return None
    return {
        "stage": recommendation.get_stage_display(),
        "path": recommendation.get_development_path_display(),
        "next_step": recommendation.next_step,
        "rationale": recommendation.rationale,
        "risk": recommendation.risk,
        "status": recommendation.get_status_display(),
    }


@never_cache
def innovation_map_data(request):
    ideas = (
        Idea.objects.select_related("locality")
        .filter(
            Q(innovation_score__isnull=False) | Q(scored_at__isnull=False),
            locality__isnull=False,
            locality__latitude__isnull=False,
            locality__longitude__isnull=False,
        )
        .order_by("-innovation_score", "-created_at")
    )
    return JsonResponse(
        {
            "innovations": [
                {
                    "id": idea.pk,
                    "name": idea.name,
                    "url": reverse("innovation_detail", args=[idea.pk]),
                    "score": (
                        float(idea.innovation_score) if idea.innovation_score is not None else None
                    ),
                    "locality": idea.locality.name,
                    "latitude": idea.locality.latitude,
                    "longitude": idea.locality.longitude,
                }
                for idea in ideas
            ]
        }
    )
