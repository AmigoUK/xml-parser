<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Integracja z własną aplikacją

Ten przewodnik prowadzi krok po kroku przez podłączenie Twojego systemu (ERP, magazyn, sklep, skrypt) do parsera: od klucza API, przez wysyłkę faktury i odbiór wyniku, po ponowienia i gotowy kod w czterech językach. Szczegóły każdego endpointu i pełną tabelę kodów odpowiedzi znajdziesz w temacie [REST API](api.md). Adres bazowy tej instancji: `http://localhost:18506/api/v1`.

<a id="model"></a>

## 1. Jak wygląda integracja

Przetwarzanie jest **synchroniczne**: odpowiedź na wysłanie pliku przychodzi dopiero po odczytaniu faktury, więc od razu zawiera `id` dokumentu i jego **ostateczny w tej chwili** status. Status `received` jest tylko stanem przejściowym w trakcie tego żądania.

1. Twoja aplikacja wysyła plik: `POST /api/v1/documents` → `201` z dokumentem.
2. Zapisujesz u siebie `id` — to jedyny trwały identyfikator dokumentu w parserze.
3. Dalej zależy od pola `status`:
   - `approved` — faktura odczytana automatycznie; pole `invoice` zawiera dokument kanoniczny, który importujesz do swojego systemu. Koniec.
   - `needs_review` — są problemy blokujące (najczęściej pierwsza faktura nowego dostawcy). Operator rozwiązuje je w panelu (*Kolejka*), a dokument po każdej decyzji jest przetwarzany ponownie. Ty odpytujesz go później (krok 4), aż status się zmieni.
   - `duplicate` — tę fakturę wysłano już wcześniej tym samym kluczem; użyj wyniku oryginału (rozdział 6).
   - `rejected` — pliku nie da się odczytać albo ma zbyt wiele pozycji (przyczyna jest w `issues`), albo operator odrzucił dokument w panelu.

```text
Twoja aplikacja                          Parser faktur
  POST /api/v1/documents (plik)  ───────►  odczyt → szablon → walidacja
                                 ◄───────  201 {id, status, invoice, issues}
  status = approved      → importujesz invoice
  status = needs_review  → operator rozwiązuje problemy w panelu
  GET /api/v1/documents/{id} (co jakiś czas) ─► aż status ≠ needs_review
  status = approved      → importujesz invoice
```

**Webhooków nie ma.** Parser nie powiadamia Twojej aplikacji o zmianie statusu — o wyniku dowiadujesz się wyłącznie, odpytując API.

<a id="przygotowanie"></a>

## 2. Przygotowanie

- **Utwórz klucz** w panelu: *Klucze API* → nazwa (np. nazwa Twojego systemu) → „Utwórz klucz”. Pełny klucz (zaczyna się od `xp_`) jest pokazywany tylko raz — w bazie zostaje wyłącznie jego skrót. Dla każdego systemu załóż osobny klucz.
- **Przechowuj klucz poza kodem**: w zmiennej środowiskowej (w przykładach `XP_API_KEY`) albo w menedżerze sekretów. Nie wpisuj go do kodu, repozytorium ani logów.
- Klucz wysyłasz w nagłówku `X-API-Key` każdego żądania; brak, zły albo wyłączony klucz → `401`.
- **Zakres klucza**: klucz widzi tylko dokumenty wysłane nim samym — dokument innego klucza zwraca `404`, tak jakby nie istniał. Szablony, dostawcy i kartoteka towarów są wspólne: dostawca nauczony w panelu jest rozpoznawany w fakturach wysłanych każdym kluczem.
- **Duplikaty liczone są w zakresie klucza**: ta sama faktura wysłana dwoma różnymi kluczami (albo raz kluczem, raz przez panel) nie jest duplikatem.

<a id="wysylka"></a>

## 3. Wysyłka faktury

Dwa równoważne sposoby wysłania pliku na `POST http://localhost:18506/api/v1/documents`:

