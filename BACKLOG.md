# Backlog Innoradaru

Plan prowadzi do kompletnego demonstratora dla wyzwania „Radar innowacji”.
Priorytety odpowiadają pięciu równoważnym kryteriom oceny konkursowej.

## M0 — Stabilna baza demonstratora

**Status:** w dużej części gotowe.

- [x] Crawler aktualności szkół, uczelni i samorządów.
- [x] Ręczne zgłoszenie pomysłu.
- [x] Ocena LLM z uzasadnieniami, wagami i kalibracją.
- [x] Lista, szczegóły, mapa i panel administracyjny.
- [x] Import CSV, harmonogram, retry, monitoring joba i wdrożenie.
- [x] Testy, quality gate oraz pełne pokrycie testami.
- [ ] Ujednolicić dynamiczne wskaźniki w sortowaniu, badaniach kolejności i
  instrukcji oceny LLM.
- [ ] Dodać konfigurowalną skalę 0–100 do każdego wskaźnika.
- [ ] Usunąć historyczne, statyczne definicje po migracji narzędzi.

**Kryterium odbioru:** piąty wskaźnik dodany w panelu można skonfigurować,
skalibrować, wykorzystać w ocenie, wyświetlić, sortować po nim i objąć badaniem
bez zmiany kodu.

## M1 — Rekomendacja dalszego kroku

**Cel:** odpowiedzieć na pytanie „co dalej z tą innowacją?”.

- [x] Dodać model `DevelopmentRecommendation` dla inicjatywy.
- [x] Generować po ocenie: etap rozwoju, ścieżkę, najbliższy krok,
  uzasadnienie i ryzyko/niewiadomą.
- [x] Obsłużyć ścieżki: pilotaż, transfer, partnerstwo, finansowanie,
  komercjalizacja i wdrożenie.
- [x] Pokazać rekomendację na stronie szczegółu.
- [x] Umożliwić korektę, ponowne wygenerowanie i zatwierdzenie w panelu.
- [x] Dodać edytowalny prompt, schemat odpowiedzi i testy.

**Kryterium odbioru:** dla dwóch demonstracyjnych inicjatyw system pokazuje
inną, rzeczową ścieżkę rozwoju, uzasadnienie i konkretny kolejny krok. **Do
domknięcia:** wskazać oraz zapisać drugi demonstracyjny przykład.

## M2 — Partnerzy, użytkownicy i transfer

**Cel:** połączyć inicjatywę z organizacją, która może ją wdrożyć, rozwinąć
albo finansować.

- [x] Dodać model `PartnerOrganization`: nazwa, typ, opis, kontakt,
  miejscowość, obszary działania, możliwości wsparcia i status aktywności.
- [x] Obsłużyć typy: użytkownik rozwiązania, partner wdrożeniowy, ekspert,
  finansujący/program wsparcia.
- [x] Dodać CRUD oraz import partnerów z CSV.
- [x] Dodać tagi potrzeb inicjatywy i możliwości partnera.
- [x] Zbudować dopasowanie po tagach wraz z uzasadnieniem.
- [x] Pokazać na szczegółach 3–5 rekomendowanych partnerów i kontakt.
- [x] Przygotować małą, opisaną bazę demonstracyjną partnerów.

**Kryterium odbioru:** demonstrator pokazuje inicjatywę, rekomendowaną ścieżkę
oraz minimum trzy sensowne organizacje, którym można ją przekazać. **Gotowe
lokalnie:** przykłady demonstracyjne są skonfigurowane dla inicjatyw `465` i
`495`.

## M3 — Podobne rozwiązania i ograniczanie dublowania

**Cel:** wykrywać pokrewne inicjatywy przed rozpoczęciem pracy od zera.

- [x] Rozszerzyć ekstrakcję LLM o tagi: problem, odbiorcy, branża, mechanizm,
  typ rozwiązania, etap i obszar terytorialny.
- [x] Zapisać tagi dla istniejących i nowych inicjatyw. Nowe rekordy są tagowane
  podczas importu lub po ocenie zgłoszenia; historyczne rekordy zostały
  jednorazowo domknięte na produkcji poleceniem `tag_idea_similarity` (576/576).
- [x] Zaimplementować ranking podobieństwa na podstawie wspólnych tagów.
- [x] Oznaczać relację: dublowanie, adaptacja, uzupełnienie lub współpraca.
- [x] Pokazać podobne inicjatywy i wyjaśnienie relacji na stronie szczegółu.
- [x] Zachować deduplikację po URL-u i nazwie jako pierwszy filtr.

**Kryterium odbioru:** dla dwóch podobnych inicjatyw system pokazuje relację
i wyjaśnia, czy powinny współpracować, czy jedna może wykorzystać drugą.

## M4 — Kompletne dane i przejrzystość pochodzenia

**Cel:** pokazać, kto stworzył inicjatywę, skąd pochodzi opis i czego system nie wie.

- [x] Rozdzielić dane zgłaszającego, twórcy/zespołu, instytucji źródłowej,
  instytucji wdrażającej i kontaktu.
