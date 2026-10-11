# Plan napraw API pod integracje (v0.5.0 / v0.6.0)

**Cel:** usunąć braki REST API v1 wykryte przy pisaniu przewodnika `/pomoc/integracja` (v0.4.0), tak aby
system zewnętrzny mógł niezawodnie synchronizować dokumenty bez gubienia zmian statusu.

**Stan wyjściowy:** v0.4.0 (`f1b051c`). Braki są opisane uczciwie w `docs/pomoc/integracja.md` z obejściami.

**Decyzje użytkownika (2026-10-11):**
1. Format czasu w API zmieniamy na ISO 8601 z `Z` (**BREAKING**, opisane w CHANGELOG i Release) — bez pól równoległych.
2. Precyzja czasu sprawdzona na żywej MariaDB demo: `documents.created_at` i `documents.updated_at` to `DATETIME` z `DATETIME_PRECISION = 0` → **migracja na `DATETIME(6)` jest wymagana** (zadanie A3a).
3. Sekrety webhooków przechowywane w bazie (a więc i w `backups/`) — zaakceptowane; udokumentować w README.
4. Plan zacommitowany do repo.

**Podział na dwa wydania:**
- **Etap A → v0.5.0:** synchronizacja przez odpytywanie (mały, niskie ryzyko, bez nowej infrastruktury).
- **Etap B → v0.6.0:** webhooki (nowa tabela, worker, SSRF, UI) — większy, osobno.

---

## Zdiagnozowane problemy

| # | Problem | Gdzie | Skutek dla integratora |
|---|---|---|---|
| P1 | `since` filtruje po `created_at` | `app/api/routes.py:102-107` | `status=approved&since=…` gubi faktury zatwierdzone przez operatora później |
| P2 | `updated_at` istnieje w modelu (`app/models.py:190`, `onupdate=utcnow`), ale API go nie zwraca ani nie filtruje | `doc_to_json` (`routes.py:61`) | brak sposobu, by wykryć zmianę statusu bez odpytywania każdego `id` |
| P3 | Strefa w `since` jest ignorowana — `datetime.fromisoformat()` zwraca czas ze strefą, porównywany z naiwnym UTC w bazie (SQLite porównuje tekst, MariaDB obcina strefę) | `routes.py:105` | `since=…+02:00` przesuwa okno o 2 h |
| P4 | `created_at` zwracany bez strefy (`isoformat()` naiwnego UTC) | `routes.py:66` | klient może zinterpretować czas jako lokalny |
| P5 | Brak stronicowania: `limit` maks. 500, sort malejący po `id`, brak kursora | `routes.py:94-112` | przy > 500 dokumentach w oknie starszych nie da się pobrać |
| P6 | Webhooki tylko w modelu (`ApiKey.webhook_url`, `webhook_secret`), nic ich nie wysyła | `app/models.py:217-218` | integrator musi odpytywać |
| P7 | Przykłady `app/help_examples/` trafiają do obrazu Docker | `app/help_examples/` | kosmetyka — pliki są potrzebne w runtime (renderuje je szablon pomocy); **bez zmian**, tylko notka w CLAUDE.md |

---

## Etap A — synchronizacja przez odpytywanie (v0.5.0)

### Decyzje projektowe
- **Kompatybilność wsteczna:** zachowanie `GET /documents` bez nowych parametrów **bez zmian** (malejąco po `id`, `since` po `created_at`). Nowy tryb włącza parametr `updated_since` lub `cursor`.
- **Czas w odpowiedziach:** `created_at` i nowe `updated_at` w formacie ISO 8601 z jawnym UTC (`2026-10-11T06:04:38.312308Z`). To zmiana formatu → **BREAKING** w CHANGELOG (klient parsujący naiwny czas bez strefy może wymagać korekty; większość parserów ISO przyjmuje `Z`).
- **Parametry czasu:** czas ze strefą jest przeliczany na UTC; czas bez strefy = UTC (jak dotąd); sama data = północ UTC.
- **Stronicowanie keyset** po `(updated_at, id)` rosnąco, kursor nieprzezroczysty (base64url z `updated_at|id`), odpowiedź z `next_cursor` (`null` = koniec). Bez offsetu (offset przy zmianach w trakcie gubi/duplikuje rekordy).
- **Wiarygodność `updated_at`:** `onupdate` działa tylko przy zmianie kolumny w flush. Zmiany statusu (`pipeline.py:328`, `negotiation.py:307`, `negotiation.py:326`) i wyniku zmieniają kolumny, więc są objęte; ale mutacje JSON w miejscu (bez przypisania) nie są wykrywane → jawnie ustawiać `doc.updated_at = utcnow()` w `process()` i akcjach negocjacji (jeden helper `touch(doc)`), test to pilnuje.