- **multipart/form-data** z polem o nazwie dokładnie `file` (nazwa pliku z formularza zostaje zapisana w dokumencie) — zalecane;
- **surowe body** z nagłówkiem `Content-Type` innym niż formularzowy (np. `application/xml`, `application/json`, `text/csv`) i opcjonalnym `X-Filename` z nazwą pliku (bez niego zapisywana jest nazwa `dokument`).

Format (XML, JSON, CSV) rozpoznawany jest po treści, nie po nazwie ani `Content-Type`. Maksymalny rozmiar pliku na tej instancji: **10 MB**; faktura może mieć najwyżej 5 000 pozycji.

| HTTP | `error.code` | Co zrobić |
| --- | --- | --- |
| 201 | — | dokument przyjęty; sprawdź `status` — także `duplicate` i `rejected` przychodzą jako 201 |
| 400 | `empty_body` | pusty plik, pole formularza o innej nazwie niż `file` albo surowe body wysłane jako formularz (patrz „Najczęstsze błędy”) — popraw żądanie, nie ponawiaj bez zmian |
| 401 | `unauthorized` | sprawdź klucz i czy nie został wyłączony; nie ponawiaj w pętli |
| 413 | `too_large` | plik większy niż 10 MB — nie ponawiaj |
| 500 | `internal_error` | ponów z przerwą (rozdział 6); błędy sieci i odpowiedzi 5xx serwera pośredniczącego traktuj tak samo |

Błędy mają zawsze postać `{"error": {"code": "…", "message": "…"}}`; komunikat (`message`) jest po polsku i nadaje się do logu.

<a id="odbior"></a>

## 4. Odbiór wyniku

Jeżeli wysyłka zwróciła `approved`, wynik masz od razu w odpowiedzi. Dokumenty `needs_review` trzeba sprawdzać później — na dwa sposoby.

### Sposób A (zalecany): odpytywanie po `id`

Trzymaj u siebie listę `id` dokumentów oczekujących i co jakiś czas wywołuj `GET http://localhost:18506/api/v1/documents/{id}`, aż status przestanie być `needs_review`. Rozwiązanie problemów zależy od człowieka, więc może trwać minuty albo dni — zacznij od kilku sekund i podwajaj przerwę do kilku minut (np. 5 s, 10 s, 20 s … maks. 5 min), a po godzinie przenieś dokument do zadania okresowego (np. raz na 15 min). Przykłady kodu poniżej robią dokładnie to.

### Sposób B: lista z filtrem `since`

`GET http://localhost:18506/api/v1/documents?since=…&status=…&limit=…` zwraca dokumenty Twojego klucza w polu `items` — bez `invoice` i `issues` (po pełny wynik sięgnij `GET /documents/{id}`). Dokładna semantyka:

- `since` — dokumenty **przyjęte** (pole `created_at`) w tej chwili lub później (porównanie „≥”). Filtr dotyczy chwili wysłania, **nie chwili zmiany statusu**.
- Czas jest w **UTC bez strefy**: tak zwracane jest `created_at` (np. `2026-10-11T06:04:38.312308`) i tak podawaj `since`. Sama data (`2026-10-11`) oznacza północ UTC. Przesunięcie strefy w `since` (np. `+02:00`) jest pomijane — godzina i tak liczona jest jako UTC — więc zawsze przeliczaj czas na UTC przed wysłaniem.
- `status` — jeden z: `received`, `approved`, `needs_review`, `duplicate`, `rejected`.
- `limit` — domyślnie 100, maks. 500 (większe wartości są obcinane do 500, mniejsze od 1 — podnoszone do 1).
- Kolejność: od najnowszych (malejąco po `id`). **Nie ma stronicowania** (offsetu ani kursora): jeśli od `since` przyjęto więcej dokumentów niż `limit`, dostaniesz tylko najnowsze, a starszych tym zapytaniem nie pobierzesz.

