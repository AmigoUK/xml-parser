<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# REST API

REST API v1 pozwala innym systemom wysyłać faktury i odbierać wynik w formacie kanonicznym (JSON). Pełna specyfikacja: dokumentacja interaktywna (Swagger) (`/api/docs`) i plik openapi.yaml (`/static/openapi.yaml`). Adres bazowy tej instancji: `http://localhost:18506/api/v1`.

Podłączasz własny system? Zacznij od przewodnika [Integracja z własną aplikacją](integracja.md) — model działania, odbiór wyniku, ponowienia i gotowy kod w Pythonie, PHP, JavaScripcie i powłoce.

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

Odpowiedź `201` zawiera dokument: `id`, `status`, `status_label`, `format`, `filename`, `number`, `issue_date`, `doc_type`, `supplier`, `template_version`, `created_at`, `issues_count`, `invoice` (wynik kanoniczny) i `issues` (problemy). Status `approved` oznacza fakturę odczytaną automatycznie, `needs_review` — czekającą na operatora w panelu.

## Lista dokumentów — `GET /api/v1/documents`

```bash
curl -H "X-API-Key: TWÓJ_KLUCZ" \
  "http://localhost:18506/api/v1/documents?status=approved&since=2026-10-01T00:00:00&limit=50"
```

Filtry (opcjonalne): `status` (jeden ze statusów: `received`, `approved`, `needs_review`, `duplicate`, `rejected`), `since` (data ISO 8601 — dokumenty przyjęte od tej chwili), `limit` (domyślnie 100, maks. 500). Wyniki od najnowszych, w polu `items`, bez `invoice` i `issues`.

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
| 400 | `bad_request` | zły parametr listy (`status`, `since`, `limit`) |
| 401 | `unauthorized` | brak, błędny lub wyłączony klucz API |
| 404 | `not_found` | brak dokumentu (albo dokument innego klucza) lub nieznany adres |
| 405 | `method_not_allowed` | metoda niedozwolona dla adresu |
| 409 | `rejected` | `reprocess` dokumentu odrzuconego ręcznie |
| 413 | `too_large` | plik większy niż 10 MB |
| 500 | `internal_error` | wewnętrzny błąd serwera |

## Limity

- Plik faktury: maks. 10 MB.
- Pozycji na fakturze: maks. 5 000 (więcej — dokument odrzucony z problemem `too_many_lines`).
- Węzłów drzewa: maks. 200 000 (więcej — problem `unreadable`).
- Lista dokumentów: maks. 500 wyników na żądanie.

## Powiadomienia (webhook)

Aplikacja nie wysyła obecnie webhooków. Aby dowiedzieć się o zmianie statusu (np. po rozwiązaniu problemów w panelu), odpytuj `GET /api/v1/documents?since=…` albo `GET /api/v1/documents/{id}` — jak robić to bezpiecznie, opisuje [Integracja z własną aplikacją](integracja.md#odbior).

## Stan usługi

`GET http://localhost:18506/healthz` (bez klucza) zwraca wersję aplikacji i stan połączenia z bazą; przy awarii bazy — 503.
