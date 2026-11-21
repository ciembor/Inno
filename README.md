# Innoradar

Aplikacja Django do zgłaszania i oceny lokalnych inicjatyw.

Szczegółowy opis stosowanych zabezpieczeń i prywatności znajduje się w
[SECURITY.md](SECURITY.md).

## Instalacja i uruchomienie

Do scoringu oraz importu aktualności potrzebny jest `OPENAI_API_KEY`. Zgłoszenia
i przeglądanie aplikacji działają również bez niego. Klucz ustaw w terminalu:

```bash
export OPENAI_API_KEY="..."
```

Możesz też zapisać go w lokalnym `.env`; Docker Compose wczyta ten plik
automatycznie. Nie dodawaj klucza do repozytorium.

### Docker Compose

Wymagany jest Docker Desktop. Z katalogu projektu uruchom:

```bash
docker compose up --build
```

To uruchamia serwer Django, workera Celery, harmonogram Celery Beat i Redisa, wykonuje migracje oraz
tworzy lokalne konto administracyjne. Otwórz [http://localhost:8000](http://localhost:8000).
Kontenery mają automatyczne przeładowywanie po zmianie kodu.

### Bez Dockera

Wymagane są Python 3.14+, Redis oraz trzy terminale. Zainstaluj zależności i
przygotuj lokalną bazę SQLite:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python manage.py migrate
python manage.py bootstrap_admin
```

W pierwszym terminalu uruchom Redisa:

```bash
redis-server
```

W drugim terminalu, z aktywnym środowiskiem `.venv`, uruchom workera:

```bash
celery -A config worker --loglevel=INFO
```

W trzecim terminalu uruchom harmonogram, który automatycznie wznawia crawling
po restarcie workera lub przekroczeniu limitu zadania:

```bash
celery -A config beat --loglevel=INFO
```

W trzecim terminalu uruchom Django:

```bash
python manage.py runserver
```

Otwórz [http://localhost:8000](http://localhost:8000). Domyślne adresy Redisa
to `redis://127.0.0.1:6379/0`; możesz je zmienić zmiennymi
`CELERY_BROKER_URL` i `CELERY_RESULT_BACKEND`.

## Usługi

| Usługa | Rola |
| --- | --- |
| `web` | Django dostępne pod portem `8000` |
| `worker` | Celery wykonujący zadania w tle, w tym scoring inicjatyw |
| `beat` | Harmonogram wznawiający przerwane przebiegi crawlera |
| `redis` | broker i backend wyników dla Celery |

## Przydatne polecenia

```bash
# uruchomienie w tle
docker compose up --build -d

# logi workera
docker compose logs -f worker

# zatrzymanie kontenerów
docker compose down

# zatrzymanie razem z danymi Redisa
docker compose down --volumes
```

## Import innowacji z aktualności

Importer pobiera strony aktualności, wybiera artykuły mogące opisywać innowacje,
wydobywa z nich nazwę, opis i datę publikacji, a następnie zleca ocenę LLM.
Każdy przebieg trafia do tabeli `InstitutionImportRun`: zapisuje czas rozpoczęcia
i zakończenia, status, liczbę przetworzonych instytucji, liczbę dodanych i
pominiętych inicjatyw oraz tempo w instytucjach na minutę.

```bash
# jeden typ instytucji
docker compose exec web python manage.py import_institution_innovations \
  --institution-type university

# wszystkie typy: uczelnie, szkoły i samorządy
docker compose exec web python manage.py import_institution_innovations --all-types

# wznowienie jednego typu po znanej instytucji
docker compose exec web python manage.py import_institution_innovations \
  --institution-type school --start-after-id 147
```

`--start-after-id` działa dla jednego typu instytucji; nie należy łączyć go z
`--all-types`. W razie ręcznego zatrzymania ostatni zapisany rekord `Idea` i
`InstitutionImportRun` są checkpointem do wznowienia. Import jest idempotentny
po URL-u źródłowego artykułu i kanonicznej nazwie inicjatywy.

### Projekty NCBR

Niezależny importer czyta publiczną wyszukiwarkę sukcesów beneficjentów NCBR,
zapisuje projekty z całej Polski wraz z ich źródłem oraz
zleca standardową ocenę AI. Nie zastępuje on crawlera aktualności instytucji;
jest dodatkowym źródłem discovery. Import jest idempotentny po adresie projektu.

```bash
# podgląd liczby projektów bez zapisu
docker compose exec web python manage.py import_ncbr_projects --dry-run

# zapis nowych projektów i zlecenie ich oceny workerowi
docker compose exec web python manage.py import_ncbr_projects
```

### Jednorazowe tagowanie istniejących inicjatyw

Importer zapisuje tagi podobieństwa dla nowych rekordów. Po wdrożeniu funkcji
oznacz wcześniej zapisane inicjatywy — polecenie pomija już otagowane rekordy,
więc można je bezpiecznie wznowić po błędzie API:

```bash
# lokalnie
python manage.py tag_idea_similarity

# w Dockerze
docker compose exec web python manage.py tag_idea_similarity

# ponowne oznaczenie wszystkich rekordów albo mała partia testowa
docker compose exec web python manage.py tag_idea_similarity --all
docker compose exec web python manage.py tag_idea_similarity --limit 10
```

### Zmierzony przebieg lokalny

| Etap | Instytucje | Dodane inicjatywy | Czas aktywnej pracy | Tempo |
| --- | ---: | ---: | ---: | ---: |
| Uczelnie i szkoły do checkpointu | 123 | 80 | 1 h 20 min 09 s | 1,5 instytucji/min |
| Szkoły po checkpointcie | 93 | 12 | 30 min 30 s | 3,1 instytucji/min |
| Samorządy | 182 | 37 | 56 min 04 s | 3,2 instytucji/min |

Łącznie lokalny import zapisał 129 inicjatyw. Czas zależy przede wszystkim od
responsywności stron źródłowych i odpowiedzi API LLM; część źródeł może zostać
pominięta z powodu błędów SSL, 404 albo timeoutu. Nie są one traktowane jako
błąd całego joba.

Klucz `OPENAI_API_KEY` nie jest zapisany w repozytorium. Na wdrożeniu należy
dostarczyć go jako zmienną środowiskową.

Plik `docker-compose.yml` jest przeznaczony dla środowiska lokalnego. Serwer
produkcyjny nie ma zainstalowanego Dockera i używa istniejącego na nim modelu
wdrożeń: systemd za Nginxem.

## Wdrożenie produkcyjne

Aplikacja jest przygotowana do pracy pod adresem
`https://maciej-ciemborowicz.eu/inno/`. Na serwerze działa jako dwie
usługi systemd (`innoradar-web`, `innoradar-worker` i `innoradar-beat`), a Nginx obsługuje
statyczne pliki i przekazuje ruch do Gunicorna.

Z komputera deweloperskiego uruchom:

```bash
./scripts/deploy-production.sh
```

Skrypt uruchamia quality gate, synchronizuje kod do
`/home/ciembor/innoradar`, instaluje brakujący Redis, tworzy środowisko Python,
wykonuje migracje i `collectstatic`, a następnie instaluje konfigurację Nginx
oraz usługi systemd. Przy pierwszym wdrożeniu tworzy też plik
`/home/ciembor/innoradar/.env`, zachowując go przy następnych wdrożeniach.
Jeśli istnieje `/home/ciembor/prodietai/.env`, wykorzystuje z niego wyłącznie
`OPENAI_API_KEY`; w przeciwnym razie należy wpisać klucz ręcznie w nowym pliku
`.env`. Wzór ustawień jest w `.env.production.example`.

## Badanie zgodności kolejności ocen

Zatrzymany przebieg pełnego rankingu zachowano w `RankingRun` jako materiał
eksploracyjny. Do oceny wcześniejszych punktacji służy ograniczone badanie:

```bash
docker compose exec web python manage.py study_scoring_order
docker compose exec web python manage.py study_scoring_order --status ID
docker compose exec web python manage.py study_scoring_order --pause ID
docker compose exec web python manage.py study_scoring_order --resume ID
```

Próba jest ustalana i zapisywana przed wywołaniami API. Dla każdego z czterech
kryteriów losujemy po 15 różnych par z czterech warstw różnicy wcześniejszych
ocen: remis (0), mała (1–5), średnia (6–15), duża (16+). Łącznie to **240
porównań**; polecenie nie pozwala przekroczyć 15 par na warstwę. Wcześniejsze
90 par dobranych adaptacyjnie wykluczamy z tej próby. Stałe ziarno losowania
pozwala odtworzyć dobór. Pozycja A/B wcześniejszego lidera jest zrównoważona,
a model nie widzi starych punktacji. Projekty mogą pojawić się w wielu parach;
każda para ma jednakowe prawdopodobieństwo wyboru w swojej warstwie.

Odpowiedzi `A`, `B`, `tie`, `unclear` i uzasadnienia trafiają do `ScoringOrderPair`.
`unclear` jest wynikiem nierozstrzygniętej pary, nie wyklucza żadnej inicjatywy.
Job zapisuje wynik po każdym wywołaniu, respektuje pauzę i może być wznowiony.
Timeout API jest automatycznie ponawiany bez limitu prób, z odstępem od 10 sekund
do 5 minut. Inne błędy zatrzymują badanie do ręcznego wznowienia.
Raport `--status` pokazuje zgodność osobno dla kryteriów i warstw; remisy
wcześniejszej oceny są raportowane osobno. To test **spójności modelu**, a nie
niezależna weryfikacja prawdziwej innowacyjności. Nowe badanie nie zmienia
punktacji inicjatyw ani nie uruchamia pełnego rankingu.

### Kolejność według wyniku końcowego

```bash
docker compose exec web python manage.py study_overall_order
docker compose exec web python manage.py study_overall_order --status ID
docker compose exec web python manage.py study_overall_order --pause ID
docker compose exec web python manage.py study_overall_order --resume ID
```

Badanie losuje 60 różnych par z każdego z trzech zakresów różnicy wyniku
końcowego: 0,1–5,0; 5,1–15,0 oraz ponad 15,0 punktów. Do 180 par dodaje 20
powtórek z zamienioną kolejnością A/B (odpowiednio 7, 7 i 6 z trzech warstw).
Remisy końcowych ocen nie należą do próby. Model nie widzi wcześniejszych
punktów; otrzymuje opisy, cztery kryteria i wagi 30/30/20/20. Każda odpowiedź
jest zapisywana osobno, więc wznowienie nie powtarza zapisanych wywołań API.
Timeout API jest ponawiany automatycznie od tej samej niezapisanej pary;
ponowienia mogą oznaczać dodatkowe koszty API.
Raport pokazuje zgodność kolejności w każdej warstwie oraz stabilność odwróconych
powtórek. Badanie niczego nie przelicza w tabeli innowacji i nie jest niezależną
oceną ekspercką.

### Wyniki lokalnych badań porównawczych

Poniższe wyniki pochodzą z ukończonych lokalnych badań nr 1. Są testem
**spójności kolejności ocen**: model porównuje dwie anonimowe inicjatywy bez
wglądu w ich wcześniejsze wyniki. Nie potwierdzają obiektywnej jakości ani
prawdziwości innowacyjności projektów.

#### Cztery kryteria — 240 porównań

W każdej komórce podano zgodność kolejności w parach rozstrzygniętych przez
model; pominięto odpowiedzi `tie` i `unclear`. Próba obejmowała po 15 par dla
każdego kryterium i każdej warstwy różnicy wcześniejszej punktacji.

| Kryterium | Różnica 1–5 | Różnica 6–15 | Różnica ponad 15 | Łącznie |
| --- | ---: | ---: | ---: | ---: |
| Nowatorstwo | 8/12 — 66,7% | 10/13 — 76,9% | 13/15 — 86,7% | 31/40 — 77,5% |
| Wartość | 5/11 — 45,5% | 11/12 — 91,7% | 14/15 — 93,3% | 30/38 — 78,9% |
| Replikowalność | 8/15 — 53,3% | 9/15 — 60,0% | 12/15 — 80,0% | 29/45 — 64,4% |
| Oddziaływanie | 8/15 — 53,3% | 13/15 — 86,7% | 15/15 — 100,0% | 36/45 — 80,0% |

W warstwie remisów model zwykle rozróżniał projekty zamiast zachowywać poprzedni
remis: zachował 2 z 15 remisów dla nowatorstwa i wartości, a dla
replikowalności oraz oddziaływania rozstrzygnął wszystkie 15. Dlatego remisy są
raportowane osobno i nie wchodzą do wskaźników w tabeli.

#### Wynik końcowy — 200 porównań

Badanie wyniku końcowego obejmowało 180 różnych par oraz 20 powtórek z
odwróconą kolejnością A/B. Model otrzymywał opisy inicjatyw, cztery kryteria i
wagi 30/30/20/20, lecz nie wcześniejsze punktacje.

| Różnica wcześniejszego wyniku końcowego | Zgodność kolejności |
| --- | ---: |
| 0,1–5,0 punktów | 38/60 — 63,3% |
| 5,1–15,0 punktów | 48/60 — 80,0% |
| Ponad 15,0 punktów | 57/60 — 95,0% |
| Łącznie | 143/180 — 79,4% |

Odwrócone powtórki dały zgodny werdykt w 18 z 20 przypadków (90,0%). Wyniki
wskazują, że większe różnice punktów są znacznie stabilniejsze niż różnice
kilkupunktowe; rankingu nie należy traktować jak precyzyjnej kolejności dla
niemal równych projektów.

## Kalibracja oceny innowacji

Kalibracją i wszystkimi promptami zarządza panel **Administracja**. Przykłady
kalibracyjne można włączać, dodawać, edytować i usuwać bez zmiany kodu; aktywna
kalibracja jest pobierana z bazy przy każdym ocenianiu.

Plik `core/data/scoring_calibration.json` jest wyłącznie materiałem startowym dla
migracji `0025_scoring_calibration_models.py`, która zasila nową, pustą bazę.
Nie edytuj go, aby zmienić działającą konfigurację.

## Panel administracyjny

Panel: http://localhost:8000/admin/ — startowy login `admin`, hasło `admin`.
Konto tworzy przy starcie Dockera polecenie `python manage.py bootstrap_admin`.
Nie nadpisuje istniejącego konta ani zmienionego hasła. Hasło zmienia się przez
„Zmień hasło” w górnym pasku panelu.

Lista instytucji umożliwia edycję danych, wybór miejscowości oraz dodawanie
i usuwanie dodatkowych stron aktualności. Importer czyta główny adres i dodatkowe źródła.
Przycisk „Import CSV” przyjmuje UTF-8 (także BOM), przecinki lub średniki:

```csv
name,address,institution_type,locality_simc,news_url,additional_news_urls
Przykładowa uczelnia,Rzeszów,university,0974133,https://example.org/news,https://example.org/research|https://example.org/projects
```

Nazwa i adres identyfikują instytucję: kolejne importy aktualizują jej dane,
a dodatkowe linki dopisują bez duplikatów. Kolumna `additional_news_urls` jest
opcjonalna. Pozostałe są wymagane; SIMC musi istnieć w bazie miejscowości.
Błędny wiersz wycofuje cały import. CSV nie uruchamia pobierania artykułów.

### Organizacje pozarządowe

Formularze oraz panel administracyjny korzystają z pełnego, urzędowego słownika
SIMC dla całej Polski. Aby odświeżyć słownik, uruchom:

```bash
python manage.py import_polish_localities
```

Wyszukiwarka miejscowości podaje województwo, a dla Podkarpacia również powiat.

Referencyjny plik `organizacje_innowacje_aktualnosci.csv` zawiera organizacje,
zweryfikowane strony ich aktualności oraz przykładowe artykuły. Polecenie pobiera
wyłącznie wskazane miejscowości z urzędowego rejestru SIMC GUS, przypisuje im
współrzędne i zapisuje organizacje jako typ „Inne instytucje”. Nie zapisuje
pojedynczych artykułów jako źródeł, więc kolejne crawlingi wykrywają także nowe
publikacje tych organizacji.

```bash
docker compose exec web python manage.py import_ngo_sources organizacje_innowacje_aktualnosci.csv
```

Do pracy bez dostępu do GUS można przekazać uprzednio pobrane archiwum:

```bash
python manage.py import_ngo_sources organizacje_innowacje_aktualnosci.csv --simc-archive /ścieżka/SIMC.zip
```

## Bezpieczeństwo i operacje

Strona `/prywatnosc/` opisuje zakres danych zgłoszenia, 12-miesięczną retencję
danych kontaktowych oraz procedurę żądania usunięcia. Formularz wymaga
potwierdzenia zapoznania się z tą informacją. Próby logowania i wysyłki są
limitowane do pięciu w 15 minut z jednego adresu IP. Produkcja wymusza zmianę
domyślnego hasła `admin/admin` przed użyciem panelu.

Wdrożenie dodaje CSP z nonce dla skryptów osadzonych, HSTS, ochronę przed
sniffingiem MIME, politykę referrera oraz blokadę osadzania strony w ramce.
Adres kontaktowy prywatności ustaw przez `PRIVACY_CONTACT_EMAIL`.

### Backup i odtworzenie

Na serwerze zatrzymaj na chwilę web i worker, wykonaj spójny backup SQLite,
uruchom usługi ponownie, a plik przechowuj poza serwerem:

```bash
sudo systemctl stop innoradar-web innoradar-worker
sqlite3 /home/ciembor/innoradar/data/db.sqlite3 ".backup '/home/ciembor/backups/innoradar-$(date +%F).sqlite3'"
sudo systemctl start innoradar-web innoradar-worker
```

Aby odtworzyć dane, zatrzymaj te same usługi, zachowaj kopię bieżącego pliku,
skopiuj wybrany backup do `data/db.sqlite3`, ustaw właściciela `ciembor` i
ponownie uruchom usługi. Przed odtworzeniem wykonaj próbę na kopii środowiska.

Monitoring procesu: `sudo systemctl status innoradar-web innoradar-worker
innoradar-beat`, a bieżące logi: `journalctl -fu innoradar-worker`. Stan
crawlera, tempo i ostatnie zdarzenia są również widoczne w panelu
**Administracja → Crawling**.