**Jak nie zgubić dokumentów.** Zapytanie `status=approved&since=<ostatnie sprawdzenie>` **pominie** fakturę wysłaną przed ostatnim sprawdzeniem, którą operator zatwierdził później — jej `created_at` się nie zmienia. Dlatego:

- podstawą jest `id` z odpowiedzi na wysyłkę i sposób A;
- listy używaj do uzgadniania: `since` = najstarszy `created_at` wśród Twoich dokumentów wciąż oczekujących (albo np. „7 dni temu”), bez filtra `status`, i porównuj statusy po `id`;
- dokument z `created_at` równym `since` wraca ponownie — odrzucaj powtórzenia po `id`;
- gdy dostaniesz dokładnie `limit` pozycji, mogło ich być więcej — sprawdzaj częściej albo skróć okno.

Status może się zmienić także **po** osiągnięciu statusu końcowego, jeśli operator działa w panelu (np. użyje „Przetwórz ponownie” po zmianie szablonu albo przy duplikacie wybierze „To nie duplikat — przetwórz” lub „Odrzuć”). Jeśli to dla Ciebie ważne, okresowo uzgadniaj statusy dokumentów z ostatnich dni.

<a id="wynik"></a>

## 5. Struktura wyniku

Rzeczywista odpowiedź tej aplikacji dla fikcyjnej próbki demo `alfa-2.xml` (po nauczeniu dostawcy na `alfa-1.xml`), wysłanej jako multipart. Lista `lines` skrócona do pierwszej z dwóch pozycji, stąd sumy w `totals` obejmują też pominiętą pozycję. Klucze są uporządkowane alfabetycznie.

```json
{
  "created_at": "2026-10-11T06:04:38.312308",
  "doc_type": "invoice",
  "filename": "alfa-2.xml",
  "format": "xml",
  "id": 2,
  "invoice": {
    "buyer": {
      "address": {
        "city": "Przykładowo",
        "country": null,
        "postcode": "00-951",
        "street": "ul. Demonstracyjna 2"
      },
      "name": "Piekarnia Demo Sp. z o.o.",
      "tax_id": "PL9990000099"
    },
    "corrected_invoice_number": null,
    "currency": "PLN",
    "delivery_notes": [
      "WZ-ALFA-0002"
    ],
    "doc_type": "invoice",
    "due_date": "2026-10-31",
    "issue_date": "2026-10-10",
    "lines": [
      {
        "batch": "L2607",
        "conversion_factor": "1",
        "expiry_date": "2027-07-15",
        "gross": "75.00",
        "gtin": "05909999000013",
        "line_no": 1,
        "name": "Posypka czekoladowa 1 kg",
        "net": "75.00",
        "product_index": "TOW-0001",
        "qty": "6",
        "supplier_code": "A-100",
        "unit": "szt",
        "unit_price_net": "12.50",
        "unit_source": "pcs",
        "vat": "0.00",
        "vat_rate": "0"
      }
    ],
    "number": "FA/2026/10/002",
    "payment_method": "Przelew",
    "sale_date": null,
    "supplier": {
      "address": {
        "city": "Przykładowo",
        "country": null,
        "postcode": "00-950",
        "street": "ul. Testowa 1"
      },
      "name": "Hurtownia Alfa Sp. z o.o.",
      "tax_id": "PL9990000011"
    },
    "totals": {
      "gross": "96.00",
      "net": "96.00",
      "vat": "0.00"
    }
  },
  "issue_date": "2026-10-10",
  "issues": [],
  "issues_count": 0,
  "number": "FA/2026/10/002",
  "status": "approved",
  "status_label": "Zatwierdzona",
  "supplier": {
    "id": 1,
    "name": "Hurtownia Alfa Sp. z o.o."
  },
  "template_version": 2
}
```

### Dokument (najwyższy poziom)

