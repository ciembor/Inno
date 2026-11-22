# Innoradar API v1

Publiczne API Innoradaru udostępnia dane katalogu w formacie JSON. Jest wyłącznie do odczytu: nie wymaga logowania i nie obsługuje operacji zapisu.

Adres bazowy produkcji: `https://maciej-ciemborowicz.eu/inno/api/`

Dokumentacja dostępna w przeglądarce: [maciej-ciemborowicz.eu/inno/api/dokumentacja/](https://maciej-ciemborowicz.eu/inno/api/dokumentacja/)

API nie udostępnia danych osób zgłaszających ani prywatnych danych kontaktowych.

## Szybki start

```bash
curl 'https://maciej-ciemborowicz.eu/inno/api/innowacje/?page=1&page_size=20'
```

Wszystkie odpowiedzi mają nagłówek `Content-Type: application/json`. Adresy względne w polach `url`, `api_url`, `next` i `previous` należy połączyć z domeną demonstratora, np. `https://maciej-ciemborowicz.eu` + `/inno/api/innowacje/42/`.

## `GET /api/`

Zwraca opis wersji API i listę głównych zasobów.

```json
{
  "title": "Innoradar API",
  "version": "v1",
  "read_only": true,
  "privacy": "API nie udostępnia danych zgłaszających ani prywatnych kontaktów.",
  "endpoints": []
}
```

## `GET /api/innowacje/`

Zwraca stronicowaną listę publicznych innowacji. Rekordy są ułożone malejąco według wyniku oceny, a następnie daty dodania.

| Parametr | Wymagany | Wartość domyślna | Opis |
| --- | --- | --- | --- |
| `page` | nie | `1` | Numer strony; wartości mniejsze od 1 i niepoprawne są zastępowane przez `1`. |
| `page_size` | nie | `20` | Liczba rekordów na stronie, od `1` do `50`. |

Przykład:

```bash
curl 'https://maciej-ciemborowicz.eu/inno/api/innowacje/?page=1&page_size=2'
```

```json
{
  "count": 574,
  "page": 1,
  "page_size": 2,
  "next": "/inno/api/innowacje/?page=2&page_size=2",
  "previous": null,
  "results": [
    {
      "id": 931,
      "name": "Nazwa innowacji",
      "url": "/inno/innowacje/931/",
      "api_url": "/inno/api/innowacje/931/",
      "score": 54.6,
      "locality": "Rzeszów",
      "institution": "Nazwa instytucji",
      "published_at": "2026-11-21T12:00:00+00:00",
      "added_at": "2026-11-21T16:16:36.710869+00:00"
    }
  ]
}
```

Pole `score`, `locality`, `institution` lub `published_at` może mieć wartość `null`, jeśli nie została ustalona w materiale źródłowym.

## `GET /api/innowacje/{id}/`

Zwraca pełne publiczne dane jednej innowacji. `id` jest identyfikatorem z listy `results`.

Przykład:

```bash
curl 'https://maciej-ciemborowicz.eu/inno/api/innowacje/931/'
```

Odpowiedź rozszerza pola z listy o:

| Pole | Znaczenie |
| --- | --- |
| `content` | Publiczny opis inicjatywy. |
| `source` | Etykieta oraz URL materiału źródłowego. |
| `institution_role` | Rola instytucji powiązanej z inicjatywą. |
| `implementing_institution` | Instytucja wdrażająca, jeżeli została wskazana. |
| `similarity_tags` | Tagi użyte do wyszukiwania podobnych rozwiązań. |
| `assessments` | Oceny kryteriów wraz z uzasadnieniem. |
| `recommendation` | Etap, ścieżka, następny krok, uzasadnienie, ryzyko i status rekomendacji; `null`, gdy jeszcze jej nie wygenerowano. |
| `partners` | Dopasowani partnerzy: nazwa, typ, publiczny kontakt, URL i uzasadnienie dopasowania. |

Przykładowy fragment:

```json
{
  "assessments": [
    {"criterion": "Nowatorstwo", "score": 72, "rationale": "…"}
  ],
  "recommendation": {
    "stage": "Koncepcja",
    "path": "Pilotaż",
    "next_step": "…",
    "rationale": "…",
    "risk": "…",
    "status": "Wygenerowana"
  },
  "partners": []
}
```

Jeżeli innowacja nie istnieje lub nie jest publiczna, API zwraca `404 Not Found`.

## Stabilność i ograniczenia

- Aktualna wersja to `v1`; nowe pola mogą być dodawane bez usuwania istniejących.
- API nie zapewnia operacji tworzenia, edycji ani usuwania danych.
- Wyniki AI i rekomendacje są materiałem pomocniczym; należy je zweryfikować przed podjęciem decyzji.
- Dane źródłowe mogą być niepełne lub nieaktualne. Przy rekordach pobranych automatycznie należy korzystać z pola `source.url`.
