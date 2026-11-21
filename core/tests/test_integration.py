import pytest
from django.urls import reverse

from core.models import Idea, Institution, Locality


def create_locality():
    return Locality.objects.create(
        simc_code="0654321",
        name="Rzeszów",
        voivodeship_code="18",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
        latitude=50.0133,
        longitude=22.0162,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "active_label", "page_heading"),
    [
        ("home", "Start", "Pomysły, które zasługują na szansę."),
        ("submit_idea", "Zgłoś pomysł", "Zgłoś pomysł, który warto dostrzec."),
        ("innovations", "Pobrane innowacje", "Pobrane innowacje."),
        ("submitted_innovations", "Zgłoszone innowacje", "Zgłoszone innowacje."),
        ("innovation_map", "Mapa", "Mapa innowacji Polski"),
    ],
)
def test_public_pages_render_the_shared_layout(client, route_name, active_label, page_heading):
    response = client.get(reverse(route_name))
    content = response.content.decode()

    assert response.status_code == 200
    assert page_heading in content
    assert 'href="#main-content">Przejdź do treści</a>' in content
    assert response.headers["Cache-Control"] == (
        "max-age=0, no-cache, no-store, must-revalidate, private"
    )
    assert 'id="main-content"' in content
    assert 'class="footer"><span>inno</span>radar' in content
    assert f'href="{reverse("privacy")}"' in content
    assert 'href="/static/core/css/base.css?v=2"' in content
    assert f'aria-current="page">{active_label}</a>' in content
    for navigation_label in (
        "Start",
        "Zgłoś pomysł",
        "Pobrane innowacje",
        "Zgłoszone innowacje",
        "Mapa",
    ):
        assert navigation_label in content


@pytest.mark.django_db
def test_home_explains_the_four_innovation_criteria(client):
    content = client.get(reverse("home")).content.decode()

    assert "Szukamy innowacji" in content
    assert "Jak szukamy i oceniamy innowacje?" in content
    assert "Przeszukujemy aktualności instytucji" in content
    assert "Dlaczego oceniamy najlepiej" in content
    assert "Kalibracja i kompleksowość." in content
    assert "Panel administracyjny pozwala zarządzać instytucjami" in content
    for criterion in ("Nowatorstwo", "Wartość", "Replikowalność", "Oddziaływanie"):
        assert criterion in content
    assert "Jedna baza, wiele źródeł." in content
    assert "importować instytucje z plików CSV" in content
    assert "Gotowość do wdrożenia" in content
    assert "WCAG 2.2 AA" in content
    assert "Ruff i Radon" in content
    assert "Dostrzegamy" not in content
    assert 'document.documentElement.classList.add("js")' in content


@pytest.mark.django_db
def test_home_displays_dynamic_institution_counts(client):
    locality = create_locality()
    for institution_type in (
        Institution.Type.SCHOOL,
        Institution.Type.SCHOOL,
        Institution.Type.UNIVERSITY,
        Institution.Type.LOCAL_GOVERNMENT,
        Institution.Type.OTHER,
    ):
        Institution.objects.create(
            name=f"Instytucja {institution_type} {Institution.objects.count()}",
            address="Rzeszów",
            institution_type=institution_type,
            locality=locality,
        )

    content = client.get(reverse("home")).content.decode()

    assert (
        'Liczba obserwowanych instytucji: <span class="examples__total"'
        '>5</span>'
    ) in content
    assert '<strong class="card__count" data-counter data-count="2">2</strong>' in content
    assert content.count('class="card__count" data-counter data-count="1"') == 3
    assert "Uczelnie" in content
    assert "Samorządy" in content
    assert "Inne instytucje" in content
    assert content.index("Uczelnie") < content.index("Szkoły")
    assert "Inicjatywy uczniów" not in content
    assert 'class="card__number"' not in content


@pytest.mark.parametrize(
    ("route_name", "script_name"),
    [
        ("home", "home.js"),
        ("submit_idea", "submit_idea.js"),
        ("innovations", "innovations.js"),
        ("submitted_innovations", "innovations.js"),
        ("innovation_map", "innovation_map.js"),
    ],
)
@pytest.mark.django_db
def test_pages_load_external_page_scripts(client, route_name, script_name):
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    assert f'core/js/{script_name}' in response.content.decode()


@pytest.mark.django_db
def test_dynamic_page_scripts_receive_urls_through_data_attributes(client):
    submission_page = client.get(reverse("submit_idea")).content.decode()
    map_page = client.get(reverse("innovation_map")).content.decode()

    assert f'data-locality-url="{reverse("locality_search")}"' in submission_page
    assert f'data-submit-url="{reverse("submit_idea")}"' in submission_page
    assert f'data-innovations-url="{reverse("innovation_map_data")}"' in map_page
    assert f'data-boundary-url="{reverse("poland_boundary")}"' in map_page