| Pole | Typ | Znaczenie |
| --- | --- | --- |
| `id` | liczba | identyfikator dokumentu — zapisz go u siebie |
| `status`, `status_label` | tekst | kod statusu i jego polska nazwa ([Statusy i problemy](statusy-i-problemy.md)) |
| `format` | tekst lub `null` | `xml`, `json` albo `csv`; `null`, gdy pliku nie dało się odczytać |
| `filename` | tekst | nazwa pliku z formularza albo z `X-Filename` |
| `number`, `issue_date`, `doc_type` | tekst lub `null` | numer, data wystawienia (`RRRR-MM-DD`) i rodzaj dokumentu — kopia z `invoice` |
| `supplier` | obiekt lub `null` | `{id, name}` dostawcy z kartoteki; `null`, dopóki dostawca nie jest rozpoznany |
| `template_version` | liczba lub `null` | numer wersji szablonu, którą odczytano fakturę |
| `created_at` | tekst | chwila przyjęcia, ISO 8601 w UTC bez strefy |
| `issues_count`, `issues` | liczba, lista | problemy (blokujące i ostrzeżenia); lista tylko w odpowiedzi z pojedynczym dokumentem |
| `invoice` | obiekt lub `null` | dokument kanoniczny; `null` dla dokumentu odrzuconego automatycznie (plik nieczytelny albo zbyt wiele pozycji). Przy `needs_review` może być niepełny — **importuj go wyłącznie przy `approved`** |

### Nagłówek faktury (`invoice`)

| Pole | Typ | Znaczenie |
| --- | --- | --- |
| `number`, `doc_type` | tekst | numer i rodzaj dokumentu (np. `invoice`) |
| `issue_date`, `sale_date`, `due_date` | tekst `RRRR-MM-DD` lub `null` | data wystawienia, sprzedaży i termin płatności |
| `currency` | tekst | kod waluty, np. `PLN` |
| `supplier`, `buyer` | obiekt | `name`, `tax_id` i `address` (`street`, `postcode`, `city`, `country`) — tak jak na fakturze |
| `totals` | obiekt | `net`, `vat`, `gross` — kwoty jako tekst |
| `payment_method`, `corrected_invoice_number` | tekst lub `null` | forma płatności; numer korygowanej faktury (dla korekt) |
| `delivery_notes` | lista tekstów | numery dokumentów dostawy (WZ) |
| `lines` | lista | pozycje — tabela niżej |

### Pozycja (`invoice.lines[]`)

| Pole | Typ | Znaczenie |
| --- | --- | --- |
| `line_no` | liczba | numer pozycji od 1 |
| `supplier_code`, `gtin`, `name` | tekst lub `null` | kod towaru u dostawcy, GTIN/EAN i nazwa z faktury |
| `product_index` | tekst lub `null` | **indeks towaru z Twojej kartoteki** w parserze (np. `TOW-0001`) — po nim łączysz pozycję z towarem w swoim systemie |
| `qty` | tekst dziesiętny | ilość **po przeliczeniu** na jednostkę `unit` |
| `unit` | tekst lub `null` | nasza jednostka (kod ze słownika jednostek), po przeliczeniu na jednostkę bazową |
| `unit_source` | tekst lub `null` | jednostka dokładnie tak, jak zapisał ją dostawca (np. `pcs`, `worek`) |
| `conversion_factor` | tekst dziesiętny | użyty przelicznik; `"1"`, gdy nie przeliczano. Np. 20 worków po 25 kg: `unit_source` = `worek`, `unit` = `kg`, `qty` = `500`, `conversion_factor` = `25`, a cena jednostkowa jest podzielona przez 25 ([Jednostki](jednostki.md)) |
| `unit_price_net` | tekst dziesiętny | cena jednostkowa netto za jednostkę `unit` (2–4 miejsca po kropce) |
| `net`, `vat`, `gross` | tekst dziesiętny | wartości pozycji, zawsze 2 miejsca po kropce |
| `vat_rate` | tekst | stawka w procentach (`"23"`, `"8"`, `"0"`) albo `zw`, `np`, `oo` |
| `batch`, `expiry_date` | tekst lub `null` | partia i data ważności (`RRRR-MM-DD`), np. z kodu GS1 |

