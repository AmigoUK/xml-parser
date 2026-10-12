# XML Parser faktur

[![CI](https://github.com/AmigoUK/xml-parser/actions/workflows/ci.yml/badge.svg)](https://github.com/AmigoUK/xml-parser/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/AmigoUK/xml-parser)](https://github.com/AmigoUK/xml-parser/releases)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Flask](https://img.shields.io/badge/flask-3.1-lightgrey)

**Uczący się parser faktur strukturalnych.** Czyta faktury XML (także KSeF FA(2)/FA(3) i UBL 2.1), JSON
i CSV od dowolnych dostawców i zamienia je na jeden dokument kanoniczny. Przy **pierwszej** fakturze
nowego dostawcy operator w panelu „negocjuje” odczyt: wskazuje pola, jednostki, przeliczniki i towary.
Decyzje zapisują się w szablonie dostawcy, więc **kolejne faktury przechodzą automatycznie**.
Bez LLM: deterministyczne reguły i transformacje z białej listy.

- **REST API v1** (`X-API-Key`) dla innych systemów + **panel po polsku** z trybem demo.
- 📖 **Pomoc:** w panelu pod `/pomoc`, w repo: [docs/pomoc](docs/pomoc/README.md) i w zakładce [Wiki](https://github.com/AmigoUK/xml-parser/wiki) (lustro odświeżane automatycznie).
- ❓ **FAQ:** [Najczęstsze pytania](docs/pomoc/faq.md) — m.in. [worki → kilogramy](docs/pomoc/faq.md#worek-na-kg) krok po kroku, ze zrzutem i listą pułapek.
- 📝 Zmiany: [CHANGELOG.md](CHANGELOG.md) · Specyfikacja: [design](docs/superpowers/specs/2026-10-10-xml-invoice-parser-design.md)

![Widok dokumentu z problemami do wyjaśnienia](app/static/screenshots/04-dokument.png)

## Funkcje

| Obszar | Co potrafi |
|---|---|
| Wejście | Upload w panelu (drag & drop) lub `POST /api/v1/documents`; XML, JSON, CSV (`;`/`,`, UTF-8 i Windows-1250); wykrywanie formatu po treści |
| Synchronizacja | przyrostowe pobieranie zmian statusów przez API — `GET /api/v1/documents?updated_since=…` z kursorem `next_cursor` (także faktury zatwierdzone przez operatora później), stronicowanie po `(updated_at, id)`, dostawa „co najmniej raz”; gotowy kod w 4 językach w [przewodniku integracji](docs/pomoc/integracja.md) |
| Rozpoznanie dostawcy | po NIP/VAT, a gdy go brak — po „odcisku” struktury pliku (podobieństwo ścieżek) |
| Szablony | mapowanie ścieżka → pole, łańcuchy transformacji, wartości domyślne; wersjonowanie, historia i przywracanie wersji |
| Transformacje | m.in. `decimal` (przecinek/kropka, tysiące, nawiasy = ujemna), `date`, `regex_extract` z limitem czasu, `map`, `convert`, `negate`, `gs1`, `strip_ai_prefix`, `concat`, `split` (pełna lista w [pomocy](docs/pomoc/edytor-mapowan.md)) |
| GS1 | parser GS1-128 (AI 01 z walidacją cyfry kontrolnej GTIN, 10 partia, 11/13/15/17 daty) |
| Jednostki | słownik jednostek i aliasów (globalnych i per dostawca), przeliczniki np. `kart.` → 12 szt, `worek` → 25 kg |
| Towary | kartoteka z importem CSV, mapowanie pozycji dostawcy na nasz indeks po kodzie/GTIN |
| Walidacja | sumy pozycji i nagłówka (tolerancja 0,01), pola wymagane, niejednoznaczne liczby (`1,234`), duplikaty w zakresie klucza API |
| Kolejka | dokumenty „Do wyjaśnienia” z podpowiedziami (% pewności) i wyborem „tylko ta faktura” / „zapamiętaj w szablonie” |
| Bezpieczeństwo | ochrona przed XXE i billion laughs, limity rozmiaru/węzłów/pozycji, haszowane klucze API, CSRF, CSP, limit prób logowania |

## Jak to działa

![Przetwarzanie faktury: plik → format i drzewo → rozpoznanie dostawcy → szablon → walidacja → zatwierdzona albo do wyjaśnienia; negocjacja w panelu wraca do szablonu](app/static/screenshots/diagram-przetwarzania.png)

<sub>Źródło diagramu (Mermaid): [`docs/screenshots/diagram-przetwarzania.mmd`](docs/screenshots/diagram-przetwarzania.mmd). Pomoc w panelu („Jak to działa”) pokazuje wariant pionowy: [`app/static/screenshots/diagram-przetwarzania-td.png`](app/static/screenshots/diagram-przetwarzania-td.png).</sub>

Szczegóły krok po kroku: [docs/pomoc/jak-to-dziala.md](docs/pomoc/jak-to-dziala.md).

## Zrzuty ekranu

Wszystkie dane na zrzutach są fikcyjne (próbki z [`demo/samples`](demo/samples/README.md)). Te same pliki
(`app/static/screenshots/`) ilustrują tematy Pomocy w panelu; odświeża je narzędzie `tools/screenshots.py`
(sekcja „Rozwój lokalny”).

| | |
|---|---|
| ![Pulpit](app/static/screenshots/02-pulpit.png)<br/>**Pulpit** — po nauczeniu na alfa-1 faktura alfa-2 zatwierdzona automatycznie | ![Kolejka](app/static/screenshots/03-kolejka.png)<br/>**Kolejka do wyjaśnienia** |
| ![Edytor mapowań](app/static/screenshots/05-edytor-mapowan.png)<br/>**Edytor mapowań** — klik w element pliku → klik w pole, podgląd na żywo | ![Szablony](app/static/screenshots/10-szablony.png)<br/>**Szablony** z wersjami |
| ![Kartoteka towarów](app/static/screenshots/06-kartoteka.png)<br/>**Kartoteka towarów** | ![Przeliczniki](app/static/screenshots/07-przeliczniki.png)<br/>**Przeliczniki** |
| ![Pomoc](app/static/screenshots/08-pomoc.png)<br/>**Pomoc** w panelu | ![Statusy i problemy](app/static/screenshots/09-pomoc-problemy.png)<br/>**Kody problemów** z opisem rozwiązania |
| ![O demo](app/static/screenshots/01-demo.png)<br/>**Tryb demo** z próbkami faktur | ![API](app/static/screenshots/11-api-docs.png)<br/>**Dokumentacja API** (OpenAPI) |
| ![Przewodnik integracji](app/static/screenshots/12-pomoc-integracja.png)<br/>**Przewodnik integracji przez API** — synchronizacja `updated_since` + `cursor` | ![FAQ: worki → kilogramy](app/static/screenshots/13-faq-worek.png)<br/>**Negocjacja przelicznika** `1 worek = 25 kg` — scenariusz z [FAQ](docs/pomoc/faq.md#worek-na-kg) |

## API w 30 sekund

```bash
BASE=http://localhost:${APP_PORT:-18506}   # adres Twojej instancji (port APP_PORT z .env)
# wyślij fakturę (klucz API tworzysz w panelu: „Klucze API”)
curl -H "X-API-Key: TWÓJ_KLUCZ" -F file=@demo/samples/alfa-1.xml $BASE/api/v1/documents
# → 201 {"id": 1, "status": "needs_review", "issues": [...]}

curl -H "X-API-Key: TWÓJ_KLUCZ" $BASE/api/v1/documents/1
curl -H "X-API-Key: TWÓJ_KLUCZ" "$BASE/api/v1/documents?status=approved"
curl -X POST -H "X-API-Key: TWÓJ_KLUCZ" $BASE/api/v1/documents/1/reprocess

# synchronizacja: dokumenty zmienione od podanej chwili (także zatwierdzone później przez operatora),
# rosnąco po (updated_at, id); kolejna strona: te same parametry + cursor=<next_cursor>, aż next_cursor = null
curl -H "X-API-Key: TWÓJ_KLUCZ" "$BASE/api/v1/documents?updated_since=2026-10-11T06:00:00Z&status=approved&limit=500"
# → 200 {"items": [{"id": 1, "status": "approved", "updated_at": "2026-10-11T06:04:38.412811Z", ...}], "next_cursor": null}
```

Czasy w odpowiedziach (`created_at`, `updated_at`) są w ISO 8601 w UTC z mikrosekundami i `Z`
(`2026-10-11T06:04:38.312308Z`); parametry czasu przyjmują strefę (`+` w adresie zapisz jako `%2B`).
Zalecany algorytm synchronizacji (margines 5 min, deduplikacja po `id` i `updated_at`) i gotowy kod w Pythonie, PHP,
JavaScripcie i powłoce: [docs/pomoc/integracja.md](docs/pomoc/integracja.md).
Pełny opis endpointów, kodów odpowiedzi i limitów: [docs/pomoc/api.md](docs/pomoc/api.md),
w panelu: `/api/docs` (OpenAPI: [`app/static/openapi.yaml`](app/static/openapi.yaml)).

## Uruchomienie (Docker)

```bash
cp .env.example .env   # uzupełnij hasła
docker compose up -d --build
# panel (Tailscale MagicDNS): http://<nazwa-hosta>.<tailnet>.ts.net:${APP_PORT}   (domyślnie APP_PORT=18506; kontener nasłuchuje wewnętrznie na 5010)
```

Domyślnie port jest publikowany **tylko na 127.0.0.1** (`APP_BIND`). Docker omija ufw, więc `0.0.0.0`
wystawia aplikację na całą sieć. Aby udostępnić panel przez Tailscale, ustaw w `.env`
`APP_BIND=<IP interfejsu tailscale0>` (`tailscale ip -4`) i zrestartuj stack — albo wystaw panel po HTTPS
przez `tailscale serve` (niżej).

**Obsługiwana baza: MariaDB ≥ 11.4** (MySQL i starsze MariaDB nie są wspierane — migracje i kopie zapasowe zakładają
składnię 11.x, kolumny JSON jako `LONGTEXT CHECK(json_valid)`). **Aplikacja wymaga własnej (sub)domeny** — wdrożenie pod
podścieżką (`https://firma.pl/xml-parser/`) nie jest obsługiwane (adresy w Pomocy, przykładach integracji i Swagger UI
są liczone od korzenia hosta).

`SECRET_KEY`, `DATABASE_URL`, `MARIADB_PASSWORD` i `MARIADB_ROOT_PASSWORD` są wymagane (compose przerwie start
bez nich). Usługa `app` dostaje z `.env` **tylko zmienne aplikacji** wymienione w `docker-compose.yml`
(bez hasła roota bazy) — nową zmienną aplikacji trzeba dopisać także tam. Kontener działa jako użytkownik
nie-root (uid 10001); entrypoint przy starcie naprawia właściciela wolumenu storage (gdy trzeba), odmawia
startu bez `DATABASE_URL` (albo z SQLite), czeka na bazę (błąd hasła/użytkownika/bazy kończy start od razu)
i uruchamia migracje oraz seed pod blokadą po stronie bazy (bezpieczne przy kilku replikach; `MIGRATE_ON_START=0`
zostawia je osobnemu zadaniu). `/healthz` sprawdza połączenie z bazą (503 przy awarii); sondę `HEALTHCHECK`
ma obraz, compose ją dziedziczy. Port wewnętrzny: `APP_INTERNAL_PORT` (domyślnie 5010; `PORT` platformy ma
pierwszeństwo). Limity zasobów: `APP_MEM_LIMIT`, `APP_CPUS`, `DB_MEM_LIMIT`, `DB_CPUS`. Logi dockera są rotowane
(10 MB x 3). Zależności runtime są przypięte w `requirements.lock` (używany w obrazie i w CI), obrazy bazowe
w konkretnych wersjach. **Przeniesienie na inną platformę** (reverse proxy, repliki, baza zarządzana,
procedura migracji danych): [docs/wdrozenie.md](docs/wdrozenie.md).

### HTTPS w tailnecie (tailscale serve)

Panel i API możesz wystawić po HTTPS w obrębie swojego tailnetu. Certyfikat wystawia Tailscale — wymaga włączonych
„HTTPS Certificates” w konsoli administracyjnej tailnetu. Port na adresie Tailscale zajmuje wtedy `tailscale serve`,
więc aplikacja nasłuchuje tylko lokalnie. W `.env`:

```bash
APP_BIND=127.0.0.1        # port aplikacji tylko lokalnie — z tailnetu ruch przychodzi przez tailscale serve
TRUSTED_PROXY_COUNT=1     # ProxyFix: poprawne https:// w adresach Pomocy i prawdziwe IP klienta dla limitu logowań
SESSION_COOKIE_SECURE=1   # ciasteczka sesji tylko po HTTPS
```

Potem (`${APP_PORT}` — wartość z `.env`, domyślnie 18506):

```bash
docker compose up -d
tailscale serve --bg --https=${APP_PORT} http://127.0.0.1:${APP_PORT}
# panel: https://<nazwa-hosta>.<tailnet>.ts.net:${APP_PORT}   (tylko w tailnecie)
tailscale serve --https=${APP_PORT} off   # wyłączenie
```

## Kopie zapasowe i odtwarzanie

```bash
tools/backup.sh          # dump MariaDB + archiwum storage do backups/<data>/ (retencja 14 dni; argument = liczba dni)
BACKUP_DIR=/mnt/kopie tools/backup.sh   # inny katalog/dysk kopii; archiwum storage czyta STORAGE_DIR kontenera app
# cron (codziennie 03:15):  15 3 * * *  cd /ścieżka/do/xml-parser && tools/backup.sh >> backups/backup.log 2>&1
```

Odtwarzanie (na działającym stacku; **nadpisuje bieżące dane**):

```bash
B=backups/<data>
gunzip -c $B/db.sql.gz | docker compose exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot'
gunzip -c $B/storage.tar.gz | docker compose exec -T app tar -C /data/storage -xf -
docker compose restart app
docker compose exec app flask check-storage   # każdy dokument ma plik w magazynie? (kod 1 + lista id, gdy nie)
```

Okresowo sprawdź kopię, odtwarzając ją na osobnym środowisku. Pełna procedura przeniesienia na inny host:
[docs/wdrozenie.md](docs/wdrozenie.md).

Serwer: gunicorn z workerami wątkowymi (`-k gthread -w 2 --threads 8 --timeout 60`), dzięki czemu
bezczynne połączenia przeglądarki nie blokują aplikacji. Pojedyncze ustawienia zmieniasz zmiennymi
`GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` (i `GUNICORN_WORKER_TMP_DIR`, domyślnie `/dev/shm` — pomijany,
gdy katalog nie istnieje); `GUNICORN_CMD_ARGS` (np. `-k gthread -w 4 --threads 16 --timeout 90`) zastępuje cały zestaw flag.

## Zmienne środowiskowe

Wartości i komentarze: [`.env.example`](.env.example); kontrakt dla platform bez `.env`: [docs/wdrozenie.md](docs/wdrozenie.md).

| Grupa | Zmienne |
|---|---|
| Wymagane | `SECRET_KEY` (min. 32 losowe znaki; placeholder = odmowa startu), `DATABASE_URL` (MariaDB; entrypoint odrzuca SQLite), `MARIADB_ROOT_PASSWORD`, `MARIADB_PASSWORD` (+ `MARIADB_DATABASE`, `MARIADB_USER` — usługa `db`) |
| Pierwszy start | `ADMIN_EMAIL`, `ADMIN_PASSWORD` (min. 10 znaków, nie przykładowe; później `flask set-admin-password`) |
| Demo | `DEMO_MODE` (domyślnie 0), `DEMO_API_KEY` (min. 24 znaki; wartość przykładowa odrzucana) |
| Limity | `MAX_DOCUMENT_BYTES`, `MAX_TREE_NODES`, `MAX_LINES` |
| Sieć | `APP_BIND`, `APP_PORT`, `APP_INTERNAL_PORT` / `PORT`, `XP_SUBNET`, `TRUSTED_PROXY_COUNT`, `PREFERRED_URL_SCHEME` |
| Wyświetlanie | `DISPLAY_TZ` (domyślnie `Europe/Warsaw`) — strefa czasu w panelu; baza i API zostają w UTC |
| Sesja i logowanie | `SESSION_COOKIE_SECURE`, `SESSION_HOURS` (domyślnie 8), `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES`, `LOGIN_MAX_ATTEMPTS_PER_IP`, `LOGIN_MAX_ATTEMPTS_PER_EMAIL`, `LOGIN_EMAIL_LOCKOUT_MINUTES`, `AUDIT_RETENTION_DAYS` (domyślnie 90) |
| Kontener | `STORAGE_DIR`, `MIGRATE_ON_START`, `MIGRATE_LOCK_TIMEOUT`, `DB_WAIT_ATTEMPTS`, `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT`, `GUNICORN_WORKER_TMP_DIR`, `GUNICORN_CMD_ARGS`, `APP_MEM_LIMIT`, `APP_CPUS`, `DB_MEM_LIMIT`, `DB_CPUS` |
| Kopie | `BACKUP_DIR`, `BACKUP_RETENTION_DAYS` (skrypt `tools/backup.sh`) |
| Tylko testy i narzędzia | `TEST_MARIADB_URL`, `PYTHON_DOTENV_DISABLED`, `FLASK_SKIP_DOTENV` |

## Rozwój lokalny

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ln -sf ../../tools/pre-commit .git/hooks/pre-commit   # lint (ruff) + strażnik danych prywatnych przed commitem
ruff check .                                          # konfiguracja w pyproject.toml (E, F, W, B, I, UP; 120 znaków)
pytest -rs                                            # -rs pokazuje testy pominięte (np. bez MariaDB)
pytest --cov=app --cov-report=term-missing:skip-covered   # pokrycie; CI wymaga ≥ 90 %
```

Testy na prawdziwej MariaDB (migracje, kolacja `products.code`, blokada migracji, sonda bazy, plan zapytania
synchronizacji) są lokalnie **pomijane**, dopóki nie ustawisz `TEST_MARIADB_URL` na pustą bazę testową — nazwa bazy
musi zawierać człon `test` (testy kasują wszystkie tabele). Ta sama tymczasowa baza co w CI:

```bash
docker run -d --name xp-mariadb-test -e MARIADB_ROOT_PASSWORD=ci-root -e MARIADB_DATABASE=xp_test \
  -p 127.0.0.1:3307:3306 mariadb:11.4.13 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
TEST_MARIADB_URL="mysql+pymysql://root:ci-root@127.0.0.1:3307/xp_test?charset=utf8mb4" pytest -rs
docker rm -f xp-mariadb-test
```

Wendorowane biblioteki frontendu (Bootstrap, Alpine.js w buildzie CSP, Swagger UI) mają manifest z wersjami i sumami
SHA-256 w [`app/static/vendor/VERSIONS.md`](app/static/vendor/VERSIONS.md) — test pilnuje zgodności sum z plikami.

### Generowanie zrzutów ekranu

`tools/screenshots.py` generuje zrzuty w `app/static/screenshots/` (tematy Pomocy w panelu i README) — odśwież je po
każdym wydaniu, bo stopka pokazuje wersję. Narzędzie uruchamia odizolowaną instancję na `127.0.0.1:18517` (świeża
SQLite i storage w katalogu tymczasowym, bez `.env`, tylko fikcyjne próbki z `demo/samples/`, konto
`admin@example.com` z jednorazowym hasłem), loguje się w Chromium przez Playwright i nadpisuje pliki PNG. Nigdy nie rób
zrzutów żywego demo.

```bash
pip install playwright && playwright install chromium   # zależność opcjonalna, tylko dla tego narzędzia
python tools/screenshots.py                             # wszystkie zrzuty; --list wypisuje strony
python tools/screenshots.py --only 08-pomoc 11-api-docs # wybrane zrzuty; --port zmienia port instancji
```

Playwright może mieć osobny venv (`/ścieżka/pw-venv/bin/python tools/screenshots.py`) — serwer aplikacji i tak działa
w podprocesie z `.venv/bin/python` (albo z interpretera podanego w `--app-python`). Diagramy `diagram-przetwarzania.png`
(poziomy, w README) i `diagram-przetwarzania-td.png` (pionowy) nie są zrzutami: Mermaid CLI renderuje je ze źródeł
`docs/screenshots/diagram-przetwarzania.mmd` i `docs/screenshots/diagram-przetwarzania-td.mmd`, które mają ustawienia
renderu w nagłówku (Mermaid 11.4.1, skala 2):

```bash
npx -y -p @mermaid-js/mermaid-cli@11.4.2 -p mermaid@11.4.1 mmdc -i docs/screenshots/diagram-przetwarzania.mmd -o app/static/screenshots/diagram-przetwarzania.png -s 2 -b white
npx -y -p @mermaid-js/mermaid-cli@11.4.2 -p mermaid@11.4.1 mmdc -i docs/screenshots/diagram-przetwarzania-td.mmd -o app/static/screenshots/diagram-przetwarzania-td.png -s 2 -b white
```

Pomoc w panelu pokazuje wariant pionowy (`diagram-przetwarzania-td.png`), czytelny w wąskiej kolumnie; README zostaje
przy poziomym.

## Dane prywatne

Realne faktury trzymaj **wyłącznie** w `private/` (ignorowane przez git).
Test `tests/test_no_private_data.py` (i hook pre-commit) szuka w śledzonych plikach
zakazanych tokenów (nazwy, NIP-y) wczytywanych z lokalnego pliku
`private/forbidden-tokens.txt` (jeden token na linię, małymi literami, `#` = komentarz).
Plik jest ignorowany przez git; bez niego skan jest pomijany — utwórz go na każdej maszynie deweloperskiej.

## Tryb demo

Domyślnie `DEMO_MODE=0`. `DEMO_MODE=1` włącza publiczną stronę „O demo” (opis, próbki faktur,
e-mail konta demo) oraz kartotekę i klucz API demo. Strona **nigdy nie pokazuje hasła** —
hasło ustawiasz w `ADMIN_PASSWORD` w `.env`. Klucz API demo widzą tylko zalogowani, a reset danych
(„Wyczyść dane demo”) może wykonać tylko administrator. Nie używaj `DEMO_MODE=1` na instancji
z prawdziwymi danymi.

## Bezpieczeństwo panelu

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `SESSION_COOKIE_SECURE` | `0` | `1` = ciasteczka sesji tylko po HTTPS. Domyślnie wyłączone, bo demo działa po HTTP przez Tailscale (tunel szyfrowany). Włącz, gdy panel stoi za TLS (np. `tailscale serve` / reverse proxy z HTTPS) — inaczej logowanie przestanie działać. |
| `TRUSTED_PROXY_COUNT` | `0` | Liczba zaufanych reverse proxy przed aplikacją. `0` = nagłówki `X-Forwarded-*` ignorowane (bez proxy ktoś mógłby podszyć IP). Ustaw `1`, gdy aplikacja stoi za jednym proxy, np. `tailscale serve` (adres klienta, schemat https). Gdy przy `0` przyjdzie żądanie z `X-Forwarded-For`, aplikacja ostrzega w logu (raz na proces); przy `>0` i `SESSION_COOKIE_SECURE=0` ostrzega przy starcie. |
| `PREFERRED_URL_SCHEME` | `http` | Schemat adresów zewnętrznych budowanych poza żądaniem (CLI). Za proxy z TLS ustaw `https`. |
| `LOGIN_MAX_ATTEMPTS` | `5` | Główny limit: nieudane logowania dla pary (e-mail, adres IP), po których ta para jest blokowana. `0` wyłącza ten próg. |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Okno liczenia i czas blokady dla progów per (e-mail, IP) i per IP. |
| `LOGIN_MAX_ATTEMPTS_PER_IP` | `20` | Nieudane logowania z jednego IP na dowolne konta (rozpylanie haseł). |
| `LOGIN_MAX_ATTEMPTS_PER_EMAIL` | `50` | Nieudane logowania na jedno konto z dowolnych IP (atak rozproszony). |
| `LOGIN_EMAIL_LOCKOUT_MINUTES` | `5` | Okno i czas blokady dla progu per e-mail (krótsze). |
| `SESSION_HOURS` | `8` | Czas życia sesji panelu w godzinach (demo publiczne: krócej). |
| `DISPLAY_TZ` | `Europe/Warsaw` | Strefa czasu (nazwa IANA) dla dat i godzin w panelu; pełna strefa w podpowiedzi po najechaniu. Nie wpływa na bazę ani REST API — te zawsze podają UTC z przyrostkiem `Z`. |
| `AUDIT_RETENTION_DAYS` | `90` | Retencja wpisów `login_failed`/`login_blocked` w „Historii” dla `flask prune-audit`. |

Kompromis limitu logowania: obcy, który zna e-mail admina, ale nie hasło, blokuje 5 próbami tylko
siebie (parę e-mail + jego IP) — admin z innego adresu loguje się normalnie. Blokada całego konta
następuje dopiero po 50 nieudanych próbach w 5 min z wielu adresów i trwa krótko. Próby odrzucone
blokadą nie są liczone (nie przedłużają blokady). Próba jest zapisywana w bazie przed sprawdzeniem
hasła, więc równoległe żądania nie omijają limitu. Uwaga: jeśli wszyscy klienci docierają z jednego
adresu (NAT Dockera, proxy bez `TRUSTED_PROXY_COUNT`), progi per IP działają jak globalne — dlatego za proxy
`TRUSTED_PROXY_COUNT` jest obowiązkowy (patrz [docs/wdrozenie.md](docs/wdrozenie.md)).

Pozostałe zabezpieczenia: nagłówki `Content-Security-Policy` (`script-src 'self'` — bez skryptów inline i bez
`'unsafe-eval'`; Alpine.js w buildzie CSP), `Strict-Transport-Security` przy HTTPS, `Permissions-Policy`,
`X-Frame-Options: DENY`, `X-Content-Type-Options`,
`Referrer-Policy`; ciasteczka `HttpOnly` + `SameSite=Lax`, sesja wygasa po 8 h; wylogowanie
(i zmiana hasła) unieważnia wszystkie wcześniej wydane ciasteczka sesji użytkownika.
Nieudane i zablokowane logowania trafiają do „Historii” (`login_failed` — każda próba do progu blokady,
`login_blocked` — jeden wpis na adres IP i okno blokady, żeby odrzucane żądania nie zapełniały bazy). Retencja:
`docker compose exec app flask prune-audit` usuwa wpisy logowań starsze niż `AUDIT_RETENTION_DAYS` (`--days N`,
`--all-actions` dla całego dziennika) — np. z crona raz dziennie obok `tools/backup.sh`.

**Hasło administratora.** Seed tworzy konto tylko przy pierwszym starcie — późniejsza zmiana `ADMIN_PASSWORD` w `.env`
nie zmienia hasła. Rotacja: w panelu „Zmień hasło” (obok adresu e-mail; wymaga obecnego hasła) albo
`docker compose exec app flask set-admin-password` (pyta o hasło; `--from-env` bierze nowe `ADMIN_PASSWORD`,
`--password-stdin` czyta z wejścia, `--email` dla innego konta). Obie drogi unieważniają wszystkie wydane ciasteczka sesji
tego konta. Hasło: min. 10 znaków, nie przykładowe.
Klucz API widzi tylko swoje dokumenty i dostawców z tych dokumentów; podpowiedzi z kartoteki
(towary, inni dostawcy, szablony) nie są zwracane przez API.

## Sieć Docker (`XP_SUBNET`)

Domyślna sieć Compose ma jawną podsieć `${XP_SUBNET:-10.210.10.0/24}`. Gdy pule adresów Dockera
na hoście są wyczerpane lub podsieć koliduje z inną, ustaw w `.env` własną wartość `XP_SUBNET`.
