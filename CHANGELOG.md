# Changelog

All notable changes to **xml-parser** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Zestaw demo „Miesiąc faktur” (`demo/dataset/`): 24 fikcyjne faktury sześciu dostawców, w tym nowy „Eta Packaging Sp. z o.o.” (XML z angielskimi tagami), z `manifest.json` (kolejność, fazy, oczekiwane statusy `on_ingest`/`after_resolve`). Pułapki: brak waluty, jednostki `pcs`/`C62`/`H87`/`EA`/`wor.`/`kart.`, towary spoza kartoteki, niezgodność sumy pozycji, nowy alias `PCE`, duplikat bajtowy.
- Karta „Zestaw demo” na stronie „O demo”: przyciski „Wczytaj pierwsze (6)”, „Wczytaj pozostałe (18)”, „Wczytaj wszystko (24)” i tabela postępu (status oczekiwany a rzeczywisty, źródło); serwis `demo_dataset`.
- Walidacja plików zestawu przed wczytaniem (istnienie, sha256); błędy `DatasetError` i `DatasetLoadError` z wynikiem częściowym.
- Generator `tools/gen_demo_dataset.py` z trybem `--check` (ponowne wygenerowanie = identyczne bajty).
- Skrypt `app/help_examples/zestaw-demo.sh` (wczytanie zestawu przez API, `XP_API_KEY`), temat Pomocy `zestaw-demo` i FAQ `zestaw-demo-api`.
- Zrzut `14-demo-zestaw`; instancja zrzutów wczytuje pierwszą fazę zestawu.

### Changed
- „Wyczyść dane demo” → „Resetuj zestaw demo” (nadal tylko administrator).
- Test uczenia obejmuje sześciu dostawców zestawu demo.

### Fixed
- `tools/screenshots.py --list` działa bez manifestu zestawu; czytelny błąd pojawia się dopiero przy starcie serwera zrzutów.
- Czwarte faktury zestawu są czyste po nauce na pierwszych sześciu, więc faza „pozostałe” wczytana jedną partią zgadza się z manifestem.

## [0.7.1] — 2026-10-12

### Added
- Polskie strony błędów panelu (403, 404, 405, 413, 500 i przepełnienie liczby w adresie) z nawigacją i stopką; `/api/*` nadal odpowiada JSON-em.
- Stronicowanie list: kursor („Starsze →” / „Następne →”) w Dokumentach, Kolejce, Historii i Szablonach oraz numerowane strony w słownikach (w stałej kolejności słownika).
- Wyszukiwarka dokumentów (`?q=`) i pole wyszukiwania w słownikach (`?q=` + `?page=`).
- Filtry Historii (akcja, użytkownik) z polskimi etykietami wszystkich akcji.
- Komunikaty po operacjach na kluczach API (włączenie/wyłączenie, zmiana nazwy, usunięcie, „Nie znaleziono klucza”; utworzenie pokazuje jednorazowy alert z kluczem, nie komunikat) i po operacjach w słownikach, z nazwą wpisu.
- Odnośniki powrotu: „← Wróć do kolejki” / „← Wróć do dokumentów” w widoku dokumentu i „← Szablony” w szczegółach szablonu; potwierdzenie usunięcia szablonu z nazwą; podpowiedź „Maks. N MiB” przy wgrywaniu; e-mail zostaje w polu po nieudanym logowaniu.
- Polska strona błędu 400 dla wygasłego tokenu formularza (CSRF) i innych nieprawidłowych żądań panelu; `/api/*` bez zmian.
- Potwierdzenia: Odrzuć, Przywróć wersję, Wyłącz klucz, usuwanie wpisów słowników (z nazwą).
- Stany pustych list z odnośnikami do następnego kroku.
- `DISPLAY_TZ` (domyślnie `Europe/Warsaw`): czas lokalny w panelu, baza i REST API bez zmian (UTC); zmienna w `.env.example`, compose i README.
- Ostrzeżenie przed opuszczeniem edytora mapowań z niezapisanymi zmianami (`beforeunload`).
- Aktywna pozycja nawigacji (`aria-current="page"`) i atrybuty ARIA przełączników menu.
- FAQ w Pomocy: „Jaki czas pokazuje panel?” (`#czas-w-panelu`) i „Lista się urywa — gdzie reszta wpisów?” (`#dluzsze-listy`).

### Changed
- Nazwy stron zgodne z menu: „Mapowania towarów”, „Jednostki”, „Przeliczniki”, „Historia”, „Szablony”; podpisy zrzutów w Pomocy i README poprawione tak samo.
- Formaty: kwoty „1 234,56” (ceny jednostkowe do 4 miejsc, wyrównane do prawej), czas jako `<time>` z UTC w `datetime` i pełną strefą w podpowiedzi.
- Etykiety akcji w Historii po polsku; akcja „Zmień nazwę” przy kluczu API.
- Zamykane komunikaty (`role="alert"`), pasek „← Panel” w `/api/docs`, blokada podwójnego wysłania formularza wgrywania, pole wyszukiwania w słownikach.

### Fixed
- Filtry kwot, cen i ilości nie powodują już błędu 500 dla bardzo długich liczb (>28 cyfr) — pokazują wartość bez zmian.
- „O demo” jest teraz aktywną pozycją nawigacji na stronie demo; „Wróć do Pulpitu” na stronach błędów prowadzi do Pulpitu także w trybie demo.
- Przycisk „Przetwórz” odblokowuje się po powrocie do strony przyciskiem „Wstecz”.
- Limity rozmiaru pliku w komunikatach w MiB (spójnie z podpowiedzią), placeholder liczb z kropką (np. 12 albo 1.125).
- N+1 zapytań na liście szablonów.
- Pusta nazwa klucza API była po cichu ignorowana — teraz komunikat błędu.
- Kategoria komunikatu po błędzie resetu demo.
- Dostępność formularzy: etykiety pól, `autocomplete`, atrybuty `aria-*`; klasa `.scroll-pane` zamiast stylu inline.
- Filtr `price` pokazuje ceny jednostkowe z 4 miejscami zamiast zaokrąglenia do kwoty.
- Pusta strona z kursorem pokazuje powrót zamiast fałszywego stanu pustego.

### Security
- Limit prób obecnego hasła przy zmianie hasła (osobna pula `pwchange:`); logowanie odrzuca e-mail z takim prefiksem, więc puli nie da się zapisać z zewnątrz.
- Usunięto martwe ustawienia `REMEMBER_COOKIE_*`.
- Bezpieczne budowanie adresów stronicowania (odrzucanie argumentów `_` w `url_for`, brak kolizji z `view_args`).

**Znane ograniczenie:** gdy żądanie jest odrzucane za duże (413) zanim serwer przeczyta treść, przeglądarka może pokazać reset połączenia zamiast polskiej strony błędu.

## [0.7.0] — 2026-10-12

### Added
- FAQ w Pomocy: sześć pytań o jednostki i przeliczniki napisanych prostym językiem — „Dostawca sprzedaje w workach, a my liczymy w kilogramach” (krok po kroku, zrzut ze scenariusza, tabela „co dzieje się z liczbami” i lista pułapek: alias wprost na kg, kropka dziesiętna, zawsze zapamiętywany, działa od teraz, tylko na jednostkę bazową, zakres „tylko dla tego towaru” wymaga towaru), worki 25 kg i 50 kg u jednego dostawcy, poprawa złego przelicznika i „Przetwórz ponownie”, cena jednostkowa po przeliczeniu, worek → karton (nie), różne zapisy tej samej jednostki. Pytania mają stałe kotwice (`/pomoc/faq#worek-na-kg`), linkowane z tematu „Jednostki”; wpis FAQ może mieć partial HTML (`app/templates/help/faq/`).
- Zakładka **Wiki** na GitHubie jako lustro Pomocy: `tools/export_wiki.py` (tylko biblioteka standardowa) przepisuje `docs/pomoc/*.md` na strony Wiki (nazwy z nagłówków, linki między tematami, obrazki przez raw.githubusercontent.com, pasek boczny z FAQ na górze, stopka), a workflow `.github/workflows/wiki.yml` wypycha je po każdym pushu na `main`; ręczne edycje w Wiki są nadpisywane. README linkuje Wiki i FAQ.
- Próbka demo `zeta.csv` (Hurtownia Zeta: „wor.”, 20 worków cukru po 25 kg) i zrzut `13-faq-worek.png` — karta „brak przelicznika” z podpowiedzianym `1 worek = 25 kg`; `tools/screenshots.py` potrafi zatrzymać „operatora” na wskazanym problemie (`SAMPLES` z kodem problemu), pętla `resolve_with_top_suggestions` ma `stop_at`. Próbka na stronie „O demo”, w teście uczenia i w `demo/samples/README.md`.
- Zmiana hasła w panelu („Zmień hasło” obok adresu e-mail: obecne hasło + nowe dwa razy; min. 10 znaków, nie przykładowe) oraz `flask set-admin-password` (`--from-env`, `--password-stdin`, `--email`; tworzy konto, gdy go nie ma). Obie drogi unieważniają wszystkie wydane ciasteczka sesji konta; wpisy `password_change` / `password_set` w Historii. Seed nadal nie nadpisuje hasła istniejącego konta — rotacja po zmianie `ADMIN_PASSWORD` w `.env` to właśnie ta komenda (README: „Hasło administratora”, Pomoc: FAQ „Jak zmienić hasło?”).
- `flask prune-audit`: retencja dziennika — usuwa wpisy `login_failed`/`login_blocked` starsze niż `AUDIT_RETENTION_DAYS` (domyślnie 90; `--days N`, `--all-actions` dla całego dziennika). Nowe zmienne `AUDIT_RETENTION_DAYS` i `SESSION_HOURS` (czas życia sesji, dotąd stała 8 h) — w `.env.example`, compose i README.
- Nagłówki `Permissions-Policy: camera=(), microphone=(), geolocation=()` zawsze i `Strict-Transport-Security: max-age=31536000; includeSubDomains` dla żądań po HTTPS (także za proxy z `X-Forwarded-Proto` i `TRUSTED_PROXY_COUNT`).
- Favicon (`/static/favicon.svg`, `/favicon.ico` → przekierowanie) oraz metadane `description` i Open Graph (`og:title`, `og:description`, `og:image` z `app/static/og-image.png` — grafika social preview przeniesiona z `docs/screenshots/`).
- OpenAPI: schematy `Supplier` i `SupplierList` dla `GET /suppliers`, odpowiedź `401` przy każdej operacji, nagłówek `X-Filename` przy `POST /documents`; test porównuje listę dostawców ze specyfikacją.
- Manifest wendorowanych bibliotek `app/static/vendor/VERSIONS.md` (nazwa, wersja, adres źródła, SHA-256) z testem zgodności sum; procedura aktualizacji w pliku.
- `tools/screenshots.py` odrzuca port żywego demo odczytany z `APP_PORT` (środowisko i `.env`), nie tylko domyślny 18506.
- Testy bezpieczeństwa z listy audytu: CSRF na formularzach panelu (logowanie, wylogowanie, negocjacja, klucze API, kartoteka, zmiana hasła), API bez sesji ciasteczkowej (`?api_key=`, `Authorization` → 401), XXE z odczytem pliku i billion laughs (czas < 1 s), DOCTYPE po 5 KB białych znaków i zewnętrzne DTD, odmowa startu przy placeholderze `SECRET_KEY`, nagłówki na stronach błędów i API 500 bez szczegółów, `Storage._path`, blokada „wszyscy z jednego IP” bez `TRUSTED_PROXY_COUNT`, seed nie nadpisuje hasła; test komponentu edytora w Node (bez przeglądarki) i test wyrażeń Alpine w szablonach; `ruff` i `pytest-cov` w `requirements-dev.txt`, `[tool.ruff]`/`[tool.coverage]` w `pyproject.toml`, krok lint i próg pokrycia 90 % w CI, lint w hooku pre-commit; `requests` jawnie w zależnościach testów.