**Kwoty i ilości są tekstami** z kropką dziesiętną (`"12.50"`), żeby nie tracić dokładności — w swoim systemie parsuj je typem dziesiętnym (`Decimal`, `BigDecimal`, `bcmath`), nie zmiennoprzecinkowym.

`issues` to lista problemów z polami `code`, `severity` (`blocking` albo `warning`), `message`, `field`, `line_no`, `source_value` i `suggestions`. Przy `approved` mogą zostać ostrzeżenia (np. niezgodna suma pozycji) — warto je zapisać obok faktury. Znaczenie kodów: [Statusy i problemy](statusy-i-problemy.md).

<a id="ponowienia"></a>

## 6. Idempotencja i ponowienia

- **Ponowne wysłanie tej samej faktury** tym samym kluczem tworzy nowy dokument w statusie `duplicate` (odpowiedź `201`). Pierwszy element `issues` ma `code` = `duplicate`, a w `source_value` — `id` oryginału jako tekst, np. `"2"`. Duplikatem jest ten sam plik albo faktura o tym samym dostawcy, rodzaju i numerze, jeśli oryginał jest zatwierdzony lub czeka na wyjaśnienie (dokument odrzucony nie blokuje ponownej wysyłki).
- **Timeout lub zerwane połączenie przy wysyłce**: nie wiesz, czy dokument powstał — po prostu wyślij plik ponownie. Jeśli pierwsze żądanie dotarło, dostaniesz `duplicate` ze wskazaniem oryginału i dalej pracujesz na jego `id`; jeśli nie — normalny nowy dokument. Ponawiaj po błędach sieci i 5xx z rosnącą przerwą; po `400`, `401` i `413` nie ponawiaj bez poprawki.
- **Ponowne przetworzenie** — `POST /api/v1/documents/{id}/reprocess` przetwarza dokument aktywną wersją szablonu i zwraca `200` z aktualnym wynikiem. Zwykle nie jest potrzebne: decyzje operatora w panelu same przetwarzają dokument ponownie. Dokument **odrzucony ręcznie** przez operatora zwraca `409` (`rejected`) — cofa to tylko „Przywróć” w panelu; odrzucenia automatyczne można przetworzyć ponownie.

<a id="przyklady"></a>

## 7. Przykłady kodu

Kompletne programy: wysyłają plik podany w argumencie, czekają na wynik z rosnącą przerwą i wypisują pozycje zatwierdzonej faktury. Adres tej instancji jest już wstawiony; klucz czytany jest ze zmiennej środowiskowej:

```bash
export XP_API_KEY='xp_…'   # Twój klucz z „Klucze API”
```

<a id="przyklad-python"></a>

### Python (requests)

