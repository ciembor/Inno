# Bezpieczeństwo i prywatność Innoradaru

Ten dokument opisuje zabezpieczenia dostępne w aktualnej wersji Innoradaru.
Może służyć jako podstawa opisu projektu, prezentacji lub audytu wdrożenia.

## Najważniejsze wnioski

Innoradar jest przygotowany do bezpiecznego przyjmowania zgłoszeń i pracy
administracyjnej poza środowiskiem hackathonowym. Ochrona nie opiera się na
jednym mechanizmie: obejmuje warstwę aplikacji Django, reverse proxy Nginx,
formularze publiczne, panel administracyjny, cache współdzielony między
procesami oraz udokumentowane procedury operacyjne.

- Dane kontaktowe nie są publikowane wraz z inicjatywą.
- Zgłoszenie wymaga świadomego potwierdzenia polityki prywatności.
- Publiczny formularz i logowanie są chronione przed seryjnymi próbami.
- Panel nie pozwala korzystać z domyślnego hasła `admin/admin` na produkcji.
- Przeglądarka otrzymuje politykę ograniczającą źródła skryptów i osadzanie
  strony w zewnętrznych ramkach.
- Backup, odtworzenie danych i obserwacja pracy crawlera są opisane w repozytorium.

## Dane osobowe i prawa osoby zgłaszającej

Formularz przyjmuje wyłącznie dane niezbędne do obsługi zgłoszenia: imię i
nazwisko, adres e-mail, miejscowość oraz opis inicjatywy. Przed wysłaniem
użytkownik musi potwierdzić zapoznanie się z polityką prywatności.

Polityka prywatności jest dostępna publicznie pod adresem `/prywatnosc/` i
opisuje:

- cel przetwarzania: przyjęcie, analiza i kontakt w sprawie inicjatywy;
- zakres danych i zasady publikacji;
- retencję danych kontaktowych: maksymalnie 12 miesięcy od zakończenia analizy;
- sposób zgłoszenia żądania dostępu, korekty, ograniczenia przetwarzania lub
  usunięcia danych;
- maksymalny termin odpowiedzi: miesiąc.

Adres kontaktowy oraz nazwa administratora danych są konfigurowane poza kodem
przez `PRIVACY_CONTACT_EMAIL` i `PRIVACY_CONTROLLER_NAME`.

## Ochrona formularzy i panelu

### Ograniczanie nadużyć

Wysyłka zgłoszeń oraz błędne logowania są limitowane do pięciu prób w ciągu
15 minut dla jednego adresu IP. Po przekroczeniu limitu aplikacja zwraca `429
Too Many Requests` z nagłówkiem `Retry-After`.

W produkcji licznik korzysta z Redisa, dlatego jest wspólny dla wielu procesów
Gunicorn i nie znika przy zmianie procesu aplikacji. Lokalnie używany jest cache
w pamięci, aby uruchomienie projektu nie wymagało dodatkowej konfiguracji.

### Dostęp administracyjny

CSRF chroni formularze zmieniające stan. Jeśli produkcyjne konto nadal używa
startowego hasła `admin/admin`, zalogowana osoba zostaje skierowana wyłącznie
do strony zmiany danych logowania; pozostały panel pozostaje niedostępny do
chwili ustawienia nowego hasła.

Poza uwierzytelnianiem aplikacji produkcja jest obecnie dodatkowo osłonięta
HTTP Basic Auth skonfigurowanym w Nginxie. To warstwa ograniczająca dostęp do
wersji demonstracyjnej, a nie substytut indywidualnych kont użytkowników.

## Nagłówki i ochrona przeglądarki

Nginx oraz Django wysyłają następujące zabezpieczenia:

| Mechanizm | Zastosowanie |
| --- | --- |
| Content-Security-Policy | Dopuszcza skrypty tylko z własnej domeny, z nonce dla skryptów inline oraz z wymaganych CDN-ów mapy i Vue. `unsafe-eval` jest ograniczonym wyjątkiem wymaganym przez używaną pełną wersję Vue, która kompiluje szablony w przeglądarce. Polityka blokuje obiekty, osadzanie w ramkach i formularze do obcych domen. |
| HSTS | Każe przeglądarce używać HTTPS przez rok, także dla subdomen. |
| `X-Content-Type-Options: nosniff` | Zapobiega zgadywaniu typu treści przez przeglądarkę. |
| `Referrer-Policy: strict-origin-when-cross-origin` | Nie przekazuje pełnej ścieżki adresu do zewnętrznych serwisów. |
| `X-Frame-Options: DENY` / `frame-ancestors 'none'` | Chroni przed osadzaniem aplikacji i clickjackingiem. |
| Secure cookies | W produkcji ciasteczka sesji i CSRF są przesyłane wyłącznie po HTTPS. |

## Operacje i ciągłość działania

Wdrożenie uruchamia oddzielne usługi `innoradar-web`, `innoradar-worker` i
`innoradar-beat` oraz Redisa. Worker i harmonogram są monitorowane przez
systemd; status i logi można sprawdzić poleceniami:

```bash
sudo systemctl status innoradar-web innoradar-worker innoradar-beat
journalctl -fu innoradar-worker
```

Panel administracyjny pokazuje postęp crawlera, ostatnie zdarzenia i stan
automatycznego harmonogramu. Procedura bezpiecznego backupu i odtworzenia bazy
znajduje się w [README.md](README.md#backup-i-odtworzenie).

## Weryfikacja jakości

Każda zmiana jest weryfikowana przez `make quality`, które uruchamia:

- linting Ruff;
- analizę złożoności Radon;
- kontrolę składni i formatowania JavaScriptu;
- testy jednostkowe oraz integracyjne z wymaganym 100% pokryciem kodu.

Po wdrożeniu M5 quality gate zakończył się powodzeniem: **284 testy i 100%
pokrycia**.

## Uczciwe ograniczenia

Projekt nie jest jeszcze pełnym systemem IAM ani certyfikowanym rozwiązaniem
do przetwarzania danych wrażliwych. Produkcyjny administrator musi ustawić
prawdziwe dane kontaktowe w zmiennych środowiskowych, bezpiecznie przechowywać
backupy oraz ograniczać dostęp do serwera. Planowane przejście na PostgreSQL
przy wdrożeniu wieloużytkownikowym pozostaje osobnym elementem backlogu.