### Changed
- **Content-Security-Policy bez `'unsafe-eval'`**: Alpine.js w buildzie CSP (`@alpinejs/csp` 3.17.4) — edytor mapowań i formularz wgrywania używają w atrybutach tylko prostych wyrażeń, a konfigurację edytora podaje blok danych `<script type="application/json">` zamiast atrybutu `x-data`. Nieużywany htmx usunięty z obrazu i stron. Edytor sprawdza `Content-Type` i przekierowanie odpowiedzi przed `r.json()`: wygasła sesja daje komunikat „Sesja wygasła…” zamiast błędu parsowania HTML.
- Dziennik: zablokowana próba logowania zapisuje `login_blocked` raz na adres IP i okno blokady (dotąd każde odrzucone żądanie dopisywało wiersz — wektor zapełnienia bazy), e-mail z formularza w dzienniku obcinany do 100 znaków.
- Seed odrzuca `DEMO_API_KEY` o wartości przykładowej z repozytorium i krótszy niż 24 znaki (ostrzeżenie, klucz demo nie powstaje) — tak jak hasło administratora; `.env.example` zostawia `DEMO_API_KEY` puste z komendą generującą klucz.
- Podpowiedzi towarów: indeks kartoteki budowany raz na dokument, porównanie rozmyte przez `rapidfuzz.process.extract` (w C, nie w pętli Pythona) i budżet 200 problemów `unmapped_product` na dokument z podpowiedziami „podobna nazwa” (dalsze pozycje dostają zgodny GTIN i „nowy towar”) — faktura z tysiącami nieznanych pozycji nie zajmuje workera na minuty; test: 200 pozycji × 5000 towarów < 5 s.
- `conversion_guess` (podpowiedź przelicznika z nazwy towaru) nie przerywa już przetwarzania liczbą poza zakresem w nazwie (dawało mylący `internal_error`); lista przeliczników pokazuje `10`/`100` zamiast `1E+1`/`1E+2`.
- Rejestracja blueprintów panelu jawna, bez `try/except ModuleNotFoundError` — brak zależności albo literówka w imporcie wywraca start zamiast cicho chować część panelu; warunki `nav_blueprints` usunięte z szablonów.
- Eksport Pomocy (`docs/pomoc/`) i README używają neutralnego adresu bazowego (`https://parser.example.com`, w README zmienna `$BASE`) zamiast lokalnego `localhost:18506`; w eksporcie fraza „Adres bazowy (przykład — w panelu widzisz adres swojej instancji)”.
- Entrypoint: pojedyncze flagi gunicorna `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT`, `GUNICORN_WORKER_TMP_DIR`; `--worker-tmp-dir /dev/shm` dodawany tylko, gdy katalog istnieje (runtime bez `/dev/shm` startuje); `GUNICORN_CMD_ARGS` nadal zastępuje cały zestaw.
- Podział warstw: reguły kartoteki, blokady usuwania i import CSV w `app/services/catalog.py`, blokada wiersza szablonu w `app/services/templates.py`, serializer API w `app/api/serializers.py` (panel nie importuje modułu tras API); walidacja kontraktu reguł (`validate_rules`, `validate_chain`) w `app/engine/transforms.py` obok rejestru transformacji i używana także w negocjacji (nie tylko w edytorze).
- Silnik: `apply_template` rozbite na nagłówek, pozycję, jednostkę, towar i przelicznik; `_enrich` jako tablica „kod problemu → funkcja podpowiedzi”; `TypedDict` `Invoice`/`InvoiceLine`; docstringi wszystkich publicznych funkcji i klas `app/engine` oraz fasada `app.engine.__all__`; nazwane stałe progów pewności, heurystyki binarności, limitów list i narzutu uploadu; długości pól z definicji kolumn zamiast literałów `64`/`255`; wartości domyślne konfiguracji tylko w `Config`.
- README: tabela wszystkich zmiennych środowiskowych, „obsługiwana baza: MariaDB ≥ 11.4”, „aplikacja wymaga własnej (sub)domeny” (podścieżka nieobsługiwana — decyzja), uruchomienie testów na MariaDB (`TEST_MARIADB_URL`), lint i pokrycie; `docs/wdrozenie.md` zaktualizowany o nowe zmienne i polecenia.
- Model danych: kolumny `ApiKey.webhook_url`/`webhook_secret` (webhooki planowane na v0.7.0) i `Document.corrects_document_id` zostają zarezerwowane i opisane w modelu jako nieużywane — bez migracji usuwającej (decyzja z audytu).

## [0.6.0] — 2026-10-12

### Added
- Wspólny strażnik identyfikatorów (`app/ids.py`): `<int:…>` w adresach panelu i API jest ograniczony do zakresu kolumny `id` (2⁶³−1), a identyfikatory z formularzy i parametrów zapytania (`unit_id`, `supplier_id`, porównanie wersji `a`/`b`, kursor) przechodzą przez `parse_id`. Liczba spoza zakresu dawała na SQLite `OverflowError` → 500 w 10 ścieżkach (`GET /api/v1/documents/99999999999999999999`, `/dokumenty/<id>`, `/szablony/<id>`, `/klucze-api/<id>/…`, `POST /towary/nowy`…); teraz to 404 albo komunikat formularza, tak samo jak na MariaDB. Siatka bezpieczeństwa: `OverflowError` z bazy → 400 w API, 404 w panelu.
- `POST /api/v1/documents` odpowiada `503 storage_unavailable`, a panel komunikatem, gdy zapis pliku w magazynie się nie powiódł (pełny dysk, utracony wolumen) — zamiast 500; szczegóły w logu. Kod opisany w Pomocy (REST API, Integracja) i w OpenAPI.
- `flask check-storage`: po przeniesieniu danych sprawdza, czy każdy dokument ma plik `raw/<sha256>` w magazynie (kod wyjścia 1 i lista id brakujących).
- Ostrzeżenia konfiguracji proxy w logu: żądanie z `X-Forwarded-For` przy `TRUSTED_PROXY_COUNT=0` (limit logowań per IP działałby jak globalny; raz na proces) oraz `TRUSTED_PROXY_COUNT>0` z `SESSION_COOKIE_SECURE=0` (przy starcie). Nowa zmienna `PREFERRED_URL_SCHEME`.
- Kontener: `HEALTHCHECK` w obrazie (compose go dziedziczy), port wewnętrzny z `APP_INTERNAL_PORT` (`PORT` platformy ma pierwszeństwo) w jednym miejscu dla entrypointu, compose i sondy; migracje i seed pod blokadą po stronie bazy (`app/dblock.py`, `GET_LOCK`) — bezpieczne przy kilku replikach startujących naraz; `MIGRATE_ON_START=0` zostawia je osobnemu zadaniu; sonda bazy `app/dbprobe.py` wypisuje cel połączenia bez hasła i nie ponawia przy złym użytkowniku/haśle/bazie (1044, 1045, 1049, 1698).
- `tools/backup.sh`: `BACKUP_DIR` (katalog kopii na innym dysku) i ścieżka storage z `STORAGE_DIR` kontenera.
- `docs/wdrozenie.md`: lista kontrolna przeniesienia na nową platformę — kontrakt zmiennych, konfiguracja reverse proxy (limit body ≥ 11 MB, timeouty, `X-Forwarded-*`, HSTS, rate limit `/login` i `/api/`), repliki i migracje, wolumen storage (uid 10001 / `fsGroup`), baza zarządzana, procedura przeniesienia danych z weryfikacją.
- Testy: `PRAGMA foreign_keys=ON` dla SQLite w `tests/conftest.py` — klucze obce są egzekwowane jak na MariaDB/InnoDB (test edytora używał bulk `DELETE` szablonów naruszającego klucze obce); testy na prawdziwej MariaDB dla kolacji `products.code`, blokady migracji i sondy bazy; testy entrypointu dla `DATABASE_URL`, SQLite, `APP_INTERNAL_PORT`/`PORT`, `MIGRATE_ON_START` i blokady.