```python
"""Wysyłka faktury do parsera i odbiór dokumentu kanonicznego (Python 3.9+, pakiet requests)."""
import os
import sys
import time

import requests

BASE_URL = "http://localhost:18506/api/v1"
API_KEY = os.environ["XP_API_KEY"]  # klucz trzymaj w zmiennej środowiskowej, nie w kodzie
FINAL = {"approved", "duplicate", "rejected"}  # statusy, na których kończymy odpytywanie


class ApiError(Exception):
    def __init__(self, http_status, code, message):
        super().__init__(f"HTTP {http_status} {code}: {message}")
        self.http_status, self.code = http_status, code


def _call(method, path, retries=4, **kwargs):
    """Żądanie z ponawianiem przy błędach sieci i 5xx; błędy 4xx zgłaszane od razu jako ApiError."""
    delay = 2
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, BASE_URL + path, headers={"X-API-Key": API_KEY},
                                 timeout=60, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == retries:
                raise
        else:
            if r.status_code < 500 or attempt == retries:
                if r.status_code >= 400:
                    try:
                        err = r.json().get("error", {})
                    except ValueError:
                        err = {}
                    raise ApiError(r.status_code, err.get("code", "http_error"), err.get("message", r.text[:200]))
                return r.json()
        time.sleep(delay)
        delay = min(delay * 2, 60)


def send_invoice(path):
    """Wysyła plik (multipart, pole 'file'). Ponowienie po timeoucie jest bezpieczne: ten sam plik
    wysłany drugi raz tym samym kluczem dostaje status 'duplicate' ze wskazaniem oryginału."""
    with open(path, "rb") as fh:
        data = fh.read()  # bajty, nie uchwyt — przy ponowieniu wysyłamy je jeszcze raz
    return _call("POST", "/documents", files={"file": (os.path.basename(path), data)})


def original_id(doc):
    """Dla statusu 'duplicate': id wcześniejszego dokumentu tej samej faktury (albo None)."""
    for issue in doc.get("issues") or []:
        if issue.get("code") == "duplicate" and str(issue.get("source_value") or "").isdigit():
            return int(issue["source_value"])
    return None


def wait_for_result(doc_id, first_delay=5, max_delay=300, timeout=3600):
    """Odpytuje GET /documents/{id}, dopóki dokument czeka na operatora (backoff 5 s → 5 min).
    Zwraca dokument w statusie końcowym albo None po przekroczeniu `timeout` sekund."""
    deadline = time.monotonic() + timeout
    delay = first_delay
    while True:
        doc = _call("GET", f"/documents/{doc_id}")
        if doc["status"] in FINAL:
            return doc
        if time.monotonic() + delay > deadline:
            return None  # zapisz id i sprawdź później (np. z harmonogramu zadań)
        time.sleep(delay)
        delay = min(delay * 2, max_delay)


if __name__ == "__main__":
    doc = send_invoice(sys.argv[1])
    print(f"Dokument #{doc['id']}: {doc['status']} ({doc['status_label']})")
    if doc["status"] == "duplicate":
        print(f"Duplikat dokumentu #{original_id(doc)} — użyj wyniku oryginału.")
    elif doc["status"] not in FINAL:
        doc = wait_for_result(doc["id"]) or doc
    if doc["status"] == "approved":
        invoice = doc["invoice"]  # dokument kanoniczny do zaimportowania w Twoim systemie
        print(invoice["number"], invoice["totals"]["gross"], invoice["currency"])
        for line in invoice["lines"]:
            print(f"  {line['product_index']}: {line['qty']} {line['unit']} × {line['unit_price_net']}")
    elif doc["status"] == "rejected":
        print("Odrzucony:", "; ".join(i["message"] for i in doc["issues"]))
    elif doc["status"] == "needs_review":
        print("Nadal czeka na operatora — sprawdź później.")
```

<a id="przyklad-php"></a>

### PHP (cURL)