### Zadanie A1 — wspólne parsowanie i formatowanie czasu
**Pliki:** utwórz `app/api/timeutil.py`; test `tests/test_api_time.py`.
- `parse_api_datetime(text) -> datetime` (naiwny UTC): przyjmuje `YYYY-MM-DD`, ISO z/bez strefy, z `Z`; przelicza strefę na UTC; błędny format → `ValueError`.
- `format_api_datetime(dt) -> str | None`: naiwny UTC → `…Z`.
- Testy: `2026-10-11` → północ UTC; `2026-10-11T08:00:00+02:00` == `2026-10-11T06:00:00`; `…Z`; naiwny; śmieci → `ValueError`; `None` → `None`.
- **Kryterium:** `since=T+02:00` i `since=T-2h` (bez strefy) zwracają ten sam zbiór dokumentów (test API).

### Zadanie A2 — `updated_at` w odpowiedzi i jego wiarygodność
**Pliki:** `app/api/routes.py` (`doc_to_json`), `app/services/pipeline.py`, `app/services/negotiation.py`, testy `tests/test_api.py`.
- `doc_to_json`: dodaj `updated_at`; oba czasy przez `format_api_datetime`.
- Helper `touch(doc)` wywoływany przy każdej zmianie statusu/wyniku (process, reject, restore, resolve, reprocess).
- Testy: po `resolve` w panelu `updated_at` rośnie, `created_at` stoi; po „Odrzuć” i „Przywróć” rośnie; ponowne pobranie bez zmian nie zmienia `updated_at`.

### Zadanie A3a — precyzja mikrosekund w MariaDB
**Pliki:** `app/models.py`, nowa migracja `migrations/versions/<rev>_czas_mikrosekundy.py` (`down_revision='e4a1d7c03b52'`), test `tests/test_migrations.py`.
- Model: `created_at`/`updated_at` dokumentu jako `db.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")` (SQLite bez zmian).
- Migracja: `ALTER TABLE documents MODIFY created_at DATETIME(6), MODIFY updated_at DATETIME(6)` tylko na dialekcie MySQL/MariaDB (idempotentna — sprawdza `DATETIME_PRECISION` przed zmianą); downgrade przywraca `DATETIME`. Istniejące wartości zachowują sekundy (`.000000`).
- Przed migracją na demo: `./tools/backup.sh`.
- Testy: model na dialekcie MariaDB kompiluje się do `DATETIME(6)`; test z `TEST_MARIADB_URL` — dwa zapisy w tej samej sekundzie mają różne `updated_at` i keyset zwraca oba.

### Zadanie A3 — filtr `updated_since` + kursor
**Pliki:** `app/api/routes.py` (`list_documents`), migracja **nowa** `migrations/versions/<rev>_indeks_documents_updated.py` (indeks `(api_key_id, updated_at, id)`; `down_revision` = migracja z A3a; nie edytować wydanych migracji), testy `tests/test_api.py`.
- Nowe parametry: `updated_since` (filtr `updated_at >=`), `cursor` (kontynuacja), `status` łączy się z obydwoma.
- W trybie `updated_since`/`cursor`: sortowanie `updated_at ASC, id ASC`, warunek keyset `(updated_at, id) > (c_ts, c_id)`, pobranie `limit+1` → `next_cursor`.
- Odpowiedź: `{"items": [...], "next_cursor": "…" | null}`; w trybie starym `next_cursor` nie występuje (zgodność).
- Błędny/podrobiony kursor → 400 `bad_request` (kursor nie zawiera danych wrażliwych; zakres klucza API sprawdzany zawsze z `g.api_key`, więc podmiana kursora nie daje dostępu do cudzych dokumentów).
- Testy:
  - faktura wysłana przed `T`, zatwierdzona po `T` → jest w `updated_since=T&status=approved` (regresja P1);
  - 1 203 dokumenty, `limit=500` → trzy strony, łącznie 1 203 unikalne `id`, ostatnia `next_cursor=null`;
  - zmiana dokumentu w trakcie stronicowania → pojawia się na dalszej stronie, żaden nie ginie;
  - kursor innego klucza API → nie zwraca cudzych dokumentów;
  - remis `updated_at` (ten sam znacznik) → stabilna kolejność po `id`;
  - test na MariaDB (`TEST_MARIADB_URL`): keyset po `(updated_at, id)` przy wielu zapisach w tej samej sekundzie (wymaga A3a).