### Changed
- **BREAKING (compose):** usługa `app` nie dostaje już całego `.env` (`env_file`), tylko zmienne aplikacji wymienione w `docker-compose.yml` (`environment:` z wartościami z `.env`) — `MARIADB_ROOT_PASSWORD` i inne sekrety usługi `db` nie trafiają do kontenera aplikacji. Własne zmienne spoza tej listy trzeba dopisać w compose.
- Entrypoint odmawia startu bez `DATABASE_URL` albo z adresem `sqlite:` (w kontenerze cichy fallback na plik SQLite w `/app` kończył się mylącym „Baza nieosiągalna po 10 próbach”); `chown -R` wolumenu storage tylko, gdy właściciel jest inny niż uid 10001, a jego niepowodzenie to ostrzeżenie (rozstrzyga sonda zapisu).
- `products.code` ma w MariaDB kolację binarną `utf8mb4_bin` (migracja `d2c1e7a94f30`, ponawialna): `ABC-1` i `abc-1` to różne indeksy — jak w SQLite i w testach. Z domyślną `utf8mb4_unicode_ci` import CSV nadpisywał po cichu towar o kodzie różniącym się wielkością liter lub akcentem. `flask db downgrade` nie powiedzie się, gdy kartoteka ma takie pary kodów — najpierw je scal.
- Zależności: `cryptography` w `requirements.txt`/`requirements.lock` (wtyczki uwierzytelniania MariaDB `caching_sha2_password`/`ed25519` w PyMySQL). CI instaluje dokładnie `requirements.lock` na Pythonie 3.12.15 (jak obraz), `pip check`, `pip-audit --strict` na locku, `timeout-minutes`.
- `.env.example`: `APP_INTERNAL_PORT`, `MIGRATE_ON_START`, `MIGRATE_LOCK_TIMEOUT`, `PREFERRED_URL_SCHEME`, `DB_WAIT_ATTEMPTS`, `GUNICORN_CMD_ARGS`, `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`; README: sekcja uruchomienia i kopii, tabela bezpieczeństwa panelu; `.audit/` w `.gitignore` i `.dockerignore`.
- CI uruchamia testy na prawdziwej MariaDB 11.4 (tymczasowy kontener); fixtury MariaDB w `tests/conftest.py`; strażnik nazwy bazy testowej dopasowuje człon `test`; test planu zapytania synchronizacji (EXPLAIN: indeks `ix_documents_api_key_updated`, bez filesort).
- Pomoc: zrzuty mają wymiary (bez skoku układu), osobny tekst alternatywny i wskazówkę o nowej karcie; „Jak to działa” pokazuje pionowy diagram przetwarzania czytelny w kolumnie Pomocy.
- Przykłady integracji (Python, bash, Node, PHP) są uruchamiane w testach wobec prawdziwego serwera HTTP: wysyłka i wynik, duplikat, synchronizacja z plikiem stanu, błąd protokołu bez `next_cursor`.

### Uwagi do aktualizacji
Przed wdrożeniem przeczytaj wpis **BREAKING** w sekcji „Changed”, a przy przenoszeniu na nową platformę — `docs/wdrozenie.md`. Kolejność i pułapki:
1. **Kopia zapasowa przed migracją** — `tools/backup.sh`. `flask db upgrade` (uruchamiany przez `docker/entrypoint.sh` przy starcie kontenera, pod blokadą `GET_LOCK`) wykonuje `ALTER TABLE products MODIFY code … COLLATE utf8mb4_bin` — przebudowę indeksu `products.code`; przy dużej kartotece poza godzinami pracy. Migracja w górę nie może trafić na duplikaty (kolacja binarna rozróżnia więcej kodów, nie mniej), a ponowne uruchomienie po awarii jest bezpieczne. Od tej wersji wyszukiwanie towaru po kodzie w MariaDB rozróżnia wielkość liter i akcenty (jak dotąd w SQLite i testach) — import CSV z kodem w innej wielkości liter tworzy nowy towar zamiast po cichu nadpisać istniejący.
2. **Compose: usługa `app` bez `env_file`** — jeśli `.env` zawiera tylko zmienne z `.env.example`, nic nie trzeba robić: wartości nadal pochodzą z `.env` przez interpolację w `docker-compose.yml`. Własne zmienne spoza tej listy dopisz jako wiersze `environment:` usługi `app`. Sprawdź wynik poleceniem `docker compose config` — w usłudze `app` nie powinno być `MARIADB_ROOT_PASSWORD` ani `MARIADB_PASSWORD`.
3. **Start kontenera** — entrypoint kończy się kodem 1 z komunikatem bez `DATABASE_URL` albo z adresem `sqlite:`, a compose odmawia startu już przy `docker compose up`, gdy w `.env` brak `SECRET_KEY` lub `DATABASE_URL`. Zły użytkownik, hasło lub nazwa bazy nie są już ponawiane 10 razy — kontener kończy się od razu z komunikatem sondy (`Baza: mysql+pymysql://xmlparser:***@db:3306/xmlparser`). Przy kilku replikach startujących naraz migracje wykonuje jedna, pozostałe czekają do `MIGRATE_LOCK_TIMEOUT` (domyślnie 600 s); na platformie z osobnym zadaniem migracji ustaw `MIGRATE_ON_START=0`. Po przeniesieniu wolumenu storage uruchom `docker compose exec app flask check-storage`.
4. **Cofnięcie do v0.5.0** — obraz v0.5.0 nie wystartuje na bazie ze stampem `d2c1e7a94f30` (jego `flask db upgrade` nie zna tej rewizji, więc kontener wpada w pętlę restartów). Przed podmianą obrazu wykonaj na działającym kontenerze v0.6.0 `docker compose exec app flask db downgrade 2eff54106035` (nie powiedzie się, gdy kartoteka ma kody różniące się tylko wielkością liter lub akcentem — najpierw je scal) albo przywróć kopię zapasową. `docker compose run app flask …` nie zadziała (entrypoint ignoruje argumenty i startuje gunicorn) — używaj `exec` na działającym kontenerze.

### Fixed
- Negocjacja (`create_supplier`, `use_supplier`) i „Pobierz plik” przy braku pliku źródłowego w magazynie (utracony wolumen, reset storage) kończyły się 500 — teraz komunikat „Brak pliku źródłowego dokumentu w magazynie plików…” (negocjacja wycofuje transakcję, pobranie wraca do dokumentu). Nieczytelny plik w negocjacji też daje komunikat zamiast 500.
- `use_supplier` z nieprawidłowym `supplier_id` (tekst, liczba spoza zakresu) pokazuje „Nieprawidłowy identyfikator dostawcy.” zamiast surowego komunikatu Pythona.
- API: zapis daty w formacie podstawowym ze strefą bez godziny (`20261011+0200`) jest odrzucany (400) zamiast czytany jako godzina 02:00 UTC — tak jak `2026-10-11+02:00`.
- `tools/screenshots.py`: błąd uruchomienia interpretera serwera albo przeglądarki daje czytelny komunikat i kod wyjścia 2 zamiast tracebacku; testy `server_env()` i trybu `--serve`.
- Przykład bash: brak `curl`/`jq` kończy się czytelnym komunikatem, a plik stanu o złym kształcie — błędem zamiast cichych błędów `jq`.

## [0.5.0] — 2026-10-11