```php
<?php
// Wysyłka faktury i odbiór wyniku (PHP 8, rozszerzenie curl).
const BASE_URL = 'http://localhost:18506/api/v1';
const FINAL_STATUSES = ['approved', 'duplicate', 'rejected'];

function xp_call(string $method, string $path, ?array $post = null): array {
    $key = getenv('XP_API_KEY');
    if ($key === false || $key === '') {
        throw new RuntimeException('Ustaw zmienną środowiskową XP_API_KEY');
    }
    $ch = curl_init(BASE_URL . $path);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => ['X-API-Key: ' . $key],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 60,
    ]);
    if ($post !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $post); // tablica z CURLFile => multipart/form-data
    }
    $body = curl_exec($ch);
    if ($body === false) {
        $err = curl_error($ch);
        curl_close($ch);
        throw new RuntimeException("Błąd połączenia: $err"); // sieć/timeout — można ponowić
    }
    $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $data = json_decode($body, true);
    if ($status >= 400) {
        $code = $data['error']['code'] ?? 'http_error';
        $msg = $data['error']['message'] ?? substr($body, 0, 200);
        throw new RuntimeException("HTTP $status $code: $msg", $status);
    }
    return $data;
}

function send_invoice(string $path): array {
    return xp_call('POST', '/documents', ['file' => new CURLFile($path, '', basename($path))]);
}

function wait_for_result(int $id, int $delay = 5, int $maxDelay = 300, int $timeout = 3600): ?array {
    $deadline = time() + $timeout;
    while (true) {
        $doc = xp_call('GET', "/documents/$id");
        if (in_array($doc['status'], FINAL_STATUSES, true)) {
            return $doc;
        }
        if (time() + $delay > $deadline) {
            return null; // zapisz id i sprawdź później
        }
        sleep($delay);
        $delay = min($delay * 2, $maxDelay);
    }
}

$doc = send_invoice($argv[1]);
echo "Dokument #{$doc['id']}: {$doc['status']}\n";
if (!in_array($doc['status'], FINAL_STATUSES, true)) {
    $doc = wait_for_result($doc['id']) ?? $doc;
}
if ($doc['status'] === 'approved') {
    $invoice = $doc['invoice'];
    echo "{$invoice['number']}: {$invoice['totals']['gross']} {$invoice['currency']}\n";
    foreach ($invoice['lines'] as $line) {
        echo "  {$line['product_index']}: {$line['qty']} {$line['unit']}\n";
    }
}
```

<a id="przyklad-javascript"></a>

### JavaScript — Node.js 18+ (fetch, FormData, Blob)

```javascript
// Wysyłka faktury i odbiór wyniku (Node.js 18+: wbudowane fetch, FormData i Blob).
// Uruchom: node faktura.mjs faktura.xml
import { readFile } from "node:fs/promises";
import { basename } from "node:path";

const BASE_URL = "http://localhost:18506/api/v1";
const API_KEY = process.env.XP_API_KEY;
const FINAL = new Set(["approved", "duplicate", "rejected"]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function call(method, path, body) {
  const res = await fetch(BASE_URL + path, {
    method,
    headers: { "X-API-Key": API_KEY },
    body,
    signal: AbortSignal.timeout(60_000),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data.error ?? {};
    throw new Error(`HTTP ${res.status} ${err.code ?? "http_error"}: ${err.message ?? ""}`);
  }
  return data;
}

export async function sendInvoice(path) {
  const form = new FormData();
  form.append("file", new Blob([await readFile(path)]), basename(path));
  return call("POST", "/documents", form);
}

export async function waitForResult(id, { delay = 5, maxDelay = 300, timeout = 3600 } = {}) {
  const deadline = Date.now() + timeout * 1000;
  for (;;) {
    const doc = await call("GET", `/documents/${id}`);
    if (FINAL.has(doc.status)) return doc;
    if (Date.now() + delay * 1000 > deadline) return null; // zapisz id i sprawdź później
    await sleep(delay * 1000);
    delay = Math.min(delay * 2, maxDelay);
  }
}

if (!API_KEY) throw new Error("Ustaw zmienną środowiskową XP_API_KEY");
let doc = await sendInvoice(process.argv[2]);
console.log(`Dokument #${doc.id}: ${doc.status}`);
if (!FINAL.has(doc.status)) doc = (await waitForResult(doc.id)) ?? doc;
if (doc.status === "approved") {
  const { number, totals, currency, lines } = doc.invoice;
  console.log(`${number}: ${totals.gross} ${currency}`);
  for (const line of lines) console.log(`  ${line.product_index}: ${line.qty} ${line.unit}`);
}
```

<a id="przyklad-bash"></a>

### Powłoka — curl i jq

```bash
#!/usr/bin/env bash
# Wysyłka faktury i odbiór wyniku (curl 7.76+ i jq). Użycie: ./faktura.sh faktura.xml
set -euo pipefail
BASE="http://localhost:18506/api/v1"
: "${XP_API_KEY:?Ustaw zmienną środowiskową XP_API_KEY}"
FILE="$1"
DELAY="${DELAY:-5}"          # pierwsza przerwa między odpytaniami (s)
MAX_WAIT="${MAX_WAIT:-3600}"  # ile najdłużej czekać na operatora (s)

