"""Widoki JSON wykorzystywane przez interfejs Vue."""

from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache

from .geojson_views import podkarpackie_county_names
from .models import Idea, Locality


def chrome_devtools_config(request):
    """Zapobiega nieistotnemu błędowi 404 generowanemu przez Chrome DevTools."""
    return JsonResponse({})


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