### Added
- Pole `updated_at` w odpowiedziach API (`POST/GET /documents`, lista) — czas ostatniej zmiany statusu lub wyniku dokumentu. Jest ustawiane jawnie (`touch()` w `app/services/pipeline.py`), a nie tylko przez `onupdate` bazy, który nie widzi zmian bez zmiany kolumny: odświeża je każde przetworzenie dokumentu (przyjęcie, `POST /documents/{id}/reprocess`, rozwiązywanie problemów w panelu — także gdy wynik wychodzi taki sam), odrzucenie i przywrócenie. Samo pobranie dokumentu go nie zmienia.
- Synchronizacja przyrostowa w `GET /api/v1/documents` — parametry `updated_since` i `cursor` włączają tryb synchronizacji: filtr `updated_at >= updated_since` (czas jak w `since`: strefa przeliczana na UTC, bez strefy = UTC), sortowanie rosnąco po `(updated_at, id)` ze stronicowaniem keyset i pole `next_cursor` w odpowiedzi (kursor kolejnej strony; `null` = koniec). Klient nie gubi już faktur zatwierdzonych przez operatora po czasie przyjęcia (`since` filtruje po czasie przyjęcia) ani dokumentów ponad limit 500 na stronę. `status` i `since` łączą się z nowymi parametrami; kursor nie przechowuje filtrów (klient powtarza je przy każdej stronie) ani danych wrażliwych, a zakres zawsze wyznacza klucz API z nagłówka. Dostawa „co najmniej raz”: dokument zmieniony w trakcie stronicowania pojawia się ponownie na dalszej stronie z nowym `updated_at`. Błędny `updated_since`, uszkodzony lub niepoprawny składniowo kursor oraz pusta wartość `updated_since=` albo `cursor=` → 400 `bad_request` (pusta wartość nie oznacza braku parametru, więc nie przełącza listy po cichu w tryb zwykły, w którym klient przesunąłby `last_sync` i pominął starsze zmiany). Składniowo poprawny kursor „z zewnątrz” (np. innego klucza) → 200 — ustawia tylko pozycję w zakresie Twojego klucza. Bez `updated_since` i `cursor` lista działa jak dotąd (od najnowszych po `id`, bez `next_cursor`); pusty `status=` i `since=` nadal oznacza brak parametru.
- Indeks `documents (api_key_id, updated_at, id)` dla trybu synchronizacji (migracja `2eff54106035`; ponowne uruchomienie po awarii jest bezpieczne, `flask db downgrade` usuwa indeks).
- Zrzuty ekranu w tematach Pomocy (`/pomoc/<temat>`) z podpisem po polsku: „Jak to działa” (diagram przetwarzania, pulpit po nauczeniu na alfa-1), „Pierwsza faktura dostawcy” (kolejka do wyjaśnienia, widok dokumentu z problemami), „Edytor mapowań”, „Szablony i wersje” (lista szablonów), „Jednostki, aliasy i przeliczniki” (przeliczniki), „Kartoteka i mapowania towarów” (kartoteka), „Statusy i problemy” (problemy w widoku dokumentu) i „REST API” (dokumentacja Swagger). Podgląd ma ograniczoną wysokość, kliknięcie otwiera pełny obraz w nowej karcie (makro `help/_shot.html`). Eksport `tools/export_help.py` przenosi zrzuty do `docs/pomoc/` jako obrazki ze ścieżką do pliku w repozytorium i podpisem kursywą; odnośniki do plików spod `/static/` (np. `openapi.yaml`) prowadzą tam teraz do pliku w repozytorium zamiast do ścieżki w panelu.
- Narzędzie `tools/screenshots.py` — powtarzalne zrzuty ekranu do `app/static/screenshots/` (odświeżane po każdym wydaniu, bo stopka pokazuje wersję) z odizolowanej instancji: świeża SQLite i storage w katalogu tymczasowym, bez `.env` i zmiennych konfiguracji z otoczenia, tylko fikcyjne próbki `demo/samples/`, konto demo z jednorazowym hasłem, serwer w podprocesie na `127.0.0.1` (domyślnie port 18517; port żywego demo 18506 i port zajęty są odrzucane), zatrzymywany po zakończeniu. Playwright (Chromium) to zależność opcjonalna tylko dla narzędzia (`pip install playwright && playwright install chromium`, może być w osobnym venv). Opcje `--only`, `--out`, `--port`, `--app-python`, `--list`; na końcu lista plików i błędy konsoli przeglądarki. Testy bez Playwright pilnują listy stron, plików i odmowy portu demo.

### Changed
- **BREAKING:** `created_at` (i nowe `updated_at`) w odpowiedziach API są teraz w ISO 8601 z jawnym UTC i mikrosekundami (`2026-10-11T06:04:38.312308Z`); dotąd naiwny czas bez strefy — na MariaDB bez ułamka sekund (`2026-10-11T06:04:38`), na SQLite z mikrosekundami (`2026-10-11T06:04:38.312308`). Klient parsujący czas bez strefy może wymagać poprawki (szczegóły w „Uwagach do aktualizacji”).
- Migracja bazy `86ccf8021da9`: `documents.created_at` i `documents.updated_at` jako `DATETIME(6)` (mikrosekundy) w MariaDB — dotąd pełne sekundy, więc wiele dokumentów przyjętych w tej samej sekundzie miało identyczny `updated_at`; dokładniejszy czas przygotowuje stronicowanie listy po `(updated_at, id)`. **`flask db upgrade` przebudowuje tabelę `documents`** — przy dużej bazie wykonaj go po kopii zapasowej (`tools/backup.sh`), poza godzinami pracy. Istniejące wartości zachowują sekundy (`.000000`), indeksy zostają, a ponowne uruchomienie po awarii jest bezpieczne (migracja zmienia tylko kolumny bez precyzji 6). `flask db downgrade` przywraca pełne sekundy i obcina ułamki. SQLite przechowuje mikrosekundy bez zmiany schematu (migracja tylko przesuwa rewizję).
- Pomoc „Integracja z własną aplikacją” i „REST API” opisują synchronizację `updated_since` + `cursor` jako zalecany sposób odbioru zmian statusów (sposób B; odpytywanie po `id` zostaje dla wyniku zaraz po wysyłce): semantyka trybu synchronizacji i `next_cursor`, przykładowe adresy kolejnych stron, dostawa „co najmniej raz” z deduplikacją po `id` i `updated_at`, zalecany algorytm z `last_sync = max(updated_at)` i marginesem bezpieczeństwa 5 minut (zmiany zatwierdzone w bazie w innej kolejności niż ich znaczniki czasu), importem tylko dokumentów, które po pełnym pobraniu nadal mają status `approved`, i odpowiedzią bez pola `next_cursor` traktowaną jako błąd, pusty `updated_since=` / `cursor=` jako błąd 400 i start pełnej synchronizacji od `1970-01-01T00:00:00Z`, kodowanie `+` jako `%2B`. Czas w odpowiedziach opisany w formacie z `Z` (`created_at`, nowe `updated_at`). Usunięto ostrzeżenia o gubieniu zatwierdzeń operatora, pomijanej strefie w `since` i braku stronicowania (została nota historyczna „przed v0.5.0”); nowe punkty listy kontrolnej i „Najczęstszych błędów”, nowe pytanie FAQ „Jak dowiedzieć się, że operator zatwierdził fakturę wysłaną przez API?”.
- OpenAPI (`/api/docs`): parametry `updated_since` i `cursor` oraz doprecyzowane `status`, `since` i `limit` w `GET /documents`, schematy `DocumentSummary` i `DocumentList` (z `next_cursor` tylko w trybie synchronizacji), odpowiedź 400, pola `created_at` i `updated_at` z przykładem formatu czasu; test pilnuje, by pola i parametry w specyfikacji odpowiadały prawdziwemu API.
- Przykłady integracji w Pythonie, PHP, JavaScripcie i powłoce mają tryb `--sync` — jeden przebieg synchronizacji przyrostowej: stan w małym pliku JSON (`last_sync` i przetworzone pary `id` → `updated_at`), stronicowanie kursorem do `next_cursor` = `null` (odpowiedź w ogóle bez pola `next_cursor`, np. z serwera sprzed v0.5.0, przerywa przebieg błędem zamiast uchodzić za ostatnią stronę), margines 5 minut, pomijanie powtórzeń i import tylko dokumentu, który po pełnym pobraniu nadal ma status `approved` (pozycja listy mogła się w międzyczasie zdezaktualizować); parę `id` + `updated_at` zapisują niezależnie od statusu. PHP i Node przy duplikacie wypisują `id` oryginału (jak Python i powłoka). Odpowiedź przykładowa w Pomocy wygenerowana na nowo z prawdziwego API.
- `GET /api/v1/documents` (w obu trybach) nie wczytuje z bazy kolumn, których lista nie zwraca — wyniku kanonicznego i danych roboczych dokumentu (`result`, `overrides`, `draft_rules`, `error`); lżejsze zapytanie przy dużych fakturach, odpowiedź bez zmian.
- README: synchronizacja i format czasu w „API w 30 sekund”, wiersz „Synchronizacja” w tabeli funkcji, link do przewodnika integracji; nowy zrzut ekranu `12-pomoc-integracja.png`, odświeżone `11-api-docs.png` i `08-pomoc.png`.
- README: HTTPS w tailnecie przez `tailscale serve` (`APP_BIND=127.0.0.1`, `TRUSTED_PROXY_COUNT=1`, `SESSION_COOKIE_SECURE=1`, włączenie i wyłączenie); komentarze przy tych zmiennych w `.env.example`.
- Pliki zrzutów ekranu przeniesione z `docs/screenshots/` do `app/static/screenshots/` — jedno źródło dla Pomocy w panelu i README (katalog `docs/` nie trafia do obrazu Docker); w `docs/screenshots/` zostają grafika social preview i źródło diagramu (`diagram-przetwarzania.mmd`, teraz z ustawieniami renderu w nagłówku). README: nowe ścieżki obrazków, a w „Rozwój lokalny” opis narzędzia do zrzutów i polecenie Mermaid CLI (`mmdc`), które odtwarza `diagram-przetwarzania.png`; test pilnuje, by obrazki i odnośniki w README i `docs/pomoc/` wskazywały istniejące pliki. Zrzuty wygenerowane na nowo narzędziem `tools/screenshots.py` (aktualna treść Pomocy, m.in. przewodnika integracji i menu tematów).