- [x] Zapisywać oraz wyświetlać rolę instytucji: twórca, współtwórca,
  lokalny adaptator, relacja zewnętrzna lub niepewna.
- [ ] Pokazywać datę, adres źródłowy i status wiarygodności danych.
- [ ] Dodać status kompletności rekordu i listę brakujących informacji.
- [x] Umożliwić administratorowi ręczne uzupełnienie twórców i kontaktów.

**Kryterium odbioru:** szczegóły inicjatywy jasno pokazują źródło, rolę instytucji,
twórcę lub kontakt (jeśli udostępniony), etap oraz brakujące dane.

## M5 — Bezpieczeństwo, prywatność i gotowość wdrożeniowa

**Cel:** przygotować projekt do wiarygodnego użycia poza hackathonem.

- [x] Dodać politykę prywatności i informację RODO przy zgłoszeniu.
- [x] Dodać potwierdzenie zapoznania się z przetwarzaniem danych.
- [x] Określić retencję danych i możliwość usunięcia zgłoszenia.
- [x] Dodać limitowanie prób logowania oraz ochronę formularza przed spamem.
- [x] Dodać CSP, HSTS, `X-Content-Type-Options` i `Referrer-Policy`.
- [x] Wymusić zmianę domyślnego hasła administracyjnego przy pierwszym wdrożeniu.
- [x] Udokumentować backup bazy, odtwarzanie i monitoring workera/crawlera.
- [ ] Rozważyć PostgreSQL jako bazę docelową dla wdrożenia wieloużytkownikowego.

**Kryterium odbioru:** osoba oceniająca znajduje zasady danych i instrukcję
bezpiecznego wdrożenia bez czytania kodu.

## M6 — Integracje, mierniki i skalowanie

**Cel:** udowodnić, że rozwiązanie może być użyte przez wiele organizacji.

- [x] Udostępnić eksport CSV inicjatyw, ocen, rekomendacji i dopasowań.
- [x] Udostępnić udokumentowane API JSON tylko do odczytu.
- [x] Dodać panel metryk: instytucje, źródła, artykuły, inicjatywy, duplikaty,
  oceny, rekomendacje, dopasowania i średni czas przetworzenia.
- [ ] Dodać konfigurację regionu, typów instytucji i źródeł bez zmian w kodzie.
- [ ] Opisać koszt, limity i ograniczenia wywołań LLM.
- [x] Dodać stronę „O projekcie” z opisem danych, AI, kryteriów, ograniczeń,
  bezpieczeństwa, skalowania i integracji.

**Kryterium odbioru:** administrator eksportuje dane, integruje odczyt przez API
i ocenia skuteczność bez dostępu do bazy danych.

## M7 — Walidacja i materiały konkursowe

**Cel:** dostarczyć komplet wymaganych materiałów i jasną historię demo.

- [ ] Wybrać dwa realne, różne przypadki demonstracyjne z bazy.
- [ ] Zapisać dla każdego scenariusz: wykrycie/zgłoszenie, uporządkowanie,
  ocena, rekomendacja, podobne rozwiązania i partnerzy.
- [ ] Zdefiniować mierniki sukcesu demonstracji oraz podać wyniki.
- [ ] Przygotować prezentację PDF do 10 slajdów.
- [ ] Przygotować film do 3 minut w otwartym repozytorium/linku.
- [ ] Udostępnić link do demonstratora i repozytorium kodu.
- [ ] Przygotować plan awaryjny: konto testowe, zrzuty ekranu i demo bez API.

**Kryterium odbioru:** niezależna osoba przechodzi dwa scenariusze w kilka minut,
a prezentacja oraz film pokazują wszystkie pięć kryteriów oceny.

## Kolejność realizacji

| Kolejność | Milestone | Główny wpływ na ocenę |
| ---: | --- | --- |
| 1 | M1 — rekomendacje dalszego kroku | Związek z wyzwaniem, kompletność |
| 2 | M2 — partnerzy i transfer | Związek z wyzwaniem, wdrażalność |
| 3 | M3 — podobne rozwiązania | Oryginalność, użyteczność |
| 4 | M4 — kompletność danych | Użyteczność, wiarygodność |
| 5 | M0 — dynamiczne wskaźniki | Jakość i utrzymywalność |
| 6 | M5 — prywatność i bezpieczeństwo | Gotowość wdrożeniowa |
| 7 | M6 — eksport, API i metryki | Skalowalność |
| 8 | M7 — walidacja i materiały | Wymogi formalne i prezentacja |

## Definition of Done

- Funkcja ma widoczne kryterium odbioru dla użytkownika.
- Jest objęta testami jednostkowymi i integracyjnymi.
- Obsługuje błędy, pusty stan i klawiaturę.
- Działa w domyślnym i obu wysokokontrastowych trybach.
- Nie ujawnia danych osobowych bez uzasadnienia lub zgody.
- Po zmianie przechodzi `make quality` z pełnym pokryciem testów.