resp=$(curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" -F "file=@$FILE" "$BASE/documents") \
  || { echo "Błąd wysyłki: $resp" >&2; exit 1; }
id=$(jq -r '.id' <<<"$resp")
status=$(jq -r '.status' <<<"$resp")
echo "Dokument #$id: $status"

waited=0
while [[ "$status" == "needs_review" || "$status" == "received" ]] && (( waited + DELAY <= MAX_WAIT )); do
  sleep "$DELAY"
  waited=$(( waited + DELAY ))
  DELAY=$(( DELAY * 2 > 300 ? 300 : DELAY * 2 ))
  resp=$(curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" "$BASE/documents/$id") \
    || { echo "Błąd odpytania: $resp" >&2; exit 1; }
  status=$(jq -r '.status' <<<"$resp")
done

case "$status" in
  approved)  jq '.invoice' <<<"$resp" > "faktura-$id.json"; echo "Zapisano faktura-$id.json" ;;
  duplicate) echo "Duplikat dokumentu #$(jq -r '.issues[] | select(.code == "duplicate") | .source_value' <<<"$resp")" ;;
  rejected)  jq -r '.issues[].message' <<<"$resp"; exit 1 ;;
  *)         echo "Nadal czeka na operatora — sprawdź później: GET $BASE/documents/$id" ;;
esac
```

<a id="checklista"></a>

## 8. Lista kontrolna wdrożenia

- Osobny klucz API dla systemu, przechowywany w zmiennej środowiskowej lub menedżerze sekretów.
- Zapisujesz `id` z każdej odpowiedzi `201`, zanim zrobisz cokolwiek dalej.
- Obsługujesz wszystkie statusy: `approved`, `needs_review`, `duplicate`, `rejected`.
- `invoice` importujesz tylko przy `approved`; kwoty parsujesz jako liczby dziesiętne.
- Pozycje łączysz z towarami po `product_index`, a ilość i cenę bierzesz w jednostce `unit`.
- Dokumenty `needs_review` odpytujesz z rosnącą przerwą (sposób A), a listą z `since` w UTC tylko uzgadniasz.
- Ponawiasz po błędach sieci i 5xx; przy `duplicate` przechodzisz na `id` oryginału.
- Ktoś po Twojej stronie wie, że faktury nowych dostawców czekają na operatora w panelu.
- Monitorujesz dostępność usługi przez `GET http://localhost:18506/healthz` (bez klucza).

<a id="bledy"></a>

## Najczęstsze błędy integracji

- **Surowe body bez `Content-Type`**, np. `curl --data-binary @faktura.xml` — curl wysyła wtedy `application/x-www-form-urlencoded`, treść jest traktowana jak formularz i API zwraca `400 empty_body`. Dodaj `-H "Content-Type: application/xml"` albo użyj `-F file=@…`.
- **Pole formularza o innej nazwie** niż `file` (np. `plik`, `invoice`) → `400 empty_body`.
- **Import przy `needs_review`** — `invoice` jest wtedy niepełny (np. bez `product_index` lub `unit`).
- **Lista `status=approved&since=…` jako jedyne źródło** — gubi faktury zatwierdzone przez operatora później (rozdział 4).
- **Czas lokalny w `since`** — przesunięcie strefy jest pomijane; podawaj UTC.
- **Liczby zmiennoprzecinkowe** zamiast dziesiętnych — błędy zaokrągleń w kwotach.
- **Szukanie dokumentu innym kluczem** — każdy klucz widzi tylko swoje dokumenty (`404`).
- **Odpytywanie w ciasnej pętli** — operator potrzebuje minut lub godzin; stosuj rosnącą przerwę.