### Uwagi do aktualizacji
Przed wdrożeniem przeczytaj wpis **BREAKING** w sekcji „Changed”. Kolejność i pułapki:
1. **Kopia zapasowa przed migracją** — `tools/backup.sh`. `flask db upgrade` (uruchamiany przez `docker/entrypoint.sh` przy starcie kontenera) przebudowuje tabelę `documents` (migracja `86ccf8021da9`; `2eff54106035` jedynie tworzy indeks); aplikacja jest wtedy zatrzymana — `docker compose up -d --build` zatrzymuje stary kontener przed startem nowego.
2. **Format czasu w odpowiedziach API** — przed aktualizacją zależał od bazy: na MariaDB (demo, produkcja) kolumny miały precyzję 0, więc API zwracało `created_at` jako `2026-10-11T06:04:38` (bez ułamka i bez strefy), na SQLite jako `2026-10-11T06:04:38.312308`. Po aktualizacji zawsze `2026-10-11T06:04:38.312308Z` (także nowe `updated_at`). Pułapki po stronie klienta: `datetime.fromisoformat` w Pythonie ≤ 3.10 nie przyjmuje `Z` — zamień `Z` na `+00:00` (tak robi `app/help_examples/integracja.py`); sztywne wzorce formatu (`strptime` z `%Y-%m-%dT%H:%M:%S`, PHP `DateTime::createFromFormat` z `Y-m-d\TH:i:s`) wymagają ułamka sekundy i strefy (`%Y-%m-%dT%H:%M:%S.%f%z`, `Y-m-d\TH:i:s.uP`); porównania tekstowe z wcześniej zapisanymi wartościami przestają działać.
3. **`since` ze strefą jest teraz honorowane** (sekcja „Fixed”) — klienci, którzy sami odejmowali przesunięcie strefy, muszą to usunąć, inaczej okno przesunie się dwukrotnie. Do synchronizacji używaj `updated_since` + `cursor`.
4. **Cofnięcie do v0.4.0** — obraz v0.4.0 nie wystartuje na bazie ze stampem `2eff54106035` (jego `flask db upgrade` nie zna tej rewizji, więc kontener wpada w pętlę restartów). Przed podmianą obrazu wykonaj na działającym kontenerze v0.5.0 `docker compose exec app flask db downgrade e4a1d7c03b52` (ułamki sekund zostaną obcięte) albo przywróć kopię zapasową. `docker compose run app flask …` nie zadziała (entrypoint ignoruje argumenty i startuje gunicorn) — używaj `exec` na działającym kontenerze.

### Fixed
- `GET /api/v1/documents?since=…` uwzględnia strefę czasową: `+02:00`, `-05:00` i `Z` są przeliczane na UTC (dotąd strefa była pomijana przy porównaniu z czasem w bazie, więc `since=2026-10-11T08:00:00+02:00` przesuwał okno o 2 godziny); czas bez strefy i sama data nadal oznaczają UTC. Błędna wartość (także poza zakresem dat po przeliczeniu) daje 400 z przykładami formatu. Parsowanie i formatowanie czasu API jest we wspólnym module `app/api/timeutil.py`.
- Data ze strefą bez godziny (`2026-10-11+02:00`, `2026-10-11-05:00` — forma `xs:date` z UBL) w `since` i `updated_since` daje 400 zamiast cichego przesunięcia okna: `datetime.fromisoformat` przyjmuje dowolny znak jako separator daty i czasu, więc strefa była czytana jako godzina (`2026-10-11+02:00` → 02:00 UTC zamiast północy w strefie +02:00). Po dacie musi stać `T` (także `t`) albo spacja i czas, a separator spacją wymaga pełnego `HH:MM:SS` — dlatego także surowy `+` w adresie (`2026-10-11+02:00` po dekodowaniu to `2026-10-11 02:00`) daje 400. Komunikat błędu podaje pełną postać daty ze strefą (`2026-10-11T00:00:00+02:00`), a nie tylko wskazówkę o `%2B`.
- Testy nie wczytują już lokalnego `.env`, więc lokalne ustawienia (np. `TRUSTED_PROXY_COUNT`) nie zmieniają wyniku testów. `tests/conftest.py` ustawia dwie zmienne: `PYTHON_DOTENV_DISABLED=1` wyłącza `load_dotenv()` w `app/config.py` (ta sama zmienna działa w narzędziach), a `FLASK_SKIP_DOTENV=1` — `flask.cli.load_dotenv`, przez które `.env` czytały podprocesy `python -m flask db …` w testach migracji (przekazywana też jawnie w ich środowisku).

## [0.4.0] — 2026-10-11

### Added
- Temat Pomocy „Integracja z własną aplikacją” (`/pomoc/integracja`, po „REST API”): przewodnik krok po kroku — model działania (synchroniczne przetwarzanie, statusy `approved` / `needs_review` / `duplicate` / `rejected`, brak webhooków), przygotowanie klucza, wysyłka (multipart i surowe body, limit z konfiguracji, kody odpowiedzi), odbiór wyniku (odpytywanie z backoffem, dokładna semantyka `since` / `limit` i jak nie zgubić dokumentów), struktura wyniku na rzeczywistej odpowiedzi API dla próbki `alfa-2.xml`, idempotencja i ponowienia, lista kontrolna wdrożenia i najczęstsze błędy.
- Gotowe przykłady integracji w Pythonie (`requests`), PHP (cURL), JavaScripcie (Node.js 18+) i powłoce (curl + jq) z adresem bieżącej instancji (`app/help_examples/`); testy sprawdzają ich składnię i zgodność przykładowego JSON-a z odpowiedzią API.
- Odnośniki do nowego tematu z „REST API” i spisu Pomocy oraz pytanie FAQ „Jak podłączyć swoją aplikację?”.
- `tools/export_help.py` przenosi język bloku kodu z klasy `language-xxx` do Markdown (`docs/pomoc/integracja.md`).

## [0.3.0] — 2026-10-11

### Added
- Sekcja „Pomoc” w panelu (`/pomoc`, dostępna bez logowania): spis treści z szybkim startem w 5 krokach oraz tematy — jak działa przetwarzanie i „uczenie”, pierwsza faktura dostawcy (negocjacja, „tylko ta faktura” vs „zapamiętaj w szablonie”, przykład alfa-1 → alfa-2), edytor mapowań z opisem wszystkich transformacji z białej listy (argumenty i przykłady wejście → wyjście), szablony i wersje, jednostki/aliasy/przeliczniki (przykład „kart.” → szt ×12), kartoteka i import CSV towarów, statusy i kody problemów, REST API (przykłady curl z adresem bieżącej instancji, kody odpowiedzi, limity) oraz FAQ.
- Rejestr kodów problemów (`app/help_content.py`) z opisem, informacją, czy problem blokuje, i sposobem rozwiązania; tabela w Pomocy z kotwicą dla każdego kodu i filtrem. Test pilnuje, by rejestr obejmował dokładnie kody emitowane przez kod źródłowy (także migracje), a przykłady transformacji dawały opisany wynik.
- Limity w Pomocy (rozmiar pliku, `MAX_LINES`, `MAX_TREE_NODES`, import CSV, lista API, logowanie, sesja) są odczytywane z konfiguracji i stałych aplikacji.
- Link „Pomoc” w menu (zawsze widoczny), link „?” przy każdym problemie w widoku dokumentu prowadzący do jego opisu, link „? Pomoc” na pasku edytora mapowań (nowa karta) i odnośnik na stronie demo.
- Pomoc w Markdown dla GitHuba (`docs/pomoc/`), generowana ze stron panelu skryptem `tools/export_help.py` (uruchom po każdej zmianie treści pomocy); test `tests/test_help_export.py` pilnuje, by pliki były aktualne.

### Changed
- README: opis funkcji, diagram przetwarzania, galeria zrzutów ekranu (`docs/screenshots/`, wyłącznie fikcyjne dane demo), szybki start API i linki do pomocy.

## [0.2.0] — 2026-10-10

Wydanie po audycie bezpieczeństwa i sytuacji brzegowych (AI Council: Security, QA, Backend/DBA, DevOps).

### Uwagi do aktualizacji
Przed wdrożeniem przeczytaj wpisy **BREAKING** w sekcji „Changed”. Kolejność:
1. **Kopia zapasowa przed migracją** — `tools/backup.sh` (kończy się błędem, gdy zrzut bazy lub archiwum storage są puste/niekompletne). Migracja `e4a1d7c03b52` zmienia statusy dokumentów i usuwa zduplikowane aliasy, przeliczniki i mapowania — jedyną drogą powrotu jest kopia.
2. **`.env`:** `DEMO_MODE` ma domyślnie `0` — instancja demo musi ustawić `DEMO_MODE=1`. Port aplikacji jest domyślnie wiązany tylko do `127.0.0.1` — dostęp przez Tailscale wymaga `APP_BIND=<IP tailscale0>`. Wymagane są `MARIADB_PASSWORD` i `MARIADB_ROOT_PASSWORD`.
3. **Migracja** uruchamia się w entrypoincie (`flask db upgrade`); po częściowej awarii na MariaDB ponowny start ją dokańcza.
4. **Ponowne logowanie** — po wdrożeniu wszyscy użytkownicy muszą zalogować się ponownie (nowy token sesji).
5. **Integratorzy API:** dokumenty z problemem `reprocess_required` (dawne duplikaty dokumentu innego klucza API lub panelu) i dokumenty z `ambiguous_number` wymagają `POST /api/v1/documents/{id}/reprocess` (po ewentualnym ustawieniu separatora w szablonie); sprawdź obsługę `vat_rate` jako tekstu (`zw`/`np`/`oo`) i statusu `duplicate` dla wcześniej zatwierdzonych dokumentów.