### Zadanie A4 — OpenAPI, Pomoc, przykłady
**Pliki:** `app/static/openapi.yaml`, `app/templates/help/integracja.html`, `app/templates/help/api.html`, `app/help_examples/*`, `app/help_examples/odpowiedz-zatwierdzona.json`, `docs/pomoc/` (przez `tools/export_help.py`), `tests/test_web_help.py`.
- OpenAPI: nowe parametry, `next_cursor`, `updated_at`, format czasu z `Z`.
- Pomoc „Integracja”: Sposób B przepisany na `updated_since` + `cursor` jako **zalecany** sposób synchronizacji; usunąć ostrzeżenia o P1/P3/P5 (zostawić notę historyczną „przed v0.5.0”).
- Przykłady Python/PHP/Node/bash: dodać funkcję synchronizacji przyrostowej (zapamiętany kursor); PHP i Node wypisują `id` oryginału przy `duplicate` (wyrównanie z Pythonem/bash).
- Ponownie uruchomić wszystkie przykłady na odizolowanej instancji (wzór: skrypt instancji zrzutów — świeża SQLite, `dotenv` wyłączony, tylko `demo/samples/`).
- `.venv/bin/python tools/export_help.py`; test eksportu zielony.

### Zadanie A5 — wydanie v0.5.0
- CHANGELOG: `### Added` (updated_since, cursor, updated_at), `### Changed` (**BREAKING**: czasy z `Z`), `### Fixed` (strefa w `since`).
- Bump `pyproject.toml`, commit `chore(release): v0.5.0 — …`, tag, push, GH Release, kopia `./tools/backup.sh`, migracja na demo (`docker compose up -d --build`), weryfikacja `/healthz` i `GET /api/v1/documents?updated_since=…` przez MagicDNS.

---

## Etap B — webhooki (v0.6.0)

### Decyzje projektowe
- **Zdarzenie:** `document.status_changed` przy przejściu do `approved`, `needs_review`, `duplicate`, `rejected` (zgodnie ze specyfikacją: co najmniej `approved`/`rejected`; pozostałe zwiększają użyteczność). Ładunek: `{event, id, status, previous_status, updated_at, document_url}` — **bez** pełnej faktury (klient dociąga `GET /documents/{id}`; mniejszy ładunek, brak wycieku przy błędnym URL).
- **Podpis:** nagłówki `X-XP-Timestamp`, `X-XP-Signature: sha256=<HMAC-SHA256(secret, timestamp + "." + body)>`, `X-XP-Delivery` (UUID, do deduplikacji po stronie klienta). Okno ważności znacznika 5 min opisane w Pomocy.
- **Niezawodność:** wzorzec outbox — rekord `webhook_deliveries` zapisywany **w tej samej transakcji** co zmiana statusu; osobny worker wysyła i ponawia (backoff 1 min, 5 min, 30 min, 2 h, 12 h; maks. 6 prób), potem `failed`. Dostawa „co najmniej raz” — klient deduplikuje po `X-XP-Delivery`.
- **Worker:** nowa usługa w `docker-compose.yml` (`worker`, ten sam obraz, polecenie `flask webhooks-worker`), pętla z `SELECT … FOR UPDATE SKIP LOCKED` na MariaDB (bez podwójnych wysyłek przy wielu workerach); w SQLite/testach — synchroniczna funkcja `deliver_pending()`.
- **Bezpieczeństwo (SSRF):** tylko `https://` (oraz `http://` gdy `WEBHOOK_ALLOW_HTTP=1`); rozwiązanie DNS i blokada adresów prywatnych/loopback/link-local/metadanych chmury, chyba że host jest na liście `WEBHOOK_ALLOWED_HOSTS` (potrzebne dla tailnetu `100.64.0.0/10`); sprawdzanie adresu **po** rozwiązaniu DNS przy każdej wysyłce (DNS rebinding); bez przekierowań; timeout 5 s; odpowiedź czytana maks. 1 KB.
- **Sekret:** generowany przez system (32 bajty), pokazywany raz przy utworzeniu/rotacji; w bazie przechowywany jawnie (potrzebny do podpisu) — opisać w Protected Files/README, że zrzut bazy zawiera sekrety webhooków.