@pytest.mark.django_db
def test_idea_submission_journey_uses_locality_lookup_and_persists_the_idea(client, monkeypatch):
    locality = create_locality()

    suggestions = client.get(reverse("locality_search"), {"q": "Rz"})
    submission = client.post(
        reverse("submit_idea"),
        {
            "name": "Mobilna pracownia nauki",
            "submitter_name": "Anna Kowalska",
            "email": "anna@example.org",
            "locality": locality.pk,
            "content": "<p>Warsztaty dla szkół z regionu.</p>",
            "privacy_accepted": "on",
        },
        HTTP_ACCEPT="application/json",
    )

    assert suggestions.json() == {
        "results": [{"id": locality.pk, "name": "Rzeszów", "county": "powiat Rzeszów"}]
    }
    assert submission.status_code == 201
    assert submission.json()["redirect_url"]
    assert submission.json()["workflow_token"]
    idea = Idea.objects.get(name="Mobilna pracownia nauki")
    assert idea.locality == locality


@pytest.mark.django_db
def test_innovations_page_sorts_and_paginates_scored_ideas(client):
    locality = create_locality()
    for score in range(1, 11):
        Idea.objects.create(
            name=f"Inicjatywa {score}",
            submitter_name="Anna Kowalska",
            email=f"anna{score}@example.org",
            locality=locality,
            content="Treść",
            source_url=f"https://example.org/inicjatywa-{score}",
            innovation_score=score,
            innovation_details={
                "Nowatorstwo": score,
                "Wartość innowacji": score,
                "Replikowalność": score,
                "Potencjał oddziaływania": score,
            },
            innovation_rationales={"Nowatorstwo": "Uzasadnienie oceny."},
        )

    first_page = client.get(reverse("innovations"), {"sort": "score"})
    second_page = client.get(reverse("innovations"), {"sort": "score", "page": 2})
    detail_page = client.get(
        reverse("innovation_detail", args=[first_page.context["page"].object_list[0].pk])
    )

    assert first_page.status_code == 200
    assert detail_page.status_code == 200
    assert "Uzasadnienie oceny." in detail_page.content.decode()
    assert 'data-view="grid"' in first_page.content.decode()
    assert 'data-view="list"' in first_page.content.decode()
    assert "innovations-table" in first_page.content.decode()
    assert "Inicjatywa 10" in first_page.content.decode()
    assert "Inicjatywa 1</h2>" not in first_page.content.decode()
    assert 'rel="next" aria-label="Następna strona">Następna</a>' in first_page.content.decode()
    assert 'aria-disabled="true">Pierwsza</span>' in first_page.content.decode()
    assert '?sort=score&amp;type=&amp;page=2' in first_page.content.decode()
    assert "Inicjatywa 1" in second_page.content.decode()
    assert (
        'rel="prev" aria-label="Poprzednia strona">Poprzednia</a>'
        in second_page.content.decode()
    )


@pytest.mark.django_db
def test_map_page_and_its_json_contract_render_geolocated_idea(client):
    locality = create_locality()
    idea = Idea.objects.create(
        name="Zielony przystanek",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        locality=locality,
        content="Treść",
        innovation_score=82,
    )

    page = client.get(reverse("innovation_map"))
    markers = client.get(reverse("innovation_map_data"))
    boundary = client.get(reverse("poland_boundary"))

    assert "leaflet@1.9.4" in page.content.decode()
    assert 'core/js/innovation_map.js' in page.content.decode()
    assert 'href="/static/core/css/pages/innovation_map.css?v=2"' in page.content.decode()
    assert "innovation-list" not in page.content.decode()
    assert 'class="map-fallback"' in page.content.decode()
    assert (
        "Zielony przystanek</a> — Rzeszów, wynik innowacyjności: 82.0."
        in page.content.decode()
    )
    assert "[[ error ]]" not in page.content.decode()
    assert "<h1>Mapa innowacji Polski</h1>" in page.content.decode()
    assert "Mapa zostanie uzupełniona" not in page.content.decode()
    assert "Mapa jest chwilowo niedostępna" not in page.content.decode()
    assert "<summary>Lista inicjatyw na mapie (1)</summary>" in page.content.decode()
    assert "Inicjatywy zgłoszone z miejscowości" not in page.content.decode()
    assert markers.json()["innovations"] == [
        {
            "id": idea.pk,
            "name": "Zielony przystanek",
            "url": reverse("innovation_detail", args=[idea.pk]),
            "score": 82,
            "locality": "Rzeszów",
            "latitude": 50.0133,
            "longitude": 22.0162,
        }
    ]
    assert boundary.json()["features"][0]["id"] == "POL"
    assert boundary.json()["features"][0]["geometry"]["type"] == "Polygon"