### Added
- Limity wczytywania konfigurowane z env: `MAX_TREE_NODES` (domyślnie 200 000 węzłów drzewa — elementy, atrybuty, komórki CSV) i `MAX_LINES` (domyślnie 5 000 pozycji). Przekroczenie odrzuca dokument z czytelnym komunikatem po polsku zamiast przeciążać serwer; XML jest parsowany przyrostowo, więc limit przerywa wczytywanie przed załadowaniem całego pliku (SEC-1).
- Problemy z pozycji tego samego rodzaju są łączone w jeden z licznikiem i listą pierwszych 20 numerów pozycji (np. 10 000 × „brak przelicznika dla worek” → 1 problem „dotyczy 10 000 pozycji”); dotyczy braków przelicznika, nieprzypisanych towarów (ten sam kod/nazwa), błędów wartości i niezgodności sum pozycji (EDGE-5).
- CI GitHub Actions: testy oraz kontrola braku `private/` i `.env` w repozytorium (OPS-3).
- `tools/backup.sh` — kopia bazy i storage z retencją; opis odtwarzania w README (OPS-4).
- Healthcheck usługi `app`; `/healthz` sprawdza połączenie z bazą (503 przy awarii, pole `db`) (OPS-7).
- Limity zasobów kontenerów (`APP_MEM_LIMIT`, `APP_CPUS`, `DB_MEM_LIMIT`, `DB_CPUS`) i rotacja logów dockera (OPS-12, OPS-18).
- `requirements.lock` z przypiętymi zależnościami przechodnimi, używany w obrazie (OPS-6).
- Transformacja `decimal` przyjmuje separator dziesiętny jako argument (`{"decimal": ","}` / `{"decimal": "."}`); problem „niejednoznaczna liczba” ma w panelu gotowe podpowiedzi z podglądem obu wariantów (EDGE-11).
- Akcja „Przywróć” w panelu (POST z CSRF) dla dokumentu odrzuconego ręcznie; kto odrzucił, zapisywane jest w nowej kolumnie `documents.rejected_by` (migracja `3c7d2a91e5b4`) (BE-2).
- Mapowanie towaru po znormalizowanej nazwie dla pozycji bez kodu i GTIN (kolumna `product_mappings.supplier_name_norm`, także w CRUD mapowań); pozycja bez kodu, GTIN i nazwy może dostać towar tylko „dla tej faktury” (BE-3/EDGE-3).
- OpenAPI: schematy `Invoice`/`InvoiceLine` (`vat_rate` jako liczba-tekst albo kod `zw`/`np`/`oo`), pola `count` i `line_nos` w `Issue`, odpowiedź 409 dla `reprocess`.
- Limit prób logowania liczony w bazie (tabela `login_attempts`, działa przy wielu workerach): 5 nieudanych prób w 15 min dla pary (e-mail, IP) → blokada tej pary na 15 min; 20 prób z jednego IP na dowolne konta; 50 prób na jedno konto z dowolnych IP w 5 min → krótka blokada konta. Obcy bez hasła nie zablokuje admina logującego się z innego adresu. Próba zapisywana przed sprawdzeniem hasła (równoległe żądania nie omijają limitu), próby zablokowane nie przedłużają blokady. Progi konfigurowalne `LOGIN_*` (SEC-2).
- Nieudane i zablokowane logowania zapisywane w historii (`login_failed`, `login_blocked`) (SEC-2).
- `TRUSTED_PROXY_COUNT` — ProxyFix włączany tylko dla jawnie zaufanych proxy (domyślnie 0) (OPS-8).
- Unikalność w bazie (migracja `e4a1d7c03b52`, najpierw bezpiecznie deduplikuje istniejące dane): klucz faktury `documents.dedupe_key` (sha256 z zakresu — klucz API albo panel — dostawcy, rodzaju dokumentu i znormalizowanego pełnego numeru) — najwyżej jeden „żywy” dokument na fakturę także przy równoległych uploadach; NIP dostawcy; przelicznik na (dostawca, towar, z jednostki) z obsługą „wszyscy” (kolumny zakresu zamiast NULL); alias jednostki — także globalny — po haszu `unit_aliases.alias_key` (zakres + alias po złożeniu wielkości liter, akcentów i spacji; unikat niezależny od kolacji bazy, wyszukiwanie i zapis aliasu używają tego samego klucza) (FR-9); mapowanie towaru po kodzie / GTIN / nazwie (`product_mappings.match_key`); indeks listy dokumentów API (klucz, status, data) (BE-1/EDGE-17, BE-17).
- Blokada optymistyczna w edytorze szablonów: zapis wysyła wersję bazową, a gdy w międzyczasie ktoś zapisał nowszą — komunikat konfliktu (409) zamiast nadpisania (BE-7).
- Problemy `file_missing` (brak pliku źródłowego w magazynie) i `internal_error` (nieoczekiwany błąd przetwarzania) — dokument zostaje zapisany do wyjaśnienia zamiast błędu 500 (BE-9, BE-10).

### Changed
- **BREAKING:** stawki VAT `zw`, `np` (także `np I` / `np II` z KSeF) i `oo` są zachowywane w `invoice.lines[].vat_rate` jako kod stawki — pole nie jest już zawsze liczbą (dawniej `null`); stawka w postaci ułamka (`0,23`) daje ostrzeżenie „prawdopodobnie ułamek, nie procent” (EDGE-10). *Integrator:* parsuj `vat_rate` jako liczbę albo kod tekstowy.
- **BREAKING:** faktura z liczbą pozycji ponad `MAX_LINES` (domyślnie 5 000) lub drzewem ponad `MAX_TREE_NODES` jest odrzucana (`rejected`, problem `too_many_lines` / błąd wczytywania) zamiast przetwarzana (SEC-1). *Integrator:* bardzo duże faktury dziel albo podnieś limity w `.env`.
- **BREAKING:** `issues[].message` problemów zagregowanych dostaje sufiks „Dotyczy N pozycji (nr …)”, a `issues[]` ma nowe pola `count` i `line_nos`; zamiast N osobnych problemów pozycji przychodzi jeden (EDGE-5). *Integrator:* nie porównuj komunikatów dosłownie, licz pozycje z `count`.
- **BREAKING:** `GET /api/v1/suppliers` zwraca tylko dostawców z dokumentów danego klucza, a z `issues[].suggestions` w API usunięto rodzaje `product`, `use_supplier` i `clone_template` (szczegóły w „Security”, SEC-5). *Integrator:* nie polegaj na pełnej kartotece ani tych podpowiedziach.
- **BREAKING:** ta sama faktura wysłana dwoma kluczami API albo kluczem i z panelu nie jest już duplikatem — każdy zakres ma własny oryginał (szczegóły w „Security”, BE-1). *Integrator:* deduplikację między kluczami prowadź po swojej stronie.
- Widok szczegółów dokumentu pokazuje maks. 50 kart problemów, 3 000 wierszy drzewa pliku i 500 pozycji wyniku (pełne dane w JSON) — strona dużej faktury nie ma już dziesiątek MB (EDGE-5).
- Wybór elementu z pozycjami: najpierw ścieżka pozycji z wyuczonych szablonów, potem grupa zawierająca typowe pola pozycji (ilość/cena + inne wg synonimów), dopiero potem najliczniejsza powtarzalna grupa. Synonim `qty` dla ilości (EDGE-4).
- Domyślny `APP_PORT` 18506 w compose (OPS-16).
- Obrazy bazowe przypięte do wersji (python 3.12.15-slim-trixie, mariadb 11.4.13) (OPS-5).
- Entrypoint: migracje z ponawianiem i backoffem; gunicorn z `--max-requests` (restart workerów) (OPS-10, OPS-12).
- **BREAKING:** liczba w formie niejednoznacznej (jeden separator i dokładnie 3 cyfry po nim, np. `1,234` / `1.234`) blokuje dokument problemem `ambiguous_number`, chyba że separator jest ustawiony w transformacji `decimal` albo jednoznacznie wynika z innych wartości tego samego dokumentu; liczby z JSON-a (typ number) są zawsze jednoznaczne (EDGE-11). *Integrator:* dokumenty, które wcześniej przechodziły (np. `1,234` czytane jako 1,234), mogą trafić do `needs_review` — także przy `reprocess` starych dokumentów.
- Waluta normalizowana do kodu ISO 4217 (`zł`/`zl` → PLN, `EURO`/`€` → EUR, `£` → GBP, wielkość liter, spacje); nieznana waluta to problem blokujący (EDGE-21).
- Litery wewnątrz liczby (np. `12a3`, `0.1+0.2`) są błędem zamiast być po cichu usuwane; dopiski waluty/procentu przed lub po liczbie (`£80.50`, `12,50 zł`, `23%`) działają jak dotąd (EDGE-1).
- Dokument jest duplikatem tylko względem wcześniej przyjętego (niższe id), nie-odrzuconego dokumentu; odrzucenie oryginału przelicza wskazujące na niego duplikaty, a „Przywróć” oryginału przywraca późniejszym kopiom status duplikatu (BE-5, EDGE-24).
- NIP/VAT dostawcy zapisywany w postaci znormalizowanej (bez spacji, myślników, kropek); „Utwórz dostawcę” z NIP istniejącego dostawcy podpina istniejącego, a CRUD odrzuca duplikat NIP; identyfikacja wybiera deterministycznie najstarszego dostawcę (BE-11/EDGE-9).
- Faktura korygująca / zaliczkowa (`doc_type` correction, advance, KOR, ZAL…) bez pozycji dostaje ostrzeżenie zamiast problemu blokującego; zwykła faktura bez pozycji nadal jest blokowana (EDGE-19).
- Edytor szablonów wymaga elementu z pozycjami (`line_path`) i prosi o potwierdzenie, gdy nowa wersja usuwa mapowanie pól wymaganych (EDGE-15).
- Przypisanie towaru „tylko dla tej faktury” do zagregowanego problemu obejmuje wszystkie pozycje z tym samym kodem/GTIN/nazwą.
- **BREAKING:** `DEMO_MODE` domyślnie `0` (config i `.env.example`); instancje demo muszą ustawić `DEMO_MODE=1` jawnie (BE-15, OPS-11).
- Strona „O demo” nie pokazuje hasła admina (tylko informację o `ADMIN_PASSWORD`); klucz API demo widoczny tylko dla zalogowanych; reset danych demo tylko dla roli admin (K-1).
- Potwierdzenia usuwania przez atrybut `data-confirm` i `static/app.js`, inicjalizacja Swagger UI w `static/api_docs.js` — bez skryptów inline (SEC-3).
- **BREAKING:** po wdrożeniu wszyscy użytkownicy muszą zalogować się ponownie (nowy format identyfikatora sesji) (SEC-4).
- Wykrywanie duplikatów porównuje znormalizowany pełny numer (wielkość liter, akcenty, białe znaki, spacje wokół „/” i „-”) tak samo na SQLite i MariaDB; rodzaj dokumentu (`doc_type`) jest częścią klucza — korekta o numerze faktury nie jest jej duplikatem (EDGE-31, EDGE-23).
- **BREAKING:** oryginałem faktury jest zawsze żywy dokument o najniższym id w tym samym zakresie (klucz API albo panel): ponowne przetworzenie wcześniejszej kopii, gdy późniejsza jest już zatwierdzona, przenosi na nią status duplikatu (BE-1, BE-5). *Integrator:* wcześniej zatwierdzony dokument klucza może zmienić status na `duplicate` po przetworzeniu wcześniejszej kopii — odświeżaj status przed użyciem.
- Straż „ręcznie odrzucony zostaje odrzucony” działa w samym `process()` — żadna ścieżka (API, panel, negocjacja, edytor, przyszłe wywołania) jej nie omija; odrzucenia automatyczne nadal można przetworzyć ponownie (BE-2).
- **BREAKING:** klucza API z dokumentami nie można usunąć — tylko dezaktywować; dokumenty zachowują powiązanie i pozostają dostępne przez API (BE-18).
- Towaru i jednostki użytych w wynikach lub ręcznych przypisaniach dokumentów nie można usunąć ani zmienić im kodu (BE-14).
- **BREAKING:** migracja `e4a1d7c03b52` porządkuje istniejące dane przed założeniem unikatów: późniejsze żywe kopie tej samej faktury w tym samym zakresie dostają status `duplicate` (z problemem wskazującym oryginał); zduplikowany NIP zostaje u najstarszego dostawcy, u pozostałych jest czyszczony z notatką; z powtórzonych aliasów, przeliczników i mapowań zostaje wiersz, który i tak wybierało wyszukiwanie (alias/mapowanie — najstarszy, przelicznik — najnowszy), reszta jest usuwana. Dokumenty, które v0.1.1 oznaczył jako `duplicate` względem dokumentu z innego zakresu (inny klucz API albo panel), przestają być duplikatami: dostają `needs_review` z blokującym problemem `reprocess_required` („przetwórz ponownie”) — ich status sprzed oznaczenia nie jest odtwarzalny bez ponownego przetworzenia nowymi regułami (FR-8). *Integrator:* po wdrożeniu część dokumentów `approved`/`needs_review` może mieć status `duplicate`, a dawne duplikaty między kluczami — `needs_review` z `reprocess_required`; zsynchronizuj statusy (`GET /api/v1/documents`).
- Reset danych demo w jednej transakcji (błąd = dane nietknięte) razem z wpisem w historii; po udanym resecie usuwane są pliki dokumentów z magazynu (BE-15, SEC-6).

