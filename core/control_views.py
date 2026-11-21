"""Własny panel administracyjny Innoradaru."""

import csv
from datetime import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from core.control_forms import (
    CrawlScheduleForm,
    CredentialsForm,
    DevelopmentRecommendationForm,
    IdeaPartnerNeedsForm,
    IdeaProvenanceForm,
    InnovationIndicatorConfigurationForm,
    InnovationIndicatorForm,
    InstitutionListFilterForm,
    InstitutionPanelForm,
    NewScoringCalibrationExampleForm,
    PartnerOrganizationForm,
    PromptTemplatesForm,
    ScoringCalibrationExampleForm,
    ScoringCalibrationForm,
)
from core.geojson_views import podkarpackie_county_names
from core.models import (
    CrawlSchedule,
    DevelopmentRecommendation,
    Idea,
    InnovationIndicator,
    Institution,
    InstitutionImportRun,
    InstitutionNewsSource,
    NCBRImportRun,
    PartnerOrganization,
    PromptTemplate,
    ScoringCalibration,
    ScoringCalibrationExample,
)
from core.security import clear_attempts, client_ip, consume_attempt, is_rate_limited
from core.services.crawl_schedule import (
    configured_institution_types,
    configured_institutions,
    reschedule_crawl,
)
from core.services.institution_csv import import_institutions_csv
from core.services.partner_csv import import_partners_csv
from core.services.partner_matching import recommended_partners
from core.services.prompt_registry import PROMPT_DEFINITIONS, configured_prompt_values
from core.tasks import import_institution_news, import_ncbr_projects, recommend_idea


