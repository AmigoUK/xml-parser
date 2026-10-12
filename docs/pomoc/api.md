<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# REST API

REST API v1 pozwala innym systemom wysyłać faktury i odbierać wynik w formacie kanonicznym (JSON). Pełna specyfikacja: dokumentacja interaktywna (Swagger) (`/api/docs`) i plik [openapi.yaml](../../app/static/openapi.yaml). Adres bazowy tej instancji: `http://localhost:18506/api/v1`.

![Swagger UI z listą endpointów REST API v1](../../app/static/screenshots/11-api-docs.png)

*Dokumentacja interaktywna (/api/docs, Swagger UI): endpointy REST API v1 z opisem parametrów i odpowiedzi; przycisk „Authorize” pozwala wpisać klucz API wysyłany w nagłówku X-API-Key.*

Podłączasz własny system? Zacznij od przewodnika [Integracja z własną aplikacją](integracja.md) — model działania, odbiór wyniku i synchronizacja zmian statusów, ponowienia i gotowy kod w Pythonie, PHP, JavaScripcie i powłoce.

## Klucze API

- Klucz tworzysz w panelu: *Klucze API* → nazwa (np. „ERP”) → „Utwórz klucz”. Pełny klucz (zaczyna się od `xp_`) jest pokazywany **tylko raz** — skopiuj go od razu; w bazie przechowywany jest wyłącznie skrót.
- Klucz wysyłasz w nagłówku `X-API-Key` każdego żądania. Brak lub zły klucz → 401.
- Klucz można wyłączyć i włączyć ponownie. Klucza, którym przyjęto dokumenty, nie da się usunąć — można go tylko wyłączyć.
- Klucz widzi **tylko własne dokumenty**: lista, pobranie i ponowne przetworzenie dokumentu innego klucza zwracają 404; lista dostawców zawiera tylko dostawców z dokumentów tego klucza. Duplikaty wykrywane są osobno dla każdego klucza.

W przykładach zamień `TWÓJ_KLUCZ` na swój klucz.

## Wysłanie faktury — `POST /api/v1/documents`

Jako formularz multipart (pole `file`):

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  -F file=@faktura.xml \
  http://localhost:18506/api/v1/documents
```

Albo jako surowe body (nazwę pliku podaj w nagłówku `X-Filename`; format rozpoznawany jest po treści):

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  -H "Content-Type: application/xml" -H "X-Filename: faktura.xml" \
  --data-binary @faktura.xml \
  http://localhost:18506/api/v1/documents
```

Odpowiedź `201` zawiera dokument: `id`, `status`, `status_label`, `format`, `filename`, `number`, `issue_date`, `doc_type`, `supplier`, `template_version`, `created_at`, `updated_at`, `issues_count`, `invoice` (wynik kanoniczny) i `issues` (problemy). Status `approved` oznacza fakturę odczytaną automatycznie, `needs_review` — czekającą na operatora w panelu.

`created_at` to chwila przyjęcia dokumentu, a `updated_at` — chwila ostatniej zmiany statusu lub wyniku (przetworzenie, decyzja operatora w panelu, „Odrzuć”, „Przywróć”, `reprocess`). Oba czasy są w ISO 8601 w UTC z mikrosekundami i `Z`, np. `2026-10-11T06:04:38.312308Z`.

## Lista dokumentów — `GET /api/v1/documents`

Lista ma dwa tryby. **Synchronizacja** — zalecana do odbioru zmian statusów, włącza ją parametr `updated_since` (albo `cursor`):

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  "http://localhost:18506/api/v1/documents?updated_since=2026-10-11T06:00:00Z&status=approved&limit=500"
# kolejna strona: te same parametry i cursor z pola next_cursor poprzedniej odpowiedzi
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  "http://localhost:18506/api/v1/documents?updated_since=2026-10-11T06:00:00Z&status=approved&limit=500&cursor=MjAyNi0xMC0xMVQwNjowNDozOC4zMTIzMDh8Nw"
```

- `updated_since` (ISO 8601) — dokumenty zmienione (`updated_at`) w tej chwili lub później, rosnąco po `updated_at`, a przy równym czasie po `id`.
- `cursor` — wartość `next_cursor` z poprzedniej odpowiedzi; pozostałe parametry powtórz bez zmian (kursor niesie tylko pozycję ostatniego zwróconego dokumentu).
- Odpowiedź: `{"items": [...], "next_cursor": …}`; `next_cursor` = `null` oznacza ostatnią stronę. Pełną synchronizację od początku zaczynasz od `updated_since=1970-01-01T00:00:00Z`.
- Dostawa „co najmniej raz”: dokument zmieniony w trakcie stronicowania wraca na dalszej stronie, a dokument z `updated_at` równym `updated_since` — w kolejnym przebiegu; odrzucaj powtórzenia po `id` i `updated_at`. Algorytm z marginesem bezpieczeństwa i gotowy kod: [Integracja z własną aplikacją](integracja.md#odbior).

**Tryb zwykły** (bez `updated_since` i `cursor`) — od najnowszych (malejąco po `id`), odpowiedź `{"items": [...]}` bez `next_cursor` i bez stronicowania:

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  "http://localhost:18506/api/v1/documents?status=approved&since=2026-10-01T00:00:00Z&limit=50"
```