### Fixed
- Faktura z jedną pozycją i inną powtarzalną grupą (raty `TerminPlatnosci`, `AdditionalDocumentReference`, `payments`) nie dostaje już rat jako pozycji; pojedyncza pozycja pod kluczem spoza listy podpowiedzi (np. `products`) jest rozpoznawana (EDGE-4).
- CSV z separatorem grupy GS1 (`\x1d`, także `\x1e`) nie jest już odrzucany jako plik binarny (EDGE-12).
- Notacja wykładnicza (`1e5`, `1.5e-3`, liczby JSON typu `1E5`) jest parsowana poprawnie zamiast zamieniać się po cichu w inną liczbę (`1e5` → 15); dotyczy wartości faktur, przeliczników w CRUD, negocjacji i transformacji `convert` (EDGE-1).
- Liczby ujemne zapisane w nawiasach (`(100,00)`), z minusem typograficznym (U+2212, półpauza) lub z minusem na końcu (`100-`) nie tracą znaku — faktury korygujące nie są już zatwierdzane z wartościami dodatnimi (EDGE-2).
- Dokument kanoniczny nie zawiera „-0” / „-0.00” (EDGE-28).
- Edytor szablonów odrzuca transformację `convert` ze współczynnikiem ≤ 0 lub niejednoznacznym, spójnie z CRUD i negocjacją; transformacja odrzuca taki współczynnik także przy przetwarzaniu (do zmiany znaku służy `negate`) (EDGE-16).
- Przetwarzanie dużych faktur: wyniki słowników (jednostki, przeliczniki, mapowania towarów) zapamiętywane na czas przetworzenia, wolny indeks nowego towaru liczony raz — 4 000 pozycji: ingest 11,3 s → 0,7 s (EDGE-5).
- Ręcznie odrzucony dokument pozostaje odrzucony po `POST /api/v1/documents/{id}/reprocess` (409 `rejected`), po zapisie z edytora, po „Przetwórz ponownie” i po próbie rozwiązania problemu; odrzucenia automatyczne (nieczytelny plik, zbyt wiele pozycji) można przetworzyć ponownie (BE-2/EDGE-6).
- „Zapamiętaj” towar dla pozycji bez kodu i GTIN nie przepina już cudzego mapowania tego dostawcy; pozycja z samym GTIN nie nadpisuje mapowania po kodzie (BE-3/EDGE-3).
- Ponowne dodanie przelicznika dla tego samego dostawcy, towaru i jednostki aktualizuje istniejący zamiast tworzyć duplikat; CRUD odrzuca duplikat, a wyszukiwanie wybiera najnowszy przelicznik (BE-4).
- Przelicznik `1,000` w CRUD i negocjacji to błąd formularza zamiast cichego 1,0.
- Przelicznik z 3 miejscami po przecinku (np. 1,125 kg) daje się wpisać: w polach przelicznika (CRUD, negocjacja, podpowiedź systemu, transformacja `convert` w edytorze) kropka jest zawsze separatorem dziesiętnym (`1.125` → 1,125; `1.000` → 1), a przecinek z dokładnie 3 cyframi (`1,125`) daje komunikat z działającymi formami („wpisz 1.125 albo 1125”). Podpowiedź przelicznika z nazwy towaru („Ser 1125 g”) nie jest już odrzucana przy zapisie. Jedna funkcja `parse_factor` we wszystkich tych miejscach (FR-2).
- Ponowne przetworzenie oryginału nie oznacza go jako duplikatu kopii zatwierdzonej przez „Dopuść duplikat” (BE-5).
- Ręczne przypisanie usuniętego towaru (lub jednostki) nie daje już statusu zatwierdzonego — pozycja dostaje problem blokujący (EDGE-7).
- Porównanie NIP/VAT uwzględnia prefiks kraju: `FR123456789` ≠ `DE123456789`; prefiks pomijany tylko, gdy po jednej stronie go brak (EDGE-8).
- Edytor nie zapisuje pustych reguł `{}` jako aktywnej wersji szablonu (EDGE-15).
- Numer pozycji `0`, ujemny lub większy niż liczba pozycji daje komunikat „Brak pozycji” zamiast trafiać w ostatnią pozycję (EDGE-25).
- Obejście wykrywania duplikatów: dokument przetworzony ponownie po zatwierdzeniu późniejszej kopii tej samej faktury (np. oryginał z nieznanym dostawcą, kopia rozwiązana jako pierwsza) dawał dwie zatwierdzone kopie (BE-1, BE-5).
- Równoległe operacje (ten sam NIP, kod `TOW-nnnn`, mapowanie, przelicznik, numer wersji szablonu) kończą się ponowieniem albo komunikatem zamiast błędu 500 (BE-7, BE-17).
- Wartości dłuższe niż kolumna (CRUD, nazwa klucza API, kody i jednostki zapamiętywane w negocjacji, nazwa szablonu z długiej nazwy dostawcy) dają komunikat walidacji zamiast `DataError`/500 na MariaDB; pola formularzy mają `maxlength` (BE-8/EDGE-18).
- Plik w magazynie zapisywany atomowo z `fsync`; nieudane przyjęcie dokumentu usuwa zapisany przez nie plik; `STORAGE_DIR` sprawdzany przy starcie (niezapisywalny → czytelny błąd zamiast 500 przy pierwszym uploadzie) (BE-9, BE-10).
- Blokada optymistyczna edytora szablonów sprawdza wersję bazową w każdej próbie zapisu, pod blokadą wiersza szablonu (`SELECT … FOR UPDATE` na MariaDB, blokada zapisu na SQLite): wersja zatwierdzona przez innego operatora między kontrolą a zapisem lub przed ponowieniem po konflikcie numeru wersji daje 409 zamiast cichego nadpisania (FR-5).
- Mapowanie towaru różniące się od zapamiętanego tylko wielkością liter, akcentami lub białymi znakami w kodzie (np. `AB  1` / `AB 1`, `ABC` / `abc`), zerami wiodącymi GTIN albo zapisem nazwy jest odnajdywane; „Zapamiętaj” aktualizuje istniejące mapowanie zamiast kończyć się fałszywym komunikatem „zmieniono równocześnie w innym oknie”. Wyszukiwanie i zapis używają tego samego klucza co unikat w bazie (`mapping_key` z jedną normalizacją kodu/GTIN/nazwy) (FR-6).
- Migracja `e4a1d7c03b52` daje się ponowić po częściowej awarii na MariaDB (DDL nietransakcyjny): każdy krok sprawdza istnienie kolumny/indeksu przed utworzeniem, kroki na danych są idempotentne; unikat aliasów nie zależy już od kolacji `utf8mb4_unicode_ci` (wcześniej np. alias ze znakiem zerowej szerokości mógł zatrzymać migrację na `uq_alias_scope`) (FR-9).
- `tools/backup.sh` wykrywa nieudany lub pusty zrzut bazy i archiwum storage (`bash` + `set -euo pipefail`, sprawdzenie `CREATE TABLE` i `Dump completed` w zrzucie, `tar -t` archiwum); przy błędzie usuwa niekompletny katalog kopii i kończy się kodem ≠ 0 zamiast „Kopia zapasowa zapisana” (FR-1).
- Obraz Dockera ustawia `STORAGE_DIR=/data/storage` (bez tej zmiennej w `.env` aplikacja jako nie-root próbowała pisać do `/app/storage`); entrypoint najpierw sprawdza zapisywalność storage (błąd konfiguracji → od razu czytelny komunikat), ponawia tylko błąd połączenia z bazą („Baza niegotowa”), a nieudaną migrację zgłasza raz, bez pętli ponowień (FR-7).