def panel_login(request):
    if request.user.is_authenticated:
        return redirect("control_dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    ip_address = client_ip(request)
    if request.method == "POST" and is_rate_limited("control-login", ip_address, limit=5):
        form.add_error(None, "Zbyt wiele nieudanych prób. Spróbuj ponownie za 15 minut.")
    elif request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        clear_attempts("control-login", ip_address)
        if (
            settings.ENFORCE_INITIAL_ADMIN_PASSWORD_CHANGE
            and request.user.username == "admin"
            and request.user.check_password("admin")
        ):
            messages.warning(request, "Zmień domyślne hasło przed dalszą pracą w panelu.")
            return redirect("control_credentials")
        return redirect(request.POST.get("next") or "control_dashboard")
    elif request.method == "POST":
        consume_attempt("control-login", ip_address, limit=5, timeout=900)
    return render(request, "core/control/login.html", {"form": form, "active_page": "control"})


@require_POST
@login_required
def panel_logout(request):
    logout(request)
    return redirect("control_login")


@login_required
def panel_dashboard(request):
    """Główna strona administracji prezentuje bieżące metryki systemu."""
    return _metrics_response(request)


def _format_duration(seconds):
    """Zwraca krótki, czytelny czas trwania zakończonego procesu."""
    if seconds is None:
        return "Brak danych"
    total_minutes = round(seconds / 60)
    if total_minutes < 1:
        return "poniżej 1 min"
    hours, minutes = divmod(total_minutes, 60)
    if not hours:
        return f"{minutes} min"
    if not minutes:
        return f"{hours} godz."
    return f"{hours} godz. {minutes} min"


@login_required
def panel_metrics(request):
    """Zachowuje dotychczasowy adres metryk i kieruje do głównego panelu."""
    return redirect("control_dashboard")


def _metrics_response(request):
    """Pokazuje administratorowi mierniki działania całego Innoradaru."""
    institution_imports = InstitutionImportRun.objects.aggregate(
        articles=Sum("ideas_created") + Sum("ideas_skipped"),
        duplicates=Sum("ideas_skipped"),
    )
    ncbr_imports = NCBRImportRun.objects.aggregate(
        articles=Sum("ideas_created") + Sum("ideas_skipped"),
        duplicates=Sum("ideas_skipped"),
    )
    import_durations = list(
        InstitutionImportRun.objects.exclude(duration_seconds__isnull=True).values_list(
            "duration_seconds", flat=True
        )
    )
    import_durations.extend(
        (finished_at - started_at).total_seconds()
        for started_at, finished_at in NCBRImportRun.objects.exclude(
            finished_at__isnull=True
        ).values_list("started_at", "finished_at")
    )
    recommendation_count = DevelopmentRecommendation.objects.count()
    approved_recommendation_count = DevelopmentRecommendation.objects.filter(
        status=DevelopmentRecommendation.Status.APPROVED
    ).count()
    partner_match_count = (
        Idea.objects.filter(partner_needs__organizations__is_active=True)
        .values("pk", "partner_needs__organizations__pk")
        .distinct()
        .count()
    )
    completed_scenarios = {
        "automatic": Idea.objects.exclude(source_url__isnull=True)
        .exclude(source_url="")
        .filter(scored_at__isnull=False, recommendation__isnull=False, partner_needs__isnull=False)
        .distinct()
        .count(),
        "manual": Idea.objects.filter(source_url__isnull=True)
        .filter(scored_at__isnull=False, recommendation__isnull=False, partner_needs__isnull=False)
        .distinct()
        .count(),
    }
    return render(
        request,
        "core/control/metrics.html",
        {
            "active_page": "control",
            "institution_count": Institution.objects.count(),
            "source_count": InstitutionNewsSource.objects.count()
            + Institution.objects.exclude(news_url="").count(),
            "article_count": (institution_imports["articles"] or 0)
            + (ncbr_imports["articles"] or 0),
            "idea_count": Idea.objects.count(),
            "duplicate_count": (institution_imports["duplicates"] or 0)
            + (ncbr_imports["duplicates"] or 0),
            "scored_idea_count": Idea.objects.filter(scored_at__isnull=False).count(),
            "recommendation_count": recommendation_count,
            "approved_recommendation_count": approved_recommendation_count,
            "partner_match_count": partner_match_count,
            "completed_scenarios": completed_scenarios,
            "average_import_duration": _format_duration(
                sum(import_durations) / len(import_durations) if import_durations else None
            ),
            "latest_institution_run": InstitutionImportRun.objects.first(),
            "latest_ncbr_run": NCBRImportRun.objects.first(),
        },
    )


@login_required
@require_http_methods(["GET"])
def panel_csv_export(request):
    """Eksportuje publiczne dane operacyjne bez danych zgłaszających."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="innoradar-innowacje.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "id",
            "nazwa",
            "opis",
            "data_dodania",
            "data_publikacji",
            "miejscowosc",
            "instytucja_zrodlowa",
            "rola_instytucji",
            "instytucja_wdrazajaca",
            "adres_zrodla",
            "wynik_innowacyjnosci",
            "oceniono",
            "oceny_i_uzasadnienia",
            "etap_rozwoju",
            "sciezka_rozwoju",
            "najblizszy_krok",
            "uzasadnienie_rekomendacji",
            "ryzyko_lub_niewiadoma",
            "potrzeby_partnerskie",
            "polecani_partnerzy",
        ]
    )
    ideas = (
        Idea.objects.select_related(
            "locality", "institution", "implementing_institution", "recommendation"
        )
        .prefetch_related("indicator_scores__indicator", "partner_needs")
        .order_by("pk")
    )
    for idea in ideas:
        recommendation = getattr(idea, "recommendation", None)
        assessments = " | ".join(
            f"{item.indicator.name}: {item.score or 'brak'} ({item.rationale})"
            for item in idea.indicator_scores.all()
        )
        partners = " | ".join(
            f"{match.organization.name}: {match.rationale}" for match in recommended_partners(idea)
        )
        writer.writerow(
            [
                idea.pk,
                idea.name,
                idea.content,
                idea.created_at.isoformat(),
                idea.published_at.isoformat() if idea.published_at else "",
                idea.locality.name if idea.locality else "",
                idea.institution.name if idea.institution else "",
                idea.get_institution_role_display(),
                idea.implementing_institution.name if idea.implementing_institution else "",
                idea.source_url or "",
                idea.innovation_score if idea.innovation_score is not None else "",
                idea.scored_at.isoformat() if idea.scored_at else "",
                assessments,
                recommendation.get_stage_display() if recommendation else "",
                recommendation.get_development_path_display() if recommendation else "",
                recommendation.next_step if recommendation else "",
                recommendation.rationale if recommendation else "",
                recommendation.risk if recommendation else "",
                " | ".join(need.name for need in idea.partner_needs.all()),
                partners,
            ]
        )
    return response


@login_required
def panel_credentials(request):
    form = CredentialsForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Dane logowania zostały zapisane.")
        return redirect("control_credentials")
    return render(
        request, "core/control/credentials.html", {"form": form, "active_page": "control"}
    )


@login_required
@require_http_methods(["GET"])
def panel_prompts(request):
    values = configured_prompt_values()
    form = PromptTemplatesForm(PROMPT_DEFINITIONS, initial=values)
    prompts = tuple(
        {
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "content": form.initial[definition.key],
            "update_url": reverse("control_prompt_update", args=[definition.key]),
        }
        for definition in PROMPT_DEFINITIONS
    )
    return render(
        request,
        "core/control/prompts.html",
        {
            "active_page": "control",
            "prompts": prompts,
            "selected_prompt": prompts[0],
        },
    )


@login_required
@require_POST
def panel_prompt_update(request, prompt_key):
    """Zapisuje pojedynczy prompt bez odświeżania panelu."""
    if prompt_key not in {definition.key for definition in PROMPT_DEFINITIONS}:
        raise Http404("Nie znaleziono prompta.")

    content = request.POST.get(prompt_key, "")
    if not content.strip():
        return JsonResponse({"error": "Prompt nie może być pusty."}, status=400)

    prompt, _ = PromptTemplate.objects.update_or_create(
        key=prompt_key,
        defaults={"content": content},
    )
    return JsonResponse(
        {
            "message": "Prompt został zapisany.",
            "updated_at": timezone.localtime(prompt.updated_at).isoformat(),
        }
    )


@login_required
@require_http_methods(["GET"])
def panel_calibration(request):
    """Wyświetla konfigurację oraz przykłady kalibracji ocen."""
    calibration, _ = ScoringCalibration.objects.get_or_create(pk=1)
    examples = calibration.examples.all()
    indicator_names = dict(InnovationIndicator.objects.values_list("key", "name"))
    return render(
        request,
        "core/control/calibration.html",
        {
            "active_page": "control",
            "calibration_form": ScoringCalibrationForm(instance=calibration),
            "calibration_examples": [
                (
                    example,
                    ScoringCalibrationExampleForm(prefix=f"example-{example.pk}", instance=example),
                    indicator_names.get(example.criterion, example.criterion),
                )
                for example in examples
            ],
            "calibration_example_form": NewScoringCalibrationExampleForm(prefix="new"),
        },
    )


@login_required
def panel_recommendations(request):
    """Lista ocenionych inicjatyw i ich rekomendacji rozwojowych."""
    ideas = Idea.objects.filter(scored_at__isnull=False).select_related("recommendation")
    page = Paginator(ideas, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "core/control/recommendations.html",
        {"active_page": "control", "page": page},
    )


@login_required
@require_http_methods(["GET", "POST"])
def panel_recommendation_form(request, idea_id):
    """Pozwala zatwierdzić lub ręcznie skorygować rekomendację danej inicjatywy."""
    idea = get_object_or_404(
        Idea.objects.select_related("recommendation", "institution", "implementing_institution"),
        pk=idea_id,
    )
    recommendation = getattr(idea, "recommendation", None)
    if recommendation is None:
        messages.info(request, "Rekomendacja nie została jeszcze wygenerowana.")
        return redirect("control_recommendations")
    form = DevelopmentRecommendationForm(request.POST or None, instance=recommendation)
    needs_form = IdeaPartnerNeedsForm(request.POST or None, instance=idea)
    provenance_form = IdeaProvenanceForm(request.POST or None, instance=idea)
    if (
        request.method == "POST"
        and form.is_valid()
        and needs_form.is_valid()
        and provenance_form.is_valid()
    ):
        saved = form.save(commit=False)
        saved.approved_at = timezone.now() if saved.status == saved.Status.APPROVED else None
        saved.save()
        needs_form.save()
        provenance_form.save()
        messages.success(request, "Rekomendacja została zapisana.")
        return redirect("control_recommendation_edit", idea_id=idea.pk)
    return render(
        request,
        "core/control/recommendation_form.html",
        {
            "active_page": "control",
            "form": form,
            "needs_form": needs_form,
            "provenance_form": provenance_form,
            "idea": idea,
            "recommendation": recommendation,
        },
    )


@login_required
@require_POST
def panel_recommendation_regenerate(request, idea_id):
    """Kolejkuje ponowne wygenerowanie rekomendacji bez blokowania panelu."""
    idea = get_object_or_404(Idea, pk=idea_id)
    recommend_idea.delay(idea.pk)
    messages.success(request, "Ponowne generowanie rekomendacji zostało uruchomione.")
    return redirect("control_recommendation_edit", idea_id=idea.pk)


@login_required
@require_http_methods(["GET", "POST"])
def panel_indicators(request):
    """Wyświetla dynamiczne wskaźniki w kolejności używanej przez oceniacz."""
    indicators = tuple(InnovationIndicator.objects.all())
    configuration_form = InnovationIndicatorConfigurationForm(indicators)
    return render(
        request,
        "core/control/indicators.html",
        {
            "active_page": "control",
            "indicators": indicators,
            "configuration_form": configuration_form,
            "configuration_rows": [
                (
                    indicator,
                    configuration_form[f"enabled_{indicator.pk}"],
                    configuration_form[f"weight_{indicator.pk}"],
                )
                for indicator in indicators
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def panel_indicator_form(request, indicator_id=None):
    """Dodaje albo edytuje pojedynczy wskaźnik."""
    indicator = get_object_or_404(InnovationIndicator, pk=indicator_id) if indicator_id else None
    form = InnovationIndicatorForm(request.POST or None, instance=indicator)
    if request.method == "POST" and form.is_valid():
        saved_indicator = form.save(commit=False)
        if indicator is None:
            positions = InnovationIndicator.objects.aggregate(max_position=Max("position"))
            highest_position = positions["max_position"]
            saved_indicator.position = (highest_position or 0) + 1
            saved_indicator.weight = 0
            saved_indicator.enabled = False
        saved_indicator.save()
        messages.success(request, "Wskaźnik został zapisany.")
        return redirect("control_indicators")
    return render(
        request,
        "core/control/indicator_form.html",
        {"active_page": "control", "form": form, "indicator": indicator},
    )


@login_required
@require_POST
def panel_indicator_delete(request, indicator_id):
    """Usuwa wskaźnik, który nie jest już potrzebny w kolejnych ocenach."""
    get_object_or_404(InnovationIndicator, pk=indicator_id).delete()
    messages.success(request, "Wskaźnik został usunięty.")
    return redirect("control_indicators")


@login_required
@require_POST
def panel_indicator_configuration_update(request):
    """Zapisuje równocześnie wagi i aktywność wskaźników."""
    indicators = tuple(InnovationIndicator.objects.all())
    form = InnovationIndicatorConfigurationForm(indicators, request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Konfiguracja wskaźników została zapisana.")
        return redirect("control_indicators")
    configuration_rows = [
        (indicator, form[f"enabled_{indicator.pk}"], form[f"weight_{indicator.pk}"])
        for indicator in indicators
    ]
    return render(
        request,
        "core/control/indicators.html",
        {
            "active_page": "control",
            "indicators": indicators,
            "configuration_form": form,
            "configuration_rows": configuration_rows,
        },
        status=400,
    )


@login_required
@require_POST
def panel_indicator_move(request, indicator_id, direction):
    """Przesuwa wskaźnik o jedną pozycję, bez ręcznego wpisywania numerów."""
    if direction not in {"up", "down"}:
        raise Http404("Nieznany kierunek przesunięcia.")

    with transaction.atomic():
        indicator = get_object_or_404(
            InnovationIndicator.objects.select_for_update(), pk=indicator_id
        )
        ordered = list(InnovationIndicator.objects.select_for_update().order_by("position", "pk"))
        index = next(index for index, item in enumerate(ordered) if item.pk == indicator.pk)
        target_index = index - 1 if direction == "up" else index + 1
        if 0 <= target_index < len(ordered):
            other = ordered[target_index]
            indicator_position = indicator.position
            other_position = other.position
            temporary_position = (max(item.position for item in ordered) if ordered else 0) + 1
            indicator.position = temporary_position
            indicator.save(update_fields=["position"])
            other.position = indicator_position
            other.save(update_fields=["position"])
            indicator.position = other_position
            indicator.save(update_fields=["position"])

    return redirect("control_indicators")


@login_required
@require_POST
def panel_calibration_update(request):
    """Zapisuje, czy oceniacz ma dołączać przykłady kalibracyjne."""
    calibration, _ = ScoringCalibration.objects.get_or_create(pk=1)
    form = ScoringCalibrationForm(request.POST, instance=calibration)
    form.is_valid()
    form.save()
    messages.success(request, "Ustawienie kalibracji zostało zapisane.")
    return redirect("control_calibration")


@login_required
@require_POST
def panel_calibration_example_add(request):
    """Dodaje przykład wykorzystywany przez aktywną kalibrację."""
    calibration, _ = ScoringCalibration.objects.get_or_create(pk=1)
    form = NewScoringCalibrationExampleForm(request.POST, prefix="new")
    if form.is_valid():
        example = form.save(commit=False)
        example.calibration = calibration
        example.position = (
            calibration.examples.filter(criterion=example.criterion).aggregate(Max("position"))[
                "position__max"
            ]
            or 0
        ) + 1
        example.save()
        messages.success(request, "Przykład kalibracyjny został dodany.")
    else:
        messages.error(request, "Nie udało się dodać przykładu kalibracyjnego.")
    return redirect("control_calibration")


@login_required
@require_POST
def panel_calibration_example_update(request, example_id):
    """Aktualizuje pojedynczy przykład kalibracyjny."""
    example = get_object_or_404(ScoringCalibrationExample, pk=example_id)
    form = ScoringCalibrationExampleForm(
        request.POST, prefix=f"example-{example.pk}", instance=example
    )
    if form.is_valid():
        form.save()
        messages.success(request, "Przykład kalibracyjny został zapisany.")
    else:
        messages.error(request, "Nie udało się zapisać przykładu kalibracyjnego.")
    return redirect("control_calibration")


@login_required
@require_POST
def panel_calibration_example_delete(request, example_id):
    """Usuwa przykład kalibracyjny z bazy."""
    get_object_or_404(ScoringCalibrationExample, pk=example_id).delete()
    messages.success(request, "Przykład kalibracyjny został usunięty.")
    return redirect("control_calibration")


@login_required
def panel_institutions(request):
    filters = InstitutionListFilterForm(request.GET or None)
    institutions = Institution.objects.select_related("locality")
    locality_label = ""
    if filters.is_valid():
        data = filters.cleaned_data
        if data["institution_type"]:
            institutions = institutions.filter(institution_type=data["institution_type"])
        if data["locality"]:
            institutions = institutions.filter(locality=data["locality"])
            locality_label = _locality_display(data["locality"])
        if data["published_from"]:
            institutions = institutions.filter(ideas__published_at__gte=data["published_from"])
        if data["published_to"]:
            institutions = institutions.filter(ideas__published_at__lte=data["published_to"])
    institutions = institutions.annotate(ideas_count=Count("ideas", distinct=True)).order_by(
        "name", "pk"
    )
    page = Paginator(institutions, 25).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "core/control/institutions.html",
        {
            "active_page": "control",
            "filters": filters,
            "filter_query": query_params.urlencode(),
            "locality_label": locality_label,
            "page": page,
            "page_range": page.paginator.get_elided_page_range(
                page.number, on_each_side=1, on_ends=1
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def panel_institution_form(request, institution_id=None):
    institution = get_object_or_404(Institution, pk=institution_id) if institution_id else None
    form = InstitutionPanelForm(request.POST or None, instance=institution)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Instytucja została zapisana.")
        return redirect("control_institutions")
    return render(
        request,
        "core/control/institution_form.html",
        {
            "active_page": "control",
            "form": form,
            "institution": institution,
            "locality_label": _locality_label(institution),
        },
    )


@login_required
@require_POST
def panel_institution_delete(request, institution_id):
    get_object_or_404(Institution, pk=institution_id).delete()
    messages.success(request, "Instytucja została usunięta.")
    return redirect("control_institutions")


@login_required
@require_http_methods(["GET", "POST"])
def panel_institutions_csv(request):
    if request.method == "POST":
        try:
            count = import_institutions_csv(request.FILES["file"])
        except (KeyError, ValidationError, csv.Error) as error:
            messages.error(request, f"Nie udało się zaimportować CSV: {error}")
        else:
            messages.success(request, f"Zaimportowano {count} wierszy.")
            return redirect("control_institutions")
    return render(request, "core/control/institutions_csv.html", {"active_page": "control"})


@login_required
def panel_partners(request):
    """Lista organizacji dostępnych do dalszego rozwoju inicjatyw."""
    partners = PartnerOrganization.objects.select_related("locality").prefetch_related("tags")
    page = Paginator(partners, 25).get_page(request.GET.get("page"))
    return render(request, "core/control/partners.html", {"active_page": "control", "page": page})


@login_required
@require_http_methods(["GET", "POST"])
def panel_partner_form(request, partner_id=None):
    """Dodaje lub aktualizuje organizację partnerską."""
    partner = get_object_or_404(PartnerOrganization, pk=partner_id) if partner_id else None
    form = PartnerOrganizationForm(request.POST or None, instance=partner)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Partner został zapisany.")
        return redirect("control_partners")
    return render(
        request,
        "core/control/partner_form.html",
        {"active_page": "control", "form": form, "partner": partner},
    )


@login_required
@require_POST
def panel_partner_delete(request, partner_id):
    get_object_or_404(PartnerOrganization, pk=partner_id).delete()
    messages.success(request, "Partner został usunięty.")
    return redirect("control_partners")


@login_required
@require_http_methods(["GET", "POST"])
def panel_partners_csv(request):
    if request.method == "POST":
        try:
            count = import_partners_csv(request.FILES["file"])
        except (KeyError, ValidationError, csv.Error) as error:
            messages.error(request, f"Nie udało się zaimportować CSV: {error}")
        else:
            messages.success(request, f"Zaimportowano {count} partnerów.")
            return redirect("control_partners")
    return render(request, "core/control/partners_csv.html", {"active_page": "control"})


@login_required
@require_http_methods(["GET", "POST"])
def panel_crawling(request):
    crawl_schedule, _ = CrawlSchedule.objects.get_or_create(pk=1, defaults={"run_at": time(3)})
    if request.method == "POST":
        institution_types = configured_institution_types(crawl_schedule)
        if InstitutionImportRun.objects.filter(status__in=["pending", "running"]).exists():
            messages.error(request, "Crawling już trwa.")
        else:
            total = configured_institutions(
                institution_types, crawl_schedule.voivodeship_code
            ).count()
            run = InstitutionImportRun.objects.create(
                status="pending",
                institution_types=institution_types,
                voivodeship_code=crawl_schedule.voivodeship_code,
                institutions_total=total,
                current_action="Oczekiwanie na uruchomienie zadania",
            )
            import_institution_news.delay(run.pk)
            messages.success(request, "Crawling został uruchomiony.")
            return redirect("control_crawling")
    latest_run = InstitutionImportRun.objects.first()
    return render(
        request,
        "core/control/crawling.html",
        {
            "active_page": "control",
            "latest_run": latest_run,
            "latest_ncbr_run": NCBRImportRun.objects.first(),
            "schedule_form": CrawlScheduleForm(instance=crawl_schedule),
            "crawl_schedule": crawl_schedule,
        },
    )


@login_required
@require_POST
def panel_crawling_schedule(request):
    """Zapisuje harmonogram automatycznego, pełnego crawlowania."""
    crawl_schedule, _ = CrawlSchedule.objects.get_or_create(pk=1, defaults={"run_at": time(3)})
    form = CrawlScheduleForm(request.POST, instance=crawl_schedule)
    if form.is_valid():
        crawl_schedule = form.save()
        reschedule_crawl(crawl_schedule)
        messages.success(request, "Harmonogram crawlowania został zapisany.")
    else:
        messages.error(request, "Nie udało się zapisać harmonogramu crawlowania.")
    return redirect("control_crawling")


@login_required
@require_POST
def panel_crawling_stop(request):
    run = InstitutionImportRun.objects.filter(status__in=["pending", "running"]).first()
    if run is None:
        messages.error(request, "Nie ma aktywnego crawlera do zatrzymania.")
    else:
        InstitutionImportRun.objects.filter(pk=run.pk, status__in=["pending", "running"]).update(
            status="stopped",
            current_action="Crawling zatrzymany przez administratora",
            retry_after=None,
        )
        run.events.create(message="Crawling zatrzymany przez administratora.")
        messages.success(request, "Crawling został zatrzymany.")
    return redirect("control_crawling")


@login_required
@require_POST
def panel_ncbr_crawling(request):
    """Uruchamia osobny import publicznego katalogu NCBR."""
    if NCBRImportRun.objects.filter(status__in=["pending", "running"]).exists():
        messages.error(request, "Crawling NCBR już trwa.")
    else:
        run = NCBRImportRun.objects.create(
            status="pending",
            current_action="Oczekiwanie na uruchomienie zadania",
        )
        import_ncbr_projects.delay(run.pk)
        messages.success(request, "Crawling NCBR został uruchomiony.")
    return redirect("control_crawling")


@login_required
def panel_crawling_status(request):
    run = InstitutionImportRun.objects.prefetch_related("events").first()
    if run is None:
        return JsonResponse({"run": None})
    total = max(run.institutions_total, run.institutions_processed)
    return JsonResponse(
        {
            "run": {
                "status": run.status,
                "total": total,
                "processed": run.institutions_processed,
                "eta_seconds": _crawling_eta_seconds(run, total),
                "created": run.ideas_created,
                "skipped": run.ideas_skipped,
                "institution": run.current_institution,
                "action": run.current_action,
                "error": run.error,
                "events": [
                    {
                        "time": timezone.localtime(event.created_at).strftime("%H:%M:%S"),
                        "message": event.message,
                    }
                    for event in run.events.all()[:12]
                ],
            }
        }
    )


@login_required
def panel_ncbr_crawling_status(request):
    run = NCBRImportRun.objects.prefetch_related("events").first()
    if run is None:
        return JsonResponse({"run": None})
    total = max(run.projects_total, run.projects_processed)
    return JsonResponse(
        {
            "run": {
                "status": run.status,
                "total": total,
                "processed": run.projects_processed,
                "eta_seconds": None,
                "created": run.ideas_created,
                "skipped": run.ideas_skipped,
                "institution": "",
                "action": run.current_action,
                "error": run.error,
                "events": [
                    {
                        "time": timezone.localtime(event.created_at).strftime("%H:%M:%S"),
                        "message": event.message,
                    }
                    for event in run.events.all()[:12]
                ],
            }
        }
    )


def _crawling_eta_seconds(run, total):
    if (
        run.status != "running"
        or not run.institutions_processed
        or total <= run.institutions_processed
    ):
        return None
    elapsed = max((timezone.now() - run.started_at).total_seconds(), 0)
    return round(elapsed * (total - run.institutions_processed) / run.institutions_processed)


def _locality_label(institution):
    return _locality_display(institution.locality if institution else None)


def _locality_display(locality):
    if not locality:
        return ""
    county = podkarpackie_county_names().get(locality.county_code)
    return f"{locality.name}, {county or f'powiat {locality.county_code}'}"
