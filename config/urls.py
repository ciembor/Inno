from django.conf import settings
from django.urls import path
from django.views.generic import RedirectView

from core import api_views, control_views, geojson_views, page_views

urlpatterns = [
    path("admin/", RedirectView.as_view(pattern_name="control_dashboard", permanent=False)),
    path("administracja/", control_views.panel_dashboard, name="control_dashboard"),
    path("administracja/logowanie/", control_views.panel_login, name="control_login"),
    path("administracja/wyloguj/", control_views.panel_logout, name="control_logout"),
    path(
        "administracja/dane-logowania/", control_views.panel_credentials, name="control_credentials"
    ),
    path("administracja/prompty/", control_views.panel_prompts, name="control_prompts"),
    path("administracja/kalibracja/", control_views.panel_calibration, name="control_calibration"),
    path(
        "administracja/rekomendacje/",
        control_views.panel_recommendations,
        name="control_recommendations",
    ),
    path(
        "administracja/rekomendacje/<int:idea_id>/",
        control_views.panel_recommendation_form,
        name="control_recommendation_edit",
    ),
    path(
        "administracja/rekomendacje/<int:idea_id>/wygeneruj/",
        control_views.panel_recommendation_regenerate,
        name="control_recommendation_regenerate",
    ),
    path(
        "administracja/wskazniki-innowacji/",
        control_views.panel_indicators,
        name="control_indicators",
    ),
    path(
        "administracja/wskazniki-innowacji/dodaj/",
        control_views.panel_indicator_form,
        name="control_indicator_add",
    ),
    path(
        "administracja/wskazniki-innowacji/konfiguracja/",
        control_views.panel_indicator_configuration_update,
        name="control_indicator_configuration_update",
    ),
    path(
        "administracja/wskazniki-innowacji/<int:indicator_id>/",
        control_views.panel_indicator_form,
        name="control_indicator_edit",
    ),
    path(
        "administracja/wskazniki-innowacji/<int:indicator_id>/usun/",
        control_views.panel_indicator_delete,
        name="control_indicator_delete",
    ),
    path(
        "administracja/wskazniki-innowacji/<int:indicator_id>/przesun/<str:direction>/",
        control_views.panel_indicator_move,
        name="control_indicator_move",
    ),
    path(
        "administracja/prompty/kalibracja/zapisz/",
        control_views.panel_calibration_update,
        name="control_calibration_update",
    ),
    path(
        "administracja/prompty/kalibracja/przyklady/dodaj/",
        control_views.panel_calibration_example_add,
        name="control_calibration_example_add",
    ),
    path(
        "administracja/prompty/kalibracja/przyklady/<int:example_id>/zapisz/",
        control_views.panel_calibration_example_update,
        name="control_calibration_example_update",
    ),
    path(
        "administracja/prompty/kalibracja/przyklady/<int:example_id>/usun/",
        control_views.panel_calibration_example_delete,
        name="control_calibration_example_delete",
    ),
    path(
        "administracja/prompty/<str:prompt_key>/zapisz/",
        control_views.panel_prompt_update,
        name="control_prompt_update",
    ),
    path(
        "administracja/instytucje/", control_views.panel_institutions, name="control_institutions"
    ),
    path(
        "administracja/instytucje/dodaj/",
        control_views.panel_institution_form,
        name="control_institution_add",
    ),
    path(
        "administracja/instytucje/<int:institution_id>/",
        control_views.panel_institution_form,
        name="control_institution_edit",
    ),
    path(
        "administracja/instytucje/<int:institution_id>/usun/",
        control_views.panel_institution_delete,
        name="control_institution_delete",
    ),
    path(
        "administracja/instytucje/import-csv/",
        control_views.panel_institutions_csv,
        name="control_institutions_csv",
    ),
    path("administracja/partnerzy/", control_views.panel_partners, name="control_partners"),
    path(
        "administracja/partnerzy/dodaj/",
        control_views.panel_partner_form,
        name="control_partner_add",
    ),
    path(
        "administracja/partnerzy/import-csv/",
        control_views.panel_partners_csv,
        name="control_partners_csv",
    ),
    path(
        "administracja/partnerzy/<int:partner_id>/",
        control_views.panel_partner_form,
        name="control_partner_edit",
    ),
    path(
        "administracja/partnerzy/<int:partner_id>/usun/",
        control_views.panel_partner_delete,
        name="control_partner_delete",
    ),
    path("administracja/crawling/", control_views.panel_crawling, name="control_crawling"),
    path(
        "administracja/crawling/harmonogram/",
        control_views.panel_crawling_schedule,
        name="control_crawling_schedule",
    ),
    path(
        "administracja/crawling/zatrzymaj/",
        control_views.panel_crawling_stop,
        name="control_crawling_stop",
    ),
    path(
        "administracja/crawling/status/",
        control_views.panel_crawling_status,
        name="control_crawling_status",
    ),
    path(
        "administracja/crawling/ncbr/",
        control_views.panel_ncbr_crawling,
        name="control_ncbr_crawling",
    ),
    path(
        "administracja/crawling/ncbr/status/",
        control_views.panel_ncbr_crawling_status,
        name="control_ncbr_crawling_status",
    ),
    path(
        "favicon.ico",
        RedirectView.as_view(
            url=f"{settings.STATIC_URL}core/images/innoradar-logo.svg",
            permanent=False,
        ),
    ),
    path(
        ".well-known/appspecific/com.chrome.devtools.json",
        api_views.chrome_devtools_config,
        name="chrome_devtools_config",
    ),
    path("", page_views.home, name="home"),
    path("innowacje/", page_views.innovations, name="innovations"),
    path(
        "zgloszone-innowacje/",
        page_views.submitted_innovations,
        name="submitted_innovations",
    ),
    path("innowacje/<int:idea_id>/", page_views.innovation_detail, name="innovation_detail"),
    path("mapa-innowacji/", page_views.innovation_map, name="innovation_map"),
    path("zglos-pomysl/", page_views.submit_idea, name="submit_idea"),
    path("prywatnosc/", page_views.privacy, name="privacy"),
    path("api/miejscowosci/", api_views.locality_search, name="locality_search"),
    path("api/mapa-innowacji/", api_views.innovation_map_data, name="innovation_map_data"),
    path(
        "api/mapa-innowacji/granica/",
        geojson_views.podkarpackie_boundary,
        name="podkarpackie_boundary",
    ),
    path(
        "api/mapa-innowacji/granica-polski/",
        geojson_views.poland_boundary,
        name="poland_boundary",
    ),
    path(
        "api/mapa-innowacji/powiaty/",
        geojson_views.podkarpackie_counties,
        name="podkarpackie_counties",
    ),
]