### Zadanie B1 — model i migracja
- Nowa migracja: tabela `webhook_deliveries` (`id`, `api_key_id`, `document_id`, `event`, `payload` JSON, `status` pending|sent|failed, `attempts`, `next_attempt_at`, `last_error`, `last_status_code`, `created_at`, `sent_at`; indeks `(status, next_attempt_at)`), `down_revision` = migracja z A3.
- Testy migracji w `tests/test_migrations.py` (upgrade/downgrade do poprzedniej rewizji).

### Zadanie B2 — emisja zdarzeń (outbox)
- Hook w miejscach zmiany statusu (`touch(doc)` z A2 → porównanie z poprzednim statusem) tworzy rekord dla klucza API dokumentu, jeśli ma `webhook_url`.
- Dokumenty z panelu (bez `api_key_id`) — brak zdarzeń.
- Testy: zmiana statusu → 1 rekord; brak zmiany → 0; rollback transakcji → 0 rekordów.

### Zadanie B3 — wysyłka, podpis, SSRF, ponowienia
- `app/services/webhooks.py`: `deliver_pending(now)`, `sign(secret, ts, body)`, `validate_target(url)`.
- Testy (z lokalnym serwerem testowym / monkeypatch HTTP): poprawny podpis weryfikowalny przykładową funkcją z Pomocy; 500 → ponowienie wg harmonogramu; 6 porażek → `failed`; `127.0.0.1`, `169.254.169.254`, `10.x`, `[::1]` → odrzucone bez wysyłki; host z `WEBHOOK_ALLOWED_HOSTS` → dozwolony; przekierowanie 302 → porażka.

### Zadanie B4 — worker i Docker
- Komenda CLI `flask webhooks-worker` (pętla, interwał 5 s, łagodne zamknięcie na SIGTERM), usługa `worker` w compose (healthcheck, limity zasobów, rotacja logów, uid 10001 jak `app`).
- Testy `tests/test_ops_scripts.py`: compose zawiera usługę, polecenie poprawne.

### Zadanie B5 — panel i API
- „Klucze API”: pole adresu webhooka (edycja), rotacja sekretu (pokazany raz), przycisk „Wyślij testowe zdarzenie”, lista ostatnich 50 dostaw z wynikiem, „Ponów” dla `failed`.
- Formularze z CSRF, dostęp tylko admin; wpisy w „Historii”.

### Zadanie B6 — Pomoc, OpenAPI, przykłady, wydanie v0.6.0
- Pomoc „Integracja”: sekcja „Webhooki” (zdarzenia, ładunek, weryfikacja podpisu w Python/PHP/Node, deduplikacja, ponowienia, adresy dozwolone); usunąć zdanie „Webhooków nie ma”; FAQ.
- OpenAPI: opis callbacku (`callbacks`/`webhooks` w OpenAPI 3.1 lub opis tekstowy w 3.0).
- Test spójności rejestru kodów problemów nadal zielony; eksport `docs/pomoc/`.
- Wydanie jak w A5 (+ nowa usługa `worker` na demo; weryfikacja testowym webhookiem na odbiorcę w tailnecie dodanym do `WEBHOOK_ALLOWED_HOSTS`).

---

## Ryzyka i otwarte kwestie
- **Migracja `DATETIME(6)`** (A3a): `ALTER TABLE` przebudowuje tabelę `documents` — przy dużej liczbie dokumentów wykonać poza godzinami pracy, po kopii zapasowej. Nawet z mikrosekundami remisy są możliwe, dlatego kursor zawsze zawiera też `id`.
- **BREAKING format czasu** (A2): zdecydowano o zmianie formatu (`Z`); nota w CHANGELOG („Uwagi do aktualizacji”) i w Release.
- **Sekrety webhooków w bazie** (B): zaakceptowane; kopie `backups/` zawierają sekrety — opisać w README (sekcja kopii zapasowych); szyfrowanie kluczem z `.env` ewentualnie jako osobne zadanie w przyszłości.
- **Webhooki z tailnetu** (B): domyślna blokada adresów prywatnych zablokuje `100.x` — wymaga świadomej konfiguracji `WEBHOOK_ALLOWED_HOSTS`.

## Weryfikacja końcowa (każdy etap)
- `.venv/bin/python -m pytest -q` zielone, w tym `tests/test_no_private_data.py` i `tests/test_help_export.py`.
- CI na GitHubie zielone (`tests`, `no-private-files`).
- Przykłady integracji uruchomione na odizolowanej instancji (nigdy na żywym demo; żadnych danych z `private/`).
- Demo po wdrożeniu: `http://<host>.<tailnet>.ts.net:18506/healthz` → nowa wersja.