Filtry wspólne obu trybów (opcjonalne, łączone warunkiem „i”): `status` (jeden ze statusów: `received`, `approved`, `needs_review`, `duplicate`, `rejected`), `since` (ISO 8601 — dokumenty **przyjęte** od tej chwili, po `created_at`; nie widzi późniejszych zmian statusu), `limit` (liczba wyników na żądanie: domyślnie 100, maks. 500). Czas ze strefą (`+02:00`, `Z`) jest przeliczany na UTC, czas bez strefy oznacza UTC, a sama data — północ UTC; znak `+` w adresie zapisz jako `%2B`. Pusty `status=` albo `since=` oznacza brak parametru, ale pusty `limit=`, `updated_since=` albo `cursor=` daje `400` — pomiń taki parametr albo podaj wartość. Wyniki są w polu `items`, bez `invoice` i `issues`.

## Szczegóły dokumentu — `GET /api/v1/documents/{id}`

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  http://localhost:18506/api/v1/documents/42
```

## Ponowne przetworzenie — `POST /api/v1/documents/{id}/reprocess`

```bash
curl -X POST -H "X-API-Key: TWÓJ_KLUCZ" \
  http://localhost:18506/api/v1/documents/42/reprocess
```

Przetwarza dokument aktywną wersją szablonu (np. po rozwiązaniu problemów przez operatora albo po problemie `reprocess_required`). Dokument **odrzucony ręcznie** przez operatora zwraca `409`:

```json
{"error": {"code": "rejected", "message": "Dokument został odrzucony przez operatora — ponowne przetworzenie nie cofa odrzucenia."}}
```

Odrzucenie cofa tylko „Przywróć” w panelu. Odrzucenia automatyczne (plik nieczytelny, zbyt wiele pozycji) można przetworzyć ponownie.

## Dostawcy — `GET /api/v1/suppliers`

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  http://localhost:18506/api/v1/suppliers
```

## Kody odpowiedzi

Błędy mają postać `{"error": {"code": "…", "message": "…"}}`.

| HTTP | `error.code` | Kiedy |
| --- | --- | --- |
| 200 | — | poprawne pobranie lub ponowne przetworzenie |
| 201 | — | faktura przyjęta — także gdy wymaga wyjaśnienia, jest duplikatem albo została odrzucona jako nieczytelna (patrz `status` i `issues`) |
| 400 | `empty_body` | pusty plik / pusta treść żądania |
| 400 | `bad_request` | zły parametr listy (`status`, `since`, `updated_since`, `limit`), uszkodzony `cursor` albo pusty `updated_since=`, `cursor=` lub `limit=` |
| 401 | `unauthorized` | brak, błędny lub wyłączony klucz API |
| 404 | `not_found` | brak dokumentu (albo dokument innego klucza) lub nieznany adres |
| 405 | `method_not_allowed` | metoda niedozwolona dla adresu |
| 409 | `rejected` | `reprocess` dokumentu odrzuconego ręcznie |
| 413 | `too_large` | plik większy niż 10 MB |
| 500 | `internal_error` | wewnętrzny błąd serwera |
| 503 | `storage_unavailable` | nie udało się zapisać pliku w magazynie (pełny dysk, niedostępny wolumen) — ponów później |

## Limity

- Plik faktury: maks. 10 MB.
- Pozycji na fakturze: maks. 5 000 (więcej — dokument odrzucony z problemem `too_many_lines`).
- Węzłów drzewa: maks. 200 000 (więcej — problem `unreadable`).
- Lista dokumentów: maks. 500 wyników na żądanie (w trybie synchronizacji — na stronę).

## Powiadomienia (webhook)

Aplikacja nie wysyła obecnie webhooków (planowane w kolejnej wersji). Aby dowiedzieć się o zmianie statusu (np. po rozwiązaniu problemów w panelu), synchronizuj listę `GET /api/v1/documents?updated_since=…` z kursorem (zalecane) albo odpytuj `GET /api/v1/documents/{id}` — jak robić to bezpiecznie, opisuje [Integracja z własną aplikacją](integracja.md#odbior).

## Stan usługi

`GET http://localhost:18506/healthz` (bez klucza) zwraca wersję aplikacji i stan połączenia z bazą; przy awarii bazy — 503.