### Security
- DoS przez złożoność kwadratową: wykrywanie grupy pozycji działa w jednym przejściu drzewa, a podpowiedzi mapowań korzystają z indeksu sufiksów ścieżek (rozpoznawanie po samym typie wartości tylko dla pierwszych 1 000 ścieżek). Szeroki JSON 1,15 MB: 35,6 s → 1,0 s; XML 1,5 MB: 162 s → 1,5 s (SEC-1).
- **BREAKING:** port aplikacji domyślnie wiązany tylko do 127.0.0.1 (`APP_BIND`); dostęp przez Tailscale wymaga ustawienia IP w `.env` (OPS-1).
- Kontener aplikacji działa jako użytkownik nie-root (uid 10001); entrypoint naprawia właściciela wolumenu storage (OPS-2).
- Wymagane `MARIADB_PASSWORD` i `MARIADB_ROOT_PASSWORD` w docker-compose (OPS-13).
- Rozszerzony `.dockerignore` (sekrety, testy, dokumentacja, narzędzia poza obrazem) (OPS-14).
- Nagłówki bezpieczeństwa na każdej odpowiedzi: `Content-Security-Policy` (`default-src 'self'`, skrypty tylko z plików, `'unsafe-eval'` wymagany przez Alpine.js, `frame-ancestors 'none'`, `object-src 'none'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` (SEC-3).
- Ciasteczka sesji i „zapamiętaj mnie”: `HttpOnly`, `SameSite=Lax`, `Secure` z env `SESSION_COOKIE_SECURE` (domyślnie 0 — HTTP przez Tailscale); sesja wygasa po 8 h; Flask-Login `session_protection="strong"` (SEC-4, OPS-9).
- Wylogowanie i zmiana hasła unieważniają skopiowane ciasteczka sesji (token sesji `users.session_token` sprawdzany przy każdym żądaniu) (SEC-4).
- API: komunikat o duplikacie dokumentu innego klucza API nie zdradza jego id („duplikat istniejącego dokumentu”) (K-2).
- API `/api/v1/suppliers` zwraca tylko dostawców z dokumentów danego klucza; w odpowiedziach API usuwane są podpowiedzi z kartoteki (towary, inni dostawcy, szablony do sklonowania) (SEC-5).
- ReDoS w parsowaniu liczb: długi tekst z literami przed/po liczbie miał koszt kwadratowy; wartość liczbowa ograniczona do 100 znaków.
- Izolacja kluczy API przy wykrywaniu duplikatów: zakresem jest klucz API dokumentu (dokumenty z panelu mają wspólny zakres „web”). Dokument innego klucza nie może już stać się oryginałem cudzej faktury, zablokować jej jako duplikat ani — przez ponowne przetworzenie, odrzucenie czy „Przywróć” — zmienić statusu dokumentu innego klucza; ta sama faktura wgrana dwoma kluczami jest przyjmowana w obu (zakres jest częścią `dedupe_key`) (BE-1).

## [0.1.1] — 2026-10-10

### Security
- Naprawiono obejście wykrywania duplikatów: numer faktury dłuższy niż 128 znaków był zapisywany w postaci obciętej, ale porównywany w pełnej, więc ponowne wgranie tej samej faktury (innych bajtów) nie było rozpoznawane jako duplikat i dokument można było zatwierdzić dwukrotnie. Numer jest teraz normalizowany (usuwanie białych znaków na brzegach, obcięcie do długości kolumny) jednakowo przy zapisie i przy porównaniu.

## [0.1.0] — 2026-10-10

### Added
- Silnik parsowania niezależny od formatu: XML (w tym KSeF FA(3)-podobny i UBL 2.1), JSON, CSV → drzewo ścieżek.
- Szablony dostawców: reguły „pole ← ścieżka → transformacje”, wersjonowanie, diff, przywracanie.
- Biała lista transformacji (liczby PL/EN, daty, `%`, GS1-128, prefiks AI 01, regex, mapy, przeliczenia).
- Rozpoznawanie dostawcy po NIP/VAT oraz po strukturze pliku (klonowanie szablonu dla nowego dostawcy).
- Słowniki: jednostki, aliasy (np. `pcs` → `szt`), przeliczniki (per dostawca / towar), kartoteka towarów z importem CSV, mapowania towarów dostawców.
- Walidacja sum pozycji i nagłówka, wykrywanie duplikatów.
- Heurystyczne podpowiedzi (synonimy PL/EN/KSeF/UBL, typy wartości, dopasowanie rozmyte) — bez LLM.
- Kolejka „do wyjaśnienia” i kreator negocjacji („tylko ta faktura” / „zapamiętaj”).
- Pełnoekranowy edytor mapowań z podglądem na żywo.
- REST API v1 z kluczami API, OpenAPI i Swagger UI.
- Strona „O demo” z fikcyjnymi próbkami i resetem danych; historia zmian (audyt).
- Zmienna `XP_SUBNET` (jawna podsieć sieci Docker Compose).

### Changed
- Domyślny port hosta `APP_PORT` zmieniony z 5010 na 18506 (kontener nadal nasłuchuje na 5010); panel dostępny przez nazwę MagicDNS Tailscale.

### Fixed
- Gunicorn: workery `gthread` (2 × 8 wątków, timeout 60 s) — bezczynne gniazda przeglądarki nie blokują już obu workerów (`WORKER TIMEOUT`); nadpisanie przez `GUNICORN_CMD_ARGS` (opisane w README).
- Uczenie: dla dostawcy rozpoznanego automatycznie, ale bez szablonu (dostawca założony ręcznie lub zmiana formatu pliku), zapis mapowania w kreatorze i w edytorze tworzy szablon — nauka nie przepada; poprawiono mylący opis „reguły robocze”.
- Pliki binarne (PDF, ZIP, PNG, XLS itd.) są odrzucane jako nieczytelne zamiast być czytane jako CSV; komunikat odróżnia UTF-16/32 bez BOM od danych binarnych.
- Skrajne wartości nie powodują już błędu 500: liczby powyżej 18 cyfr całkowitych dają problem `invalid_value`, wartości dłuższe niż kolumny (numer, typ, nazwa pliku, dostawca) są obcinane, zbyt duży przelicznik jest odrzucany; `resolve` wycofuje transakcję przy każdym wyjątku.
- „Przetwórz ponownie” w panelu nie cofa już ręcznego odrzucenia dokumentu (dozwolone tylko dla dokumentów nieczytelnych).

### Security
- Strażnik danych prywatnych wykrywa też warianty: NIP z prefiksem i separatorami (`PL1234567890`, `123-456-78-90`), nazwy z polskimi znakami (także po zwinięciu diakrytyków i separatorów); testy z syntetycznymi tokenami.

## [0.0.1] — 2026-10-10

### Added
- Szkielet aplikacji Flask, konfiguracja z `.env`, Docker Compose (MariaDB 11.4), `/healthz`.
- Stopka z kredytami i wersją.
- Strażnik danych prywatnych (`tests/test_no_private_data.py`) + hook pre-commit.
- Specyfikacja projektowa i plan etapu 1.

[Unreleased]: https://github.com/AmigoUK/xml-parser/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/AmigoUK/xml-parser/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/AmigoUK/xml-parser/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/AmigoUK/xml-parser/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/AmigoUK/xml-parser/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/AmigoUK/xml-parser/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/AmigoUK/xml-parser/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/AmigoUK/xml-parser/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/AmigoUK/xml-parser/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/AmigoUK/xml-parser/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/AmigoUK/xml-parser/releases/tag/v0.0.1
