<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Integracja z własną aplikacją

Ten przewodnik prowadzi krok po kroku przez podłączenie Twojego systemu (ERP, magazyn, sklep, skrypt) do parsera: od klucza API, przez wysyłkę faktury, odbiór wyniku i synchronizację zmian statusów, po ponowienia i gotowy kod w czterech językach. Szczegóły każdego endpointu i pełną tabelę kodów odpowiedzi znajdziesz w temacie [REST API](api.md). Adres bazowy (przykład — w panelu widzisz adres swojej instancji): `https://parser.example.com/api/v1`.

<a id="model"></a>

## 1. Jak wygląda integracja

Przetwarzanie jest **synchroniczne**: odpowiedź na wysłanie pliku przychodzi dopiero po odczytaniu faktury, więc od razu zawiera `id` dokumentu i jego **ostateczny w tej chwili** status. Status `received` jest tylko stanem przejściowym w trakcie tego żądania.

1. Twoja aplikacja wysyła plik: `POST /api/v1/documents` → `201` z dokumentem.
2. Zapisujesz u siebie `id` — to jedyny trwały identyfikator dokumentu w parserze.
3. Dalej zależy od pola `status`:
   - `approved` — faktura odczytana automatycznie; pole `invoice` zawiera dokument kanoniczny, który importujesz do swojego systemu. Koniec.
   - `needs_review` — są problemy blokujące (najczęściej pierwsza faktura nowego dostawcy). Operator rozwiązuje je w panelu (*Kolejka*), a dokument po każdej decyzji jest przetwarzany ponownie. O zmianie statusu dowiesz się z synchronizacji zmian albo odpytując dokument (rozdział 4).
   - `duplicate` — tę fakturę wysłano już wcześniej tym samym kluczem; użyj wyniku oryginału (rozdział 6).
   - `rejected` — pliku nie da się odczytać albo ma zbyt wiele pozycji (przyczyna jest w `issues`), albo operator odrzucił dokument w panelu.

```text
Twoja aplikacja                                 Parser faktur
  POST /api/v1/documents (plik)         ───────►  odczyt → szablon → walidacja
                                        ◄───────  201 {id, status, invoice, issues}
  status = approved      → importujesz invoice
  status = needs_review  → operator rozwiązuje problemy w panelu
  GET /api/v1/documents?updated_since=… ───────►  dokumenty zmienione od ostatniego przebiegu
  (cyklicznie; kolejne strony z cursor) ◄───────  {items, next_cursor}
  status = approved      → GET /api/v1/documents/{id} → importujesz invoice
```

**Webhooków nie ma** (planowane w kolejnej wersji). Parser nie powiadamia Twojej aplikacji o zmianie statusu — o wyniku dowiadujesz się wyłącznie z API: synchronizacją zmian albo odpytując dokument (rozdział 4).

<a id="przygotowanie"></a>

## 2. Przygotowanie

- **Utwórz klucz** w panelu: *Klucze API* → nazwa (np. nazwa Twojego systemu) → „Utwórz klucz”. Pełny klucz (zaczyna się od `xp_`) jest pokazywany tylko raz — w bazie zostaje wyłącznie jego skrót. Dla każdego systemu załóż osobny klucz.
- **Przechowuj klucz poza kodem**: w zmiennej środowiskowej (w przykładach `XP_API_KEY`) albo w menedżerze sekretów. Nie wpisuj go do kodu, repozytorium ani logów.
- Klucz wysyłasz w nagłówku `X-API-Key` każdego żądania; brak, zły albo wyłączony klucz → `401`.
- **Zakres klucza**: klucz widzi tylko dokumenty wysłane nim samym — dokument innego klucza zwraca `404`, tak jakby nie istniał. Szablony, dostawcy i kartoteka towarów są wspólne: dostawca nauczony w panelu jest rozpoznawany w fakturach wysłanych każdym kluczem.
- **Duplikaty liczone są w zakresie klucza**: ta sama faktura wysłana dwoma różnymi kluczami (albo raz kluczem, raz przez panel) nie jest duplikatem.

<a id="wysylka"></a>

## 3. Wysyłka faktury

Dwa równoważne sposoby wysłania pliku na `POST https://parser.example.com/api/v1/documents`:

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
| 503 | `storage_unavailable` | magazyn plików chwilowo niedostępny (dokument nie powstał) — ponów z przerwą jak przy 500 |

Błędy mają zawsze postać `{"error": {"code": "…", "message": "…"}}`; komunikat (`message`) jest po polsku i nadaje się do logu.

<a id="odbior"></a>

## 4. Odbiór wyniku

Jeżeli wysyłka zwróciła `approved`, wynik masz od razu w odpowiedzi. Dokumenty `needs_review` zmieniają status później — po decyzjach operatora w panelu, które mogą zająć minuty albo dni. Wynik odbierasz na dwa sposoby: synchronizacją zmian (sposób B, zalecany) albo odpytując pojedynczy dokument (sposób A — gdy wynik jest potrzebny zaraz po wysyłce).

<a id="sposob-a"></a>

### Sposób A: odpytywanie po `id` — natychmiastowy wynik

Gdy wynik jest potrzebny od razu (np. użytkownik czeka na ekranie), wywołuj `GET https://parser.example.com/api/v1/documents/{id}`, aż status przestanie być `needs_review`. Zacznij od kilku sekund i podwajaj przerwę do kilku minut (np. 5 s, 10 s, 20 s … maks. 5 min). Rozwiązanie problemów zależy od człowieka — jeśli po godzinie dokument nadal czeka, zostaw go synchronizacji (sposób B), która jednym przebiegiem obejmuje wszystkie oczekujące dokumenty. Tak działają przykłady kodu poniżej uruchomione z plikiem faktury.

<a id="synchronizacja"></a>

### Sposób B (zalecany do synchronizacji): `updated_since` + `cursor`

`GET https://parser.example.com/api/v1/documents?updated_since=…` zwraca dokumenty Twojego klucza, które **zmieniły się** w podanej chwili lub później — także przyjęte dawno, a zatwierdzone przez operatora dopiero teraz. Pozycje listy (`items`) nie zawierają `invoice` ani `issues`; pełny wynik pobierasz przez `GET /documents/{id}`. Dokładna semantyka:

- `updated_since` — dokumenty, których `updated_at` jest równe podanemu czasowi lub późniejsze (porównanie „≥”). `updated_at` zmienia każde przetworzenie dokumentu (przyjęcie, decyzja operatora w panelu, „Przetwórz ponownie”, `reprocess` przez API) — także gdy wynik wyszedł taki sam — oraz „Odrzuć” i „Przywróć” w panelu. Samo pobranie dokumentu go nie zmienia.
- Kolejność: rosnąco po `updated_at`, a przy równym czasie po `id` — najpierw dokumenty zmienione najdawniej.
- `next_cursor` — odpowiedź ma postać `{"items": [...], "next_cursor": …}`. Gdy wyników jest więcej niż `limit`, `next_cursor` zawiera kursor kolejnej strony: pobierasz ją z **tymi samymi** parametrami (`updated_since`, `status`, `limit`) i dodatkowo `cursor=<next_cursor>`. `null` oznacza ostatnią stronę.
- Kursor to nieprzezroczysty token: wskazuje pozycję ostatniego zwróconego dokumentu — nie odczytuj go i nie składaj sam. Nie przechowuje filtrów (dlatego powtarzasz je przy każdej stronie) ani danych wrażliwych, a zakres zawsze wyznacza klucz z nagłówka `X-API-Key`. Uszkodzony kursor → `400 bad_request`.
- `status` — jeden z: `received`, `approved`, `needs_review`, `duplicate`, `rejected`. Z `status=approved` dostajesz dokumenty zatwierdzone, także przez operatora później. Bez `status` przychodzą wszystkie zmiany, również `needs_review`, `duplicate` i `rejected` (np. do raportowania).
- `limit` — liczba wyników na stronę: domyślnie 100, maks. 500 (większe wartości są obcinane do 500, mniejsze od 1 — podnoszone do 1). Pusty `limit=` daje `400` — pomiń go albo podaj liczbę.
- Czas podajesz w ISO 8601: czas ze strefą (`+02:00`, `Z`) jest przeliczany na UTC, czas bez strefy oznacza UTC, a sama data (`2026-10-11`) — północ UTC. **Znak `+` zapisz w adresie jako `%2B`** — surowy `+` w URL oznacza spację i API zwróci `400`; najprościej podawaj czas w UTC z `Z`, tak jak zwraca go API. Błędny format → `400 bad_request`.
- Pusty `updated_since=` albo `cursor=` (bez wartości) daje `400 bad_request`, tak samo jak pusty `limit=` (wyżej) — przypadkowo pusta wartość nie przełącza listy po cichu w tryb zwykły (od najnowszych, bez `next_cursor`). Pusty `status=` i `since=` oznacza brak parametru. Pełną synchronizację od początku zaczynasz jawną wartością: `updated_since=1970-01-01T00:00:00Z` (albo datą wdrożenia integracji), a `cursor` na pierwszej stronie pomijasz.

Kolejne strony jednego przebiegu (wartości przykładowe):

```text
GET https://parser.example.com/api/v1/documents?updated_since=2026-10-11T06:00:00Z&status=approved&limit=500
→ {"items": [… 500 dokumentów …], "next_cursor": "MjAyNi0xMC0xMVQwNjowNDozOC4zMTIzMDh8Nw"}
GET https://parser.example.com/api/v1/documents?updated_since=2026-10-11T06:00:00Z&status=approved&limit=500&cursor=MjAyNi0xMC0xMVQwNjowNDozOC4zMTIzMDh8Nw
→ {"items": [… reszta …], "next_cursor": null}
```

**Dostawa „co najmniej raz”.** Ten sam dokument może przyjść więcej niż raz:

- dokument zmieniony w trakcie stronicowania pojawia się ponownie na dalszej stronie, z nowym `updated_at`;
- dokument z `updated_at` równym `updated_since` wraca w kolejnym przebiegu;
- margines bezpieczeństwa (niżej) celowo pobiera ponownie dokumenty z ostatnich minut.

Odrzucaj powtórzenia po `id` i `updated_at` (para już przetworzona — pomiń) i importuj idempotentnie, np. aktualizuj rekord o danym `id` zamiast dopisywać nowy. Samo `id` nie wystarczy: ten sam dokument z nowszym `updated_at` to późniejsza zmiana (np. ponowne przetworzenie z poprawionym wynikiem), którą trzeba zaimportować.

**Zalecany algorytm** (tak działa synchronizacja w przykładach kodu — argument `--sync`):

1. **Stan**: trzymaj u siebie `last_sync` — największy `updated_at` spośród odebranych dokumentów — oraz już przetworzone pary `id` + `updated_at` z ostatnich minut. Bez stanu (pierwszy przebieg) zacznij od `1970-01-01T00:00:00Z` albo od daty wdrożenia integracji.
2. **Początek przebiegu**: `updated_since = last_sync − 5 min` (margines bezpieczeństwa).
3. **Strony**: `GET /api/v1/documents?updated_since=…&status=approved&limit=500`, potem te same parametry z `cursor=<next_cursor>`, aż `next_cursor` będzie `null`. Odpowiedź w ogóle bez pola `next_cursor` (brak, a nie `null`) oznacza tryb zwykły listy (np. serwer sprzed v0.5.0) — przerwij przebieg błędem, nie traktuj jej jak ostatniej strony.
4. **Każda strona**: pomiń pary już przetworzone; pozostałe dokumenty pobierz w całości (`GET /documents/{id}`) i zaimportuj te, które nadal mają status `approved` — pozycja listy mogła się w międzyczasie zdezaktualizować (ponowne przetworzenie, odrzucenie, duplikat). Pary zapamiętaj niezależnie od statusu.
5. **Po stronie**: zapisz `last_sync = max(updated_at)` odebranych dokumentów — nie „teraz”: liczy się czas serwera, a zegar Twojej aplikacji nie ma znaczenia. Pary starsze niż `last_sync − 5 min` możesz zapomnieć — już nie wrócą.

**Dlaczego margines 5 minut.** `updated_at` jest nadawane w chwili zmiany, zanim baza zatwierdzi transakcję. Dwie równoległe zmiany mogą zostać zatwierdzone w odwrotnej kolejności niż ich znaczniki czasu — dokument z wcześniejszym `updated_at` staje się wtedy widoczny dopiero po dokumencie z późniejszym. Gdyby kolejny przebieg zaczynał się dokładnie od `last_sync`, taki dokument zostałby pominięty. Zaczynając od `last_sync − 5 min`, pobierzesz go w następnym przebiegu, a powtórzenia z tego okna odrzucisz po `id` i `updated_at`.

Status może się zmienić także **po** osiągnięciu statusu końcowego, jeśli operator działa w panelu (np. użyje „Przetwórz ponownie” po zmianie szablonu albo przy duplikacie wybierze „To nie duplikat — przetwórz” lub „Odrzuć”). Każda taka zmiana przesuwa `updated_at`, więc synchronizacja ją dostarczy. Z `status=approved` zobaczysz dokument, który **stał się** zatwierdzony, ale nie ten, który przestał nim być — jeśli to dla Ciebie ważne, synchronizuj bez filtra `status` i porównuj statusy po `id`.

**Lista bez `updated_since` i `cursor`** (tryb zwykły) działa jak dotąd: `since` filtruje po czasie **przyjęcia** (`created_at`, porównanie „≥”), wyniki są od najnowszych (malejąco po `id`), bez `next_cursor` i bez stronicowania. Do synchronizacji się nie nadaje: faktura przyjęta wcześniej, a zatwierdzona przez operatora później, nie spełni warunku `since`. W trybie synchronizacji `since` też działa (warunek „i”), ale nie jest potrzebne.

Przed v0.5.0 lista filtrowała tylko po czasie przyjęcia (`since`), nie miała kursora, a strefa w `since` była pomijana — jeśli integrowałeś się ze starszą wersją, przejdź na `updated_since` + `cursor`.

<a id="wynik"></a>

## 5. Struktura wyniku

Rzeczywista odpowiedź tej aplikacji dla fikcyjnej próbki demo `alfa-2.xml` (po nauczeniu dostawcy na `alfa-1.xml`), wysłanej jako multipart. Lista `lines` skrócona do pierwszej z dwóch pozycji, stąd sumy w `totals` obejmują też pominiętą pozycję. Klucze są uporządkowane alfabetycznie.

```json
{
  "created_at": "2026-10-11T09:02:02.963526Z",
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
  "template_version": 2,
  "updated_at": "2026-10-11T09:02:02.978167Z"
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
| `created_at` | tekst | chwila przyjęcia dokumentu — ISO 8601 w UTC z mikrosekundami i `Z`, np. `2026-10-11T06:04:38.312308Z`; po niej filtruje `since` |
| `updated_at` | tekst | chwila ostatniej zmiany statusu lub wyniku (przetworzenie, decyzja operatora, „Odrzuć”, „Przywróć”, `reprocess`), ten sam format; po niej filtruje `updated_since` (rozdział 4) |
| `issues_count`, `issues` | liczba, lista | problemy (blokujące i ostrzeżenia); lista tylko w odpowiedzi z pojedynczym dokumentem |
| `invoice` | obiekt lub `null` | dokument kanoniczny; `null` dla dokumentu odrzuconego automatycznie (plik nieczytelny albo zbyt wiele pozycji). Przy `needs_review` może być niepełny — **importuj go wyłącznie przy `approved`** |

Czas w odpowiedziach ma zawsze ten sam format: UTC, 6 cyfr ułamka sekundy i `Z`. Parsuj go jako czas ze strefą, a `updated_at` do synchronizacji zapamiętuj jako tekst — po zamianie na `Date` w JavaScripcie stracisz mikrosekundy.

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
- **Import z synchronizacji** (sposób B) musi być idempotentny: ten sam dokument może przyjść więcej niż raz (rozdział 4), więc zapisuj go po `id` — aktualizacja zamiast dopisania.
- **Ponowne przetworzenie** — `POST /api/v1/documents/{id}/reprocess` przetwarza dokument aktywną wersją szablonu i zwraca `200` z aktualnym wynikiem. Zwykle nie jest potrzebne: decyzje operatora w panelu same przetwarzają dokument ponownie. Dokument **odrzucony ręcznie** przez operatora zwraca `409` (`rejected`) — cofa to tylko „Przywróć” w panelu; odrzucenia automatyczne można przetworzyć ponownie.

<a id="przyklady"></a>

## 7. Przykłady kodu

Kompletne programy w dwóch trybach. Z plikiem w argumencie wysyłają go, czekają na wynik z rosnącą przerwą (sposób A) i wypisują pozycje zatwierdzonej faktury, a przy duplikacie — `id` oryginału. Z argumentem `--sync` wykonują jeden przebieg synchronizacji (sposób B): stan (`last_sync` i przetworzone pary) trzymają w pliku `xp-sync.json` albo w pliku podanym po `--sync`, stronicują kursorem i wypisują `id`, status i `updated_at` nowych lub zmienionych dokumentów. Synchronizację uruchamiaj cyklicznie, np. co 5 minut z harmonogramu zadań. Adres tej instancji jest już wstawiony; klucz czytany jest ze zmiennej środowiskowej:

```bash
export XP_API_KEY='xp_…'   # Twój klucz z „Klucze API”
python3 faktura.py faktura.xml   # wysyłka i odbiór wyniku (sposób A)
python3 faktura.py --sync        # jeden przebieg synchronizacji (sposób B)
```

<a id="przyklad-python"></a>

### Python (requests)

```python
"""Wysyłka faktury do parsera, odbiór dokumentu kanonicznego i synchronizacja zmian (Python 3.9+, pakiet requests).

Użycie:  python3 faktura.py faktura.xml       — wysyłka i odbiór wyniku (sposób A)
         python3 faktura.py --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

BASE_URL = "https://parser.example.com/api/v1"
API_KEY = os.environ["XP_API_KEY"]  # klucz trzymaj w zmiennej środowiskowej, nie w kodzie
FINAL = {"approved", "duplicate", "rejected"}  # statusy, na których kończymy odpytywanie
SYNC_START = "1970-01-01T00:00:00Z"  # pierwszy przebieg: pełna synchronizacja (albo data wdrożenia integracji)
SYNC_MARGIN = timedelta(minutes=5)  # zapas na zmiany zatwierdzone w bazie w innej kolejności niż ich updated_at


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


def _minus_margin(api_time):
    """'2026-10-11T06:04:38.312308Z' minus SYNC_MARGIN, w tym samym formacie (fromisoformat < 3.11 nie zna 'Z')."""
    t = datetime.fromisoformat(api_time.replace("Z", "+00:00")) - SYNC_MARGIN
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sync_approved(state_path="xp-sync.json"):
    """Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego
    przebiegu. Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id → updated_at.
    Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id)."""
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        state = {"last_sync": None, "seen": {}}
    since = _minus_margin(state["last_sync"]) if state["last_sync"] else SYNC_START
    params = {"updated_since": since, "status": "approved", "limit": 500}
    while True:
        page = _call("GET", "/documents", params=params)
        if "next_cursor" not in page:  # brak pola (a nie null) to tryb zwykły listy, a nie ostatnia strona
            raise RuntimeError("Błąd protokołu: odpowiedź bez pola next_cursor (serwer sprzed v0.5.0?) — "
                               "synchronizacja przerwana.")
        for item in page["items"]:
            if state["seen"].get(str(item["id"])) == item["updated_at"]:
                continue  # już przetworzony: powtórka z marginesu albo z granicy updated_since
            doc = _call("GET", f"/documents/{item['id']}")  # pełny wynik z invoice
            invoice = doc["invoice"] or {}
            print(f"#{doc['id']} {doc['status']} {item['updated_at']} {invoice.get('number') or ''}")
            # importuj tylko approved — pozycja listy mogła się zdezaktualizować (reprocess, odrzucenie, duplikat)
            if doc["status"] == "approved":
                pass  # tu zaimportuj doc["invoice"] do swojego systemu — idempotentnie (aktualizacja rekordu po id)
            state["seen"][str(item["id"])] = item["updated_at"]  # parę zapisz niezależnie od statusu
            # czas zawsze w formacie API (6 cyfr ułamka i Z), więc porównanie tekstów = porównanie czasu
            state["last_sync"] = max(state["last_sync"] or "", item["updated_at"])
        if state["last_sync"]:  # pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
            cutoff = _minus_margin(state["last_sync"])
            state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
        with open(state_path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(state_path + ".tmp", state_path)  # stan po każdej stronie; zapis atomowy
        if page["next_cursor"] is None:
            return state
        params["cursor"] = page["next_cursor"]  # kolejna strona: te same parametry + kursor


if __name__ == "__main__":
    if sys.argv[1] == "--sync":
        sync_approved(*sys.argv[2:3])
        sys.exit(0)
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
// Wysyłka faktury, odbiór wyniku i synchronizacja zmian (PHP 8, rozszerzenie curl).
// Użycie: php faktura.php faktura.xml        — wysyłka i odbiór wyniku (sposób A)
//         php faktura.php --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
const BASE_URL = 'https://parser.example.com/api/v1';
const FINAL_STATUSES = ['approved', 'duplicate', 'rejected'];
const SYNC_START = '1970-01-01T00:00:00Z'; // pierwszy przebieg: pełna synchronizacja (albo data wdrożenia)
const SYNC_MARGIN = '-5 minutes';          // zapas na zmiany zatwierdzone w innej kolejności niż ich updated_at

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

// Dla statusu 'duplicate': id wcześniejszego dokumentu tej samej faktury (albo null).
function original_id(array $doc): ?int {
    foreach ($doc['issues'] ?? [] as $issue) {
        if ($issue['code'] === 'duplicate' && ctype_digit((string) ($issue['source_value'] ?? ''))) {
            return (int) $issue['source_value'];
        }
    }
    return null;
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

// Czas API ('2026-10-11T06:04:38.312308Z') przesunięty o SYNC_MARGIN, w tym samym formacie.
function minus_margin(string $apiTime): string {
    return (new DateTimeImmutable($apiTime))->modify(SYNC_MARGIN)->format('Y-m-d\TH:i:s.u\Z');
}

// Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego przebiegu.
// Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id => updated_at.
// Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id).
function sync_approved(string $statePath = 'xp-sync.json'): void {
    $state = is_file($statePath)
        ? json_decode(file_get_contents($statePath), true, 512, JSON_THROW_ON_ERROR)
        : ['last_sync' => null, 'seen' => []];
    $query = [
        'updated_since' => $state['last_sync'] !== null ? minus_margin($state['last_sync']) : SYNC_START,
        'status' => 'approved',
        'limit' => 500,
    ];
    do {
        $page = xp_call('GET', '/documents?' . http_build_query($query)); // http_build_query koduje „+” jako %2B
        // brak pola next_cursor (a nie null) to tryb zwykły listy, a nie ostatnia strona
        if (!array_key_exists('next_cursor', $page)) {
            throw new RuntimeException('Błąd protokołu: odpowiedź bez pola next_cursor (serwer sprzed v0.5.0?) — '
                . 'synchronizacja przerwana.');
        }
        foreach ($page['items'] as $item) {
            if (($state['seen'][$item['id']] ?? null) === $item['updated_at']) {
                continue; // już przetworzony: powtórka z marginesu albo z granicy updated_since
            }
            $doc = xp_call('GET', "/documents/{$item['id']}"); // pełny wynik z invoice
            echo "#{$doc['id']} {$doc['status']} {$item['updated_at']} " . ($doc['invoice']['number'] ?? '') . "\n";
            // importuj tylko approved — pozycja listy mogła się zdezaktualizować (reprocess, odrzucenie, duplikat)
            if ($doc['status'] === 'approved') {
                // tu zaimportuj $doc['invoice'] do swojego systemu — idempotentnie (aktualizacja rekordu po id)
            }
            $state['seen'][$item['id']] = $item['updated_at']; // parę zapisz niezależnie od statusu
            // czas zawsze w formacie API (6 cyfr ułamka i Z), więc porównanie tekstów = porównanie czasu
            if ($state['last_sync'] === null || strcmp($item['updated_at'], $state['last_sync']) > 0) {
                $state['last_sync'] = $item['updated_at'];
            }
        }
        if ($state['last_sync'] !== null) { // pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
            $cutoff = minus_margin($state['last_sync']);
            $state['seen'] = array_filter($state['seen'], fn ($at) => strcmp($at, $cutoff) >= 0);
        }
        file_put_contents("$statePath.tmp", json_encode($state, JSON_FORCE_OBJECT)); // pusty seen jako {}, nie []
        rename("$statePath.tmp", $statePath); // stan po każdej stronie; zapis atomowy
        $query['cursor'] = $page['next_cursor']; // kolejna strona: te same parametry + kursor
    } while ($page['next_cursor'] !== null);
}

if (($argv[1] ?? '') === '--sync') {
    sync_approved($argv[2] ?? 'xp-sync.json');
    exit(0);
}
$doc = send_invoice($argv[1]);
echo "Dokument #{$doc['id']}: {$doc['status']}\n";
if ($doc['status'] === 'duplicate') {
    echo 'Duplikat dokumentu #' . (original_id($doc) ?? '?') . " — użyj wyniku oryginału.\n";
} elseif (!in_array($doc['status'], FINAL_STATUSES, true)) {
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
// Wysyłka faktury, odbiór wyniku i synchronizacja zmian (Node.js 18+: wbudowane fetch, FormData i Blob).
// Uruchom: node faktura.mjs faktura.xml        — wysyłka i odbiór wyniku (sposób A)
//          node faktura.mjs --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
import { readFile, rename, writeFile } from "node:fs/promises";
import { basename } from "node:path";

const BASE_URL = "https://parser.example.com/api/v1";
const API_KEY = process.env.XP_API_KEY;
const FINAL = new Set(["approved", "duplicate", "rejected"]);
const SYNC_START = "1970-01-01T00:00:00Z"; // pierwszy przebieg: pełna synchronizacja (albo data wdrożenia)
const SYNC_MARGIN_MS = 5 * 60 * 1000; // zapas na zmiany zatwierdzone w innej kolejności niż ich updated_at
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

// Dla statusu "duplicate": id wcześniejszego dokumentu tej samej faktury (albo null).
export function originalId(doc) {
  const issue = (doc.issues ?? []).find((i) => i.code === "duplicate" && /^\d+$/.test(i.source_value ?? ""));
  return issue ? Number(issue.source_value) : null;
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

async function loadState(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (e) {
    if (e.code === "ENOENT") return { last_sync: null, seen: {} }; // pierwszy przebieg
    throw e;
  }
}

// Czas API minus SYNC_MARGIN (Date ma dokładność do milisekund — przy odejmowaniu marginesu to bez znaczenia).
const minusMargin = (apiTime) => new Date(Date.parse(apiTime) - SYNC_MARGIN_MS).toISOString();

// Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego przebiegu.
// Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id → updated_at.
// Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id).
export async function syncApproved(statePath = "xp-sync.json") {
  const state = await loadState(statePath);
  const since = state.last_sync ? minusMargin(state.last_sync) : SYNC_START;
  const params = new URLSearchParams({ updated_since: since, status: "approved", limit: "500" });
  for (;;) {
    const page = await call("GET", `/documents?${params}`); // URLSearchParams koduje „+” jako %2B
    // brak pola next_cursor (a nie null) to tryb zwykły listy, a nie ostatnia strona
    if (!Object.hasOwn(page, "next_cursor")) {
      throw new Error("Błąd protokołu: odpowiedź bez pola next_cursor (serwer sprzed v0.5.0?) — "
        + "synchronizacja przerwana.");
    }
    for (const item of page.items) {
      if (state.seen[item.id] === item.updated_at) continue; // już przetworzony (margines, granica updated_since)
      const doc = await call("GET", `/documents/${item.id}`); // pełny wynik z invoice
      console.log(`#${doc.id} ${doc.status} ${item.updated_at} ${doc.invoice?.number ?? ""}`);
      // importuj tylko approved — pozycja listy mogła się zdezaktualizować (reprocess, odrzucenie, duplikat)
      if (doc.status === "approved") {
        // tu zaimportuj doc.invoice do swojego systemu — idempotentnie (aktualizacja rekordu po id)
      }
      // parę zapisz niezależnie od statusu; updated_at jako tekst — Date obcięłoby mikrosekundy
      state.seen[item.id] = item.updated_at;
      // czas zawsze w formacie API (6 cyfr ułamka i Z), więc porównanie tekstów = porównanie czasu
      if (!state.last_sync || item.updated_at > state.last_sync) state.last_sync = item.updated_at;
    }
    if (state.last_sync) { // pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
      const cutoff = Date.parse(state.last_sync) - SYNC_MARGIN_MS;
      for (const [id, at] of Object.entries(state.seen)) if (Date.parse(at) < cutoff) delete state.seen[id];
    }
    await writeFile(`${statePath}.tmp`, JSON.stringify(state));
    await rename(`${statePath}.tmp`, statePath); // stan po każdej stronie; zapis atomowy
    if (!page.next_cursor) return state; // null = ostatnia strona
    params.set("cursor", page.next_cursor); // kolejna strona: te same parametry + kursor
  }
}

if (!API_KEY) throw new Error("Ustaw zmienną środowiskową XP_API_KEY");
if (process.argv[2] === "--sync") {
  await syncApproved(process.argv[3]);
} else {
  let doc = await sendInvoice(process.argv[2]);
  console.log(`Dokument #${doc.id}: ${doc.status}`);
  if (doc.status === "duplicate") console.log(`Duplikat dokumentu #${originalId(doc) ?? "?"} — użyj wyniku oryginału.`);
  else if (!FINAL.has(doc.status)) doc = (await waitForResult(doc.id)) ?? doc;
  if (doc.status === "approved") {
    const { number, totals, currency, lines } = doc.invoice;
    console.log(`${number}: ${totals.gross} ${currency}`);
    for (const line of lines) console.log(`  ${line.product_index}: ${line.qty} ${line.unit}`);
  }
}
```

<a id="przyklad-bash"></a>

### Powłoka — curl i jq

```bash
#!/usr/bin/env bash
# Wysyłka faktury, odbiór wyniku i synchronizacja zmian (curl 7.76+ i jq 1.6+).
# Użycie: ./faktura.sh faktura.xml        — wysyłka i odbiór wyniku (sposób A)
#         ./faktura.sh --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
set -euo pipefail
BASE="https://parser.example.com/api/v1"
: "${XP_API_KEY:?Ustaw zmienną środowiskową XP_API_KEY}"
for t in curl jq; do command -v "$t" > /dev/null || { echo "Brak programu $t — zainstaluj go (curl 7.76+, jq 1.6+)." >&2; exit 1; }; done
DELAY="${DELAY:-5}"          # pierwsza przerwa między odpytaniami (s)
MAX_WAIT="${MAX_WAIT:-3600}"  # ile najdłużej czekać na operatora (s)
SYNC_START="1970-01-01T00:00:00Z"  # pierwszy przebieg: pełna synchronizacja (albo data wdrożenia)
SYNC_MARGIN=300                    # zapas 5 min na zmiany zatwierdzone w innej kolejności niż ich updated_at

api() { curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" "$@"; }

# Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego przebiegu.
# Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id → updated_at.
# Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id).
sync_approved() {
  local state="${1:-xp-sync.json}" since cursor="" page doc id status updated_at
  local -a args
  [[ -f "$state" ]] || echo '{"last_sync": null, "seen": {}}' > "$state"
  jq -e 'type == "object" and (.seen | type == "object")' "$state" > /dev/null \
    || { echo "Plik stanu $state ma zły format (oczekiwano obiektu z polem seen) — usuń go albo popraw." >&2; return 1; }
  # last_sync − margines (jq liczy w pełnych sekundach — przy 5-minutowym marginesie ułamek nie ma znaczenia)
  since=$(jq -r --argjson m "$SYNC_MARGIN" \
    '.last_sync // empty | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601 - $m | todateiso8601' "$state")
  since="${since:-$SYNC_START}"
  while :; do
    args=(-G --data-urlencode "updated_since=$since" -d status=approved -d limit=500)  # --data-urlencode: „+” → %2B
    [[ -z "$cursor" ]] || args+=(--data-urlencode "cursor=$cursor")  # kolejna strona: te same parametry + kursor
    page=$(api "${args[@]}" "$BASE/documents") || { echo "Błąd synchronizacji: $page" >&2; return 1; }
    # brak pola next_cursor (a nie null) to tryb zwykły listy, a nie ostatnia strona
    jq -e 'has("next_cursor")' <<<"$page" > /dev/null || {
      echo "Błąd protokołu: odpowiedź bez pola next_cursor (serwer sprzed v0.5.0?) — synchronizacja przerwana." >&2
      return 1
    }
    while read -r id updated_at; do  # tylko pary (id, updated_at), których jeszcze nie przetworzono
      doc=$(api "$BASE/documents/$id") || { echo "Błąd odpytania: $doc" >&2; return 1; }
      status=$(jq -r '.status' <<<"$doc")
      echo "#$id $status $updated_at $(jq -r '.invoice.number // ""' <<<"$doc")"
      # importuj tylko approved — pozycja listy mogła się zdezaktualizować (reprocess, odrzucenie, duplikat);
      # zapis do pliku po id — idempotentny
      [[ "$status" != approved ]] || jq '.invoice' <<<"$doc" > "faktura-$id.json"
    done < <(jq -r --slurpfile s "$state" \
      '.items[] | select($s[0].seen[.id | tostring] != .updated_at) | "\(.id) \(.updated_at)"' <<<"$page")
    # stan po każdej stronie: last_sync = max(updated_at) (czas zawsze w formacie API, więc max tekstów = max czasu),
    # nowe pary do seen niezależnie od statusu; pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
    jq -s --argjson m "$SYNC_MARGIN" '
      def secs: sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601;
      .[0] as $s | .[1].items as $items
      | ([$s.last_sync] + ($items | map(.updated_at)) | map(select(. != null)) | max) as $last
      | {last_sync: $last, seen: ($s.seen + ($items | map({key: (.id | tostring), value: .updated_at}) | from_entries))}
      | if $last then .seen |= with_entries(select((.value | secs) >= ($last | secs) - $m)) else . end' \
      "$state" - <<<"$page" > "$state.tmp" && mv "$state.tmp" "$state"
    cursor=$(jq -r '.next_cursor // empty' <<<"$page")
    [[ -n "$cursor" ]] || break  # next_cursor = null: ostatnia strona
  done
}

if [[ "${1:-}" == "--sync" ]]; then
  sync_approved "${2:-}"
  exit
fi

FILE="$1"
resp=$(api -F "file=@$FILE" "$BASE/documents") || { echo "Błąd wysyłki: $resp" >&2; exit 1; }
id=$(jq -r '.id' <<<"$resp")
status=$(jq -r '.status' <<<"$resp")
echo "Dokument #$id: $status"

waited=0
while [[ "$status" == "needs_review" || "$status" == "received" ]] && (( waited + DELAY <= MAX_WAIT )); do
  sleep "$DELAY"
  waited=$(( waited + DELAY ))
  DELAY=$(( DELAY * 2 > 300 ? 300 : DELAY * 2 ))
  resp=$(api "$BASE/documents/$id") || { echo "Błąd odpytania: $resp" >&2; exit 1; }
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
- Zmiany statusów odbierasz synchronizacją `updated_since` + `cursor` (sposób B): stronicujesz, aż `next_cursor` = `null`, a każdy przebieg zaczynasz od `last_sync − 5 min`.
- `last_sync` to `max(updated_at)` odebranych dokumentów, nie czas z zegara Twojej aplikacji; pierwszy przebieg zaczynasz od jawnej wartości (`1970-01-01T00:00:00Z` albo data wdrożenia).
- Powtórzenia odrzucasz po `id` i `updated_at`, a import jest idempotentny.
- Sposobu A (odpytywanie po `id`) używasz tylko wtedy, gdy wynik jest potrzebny zaraz po wysyłce.
- Ponawiasz po błędach sieci i 5xx; przy `duplicate` przechodzisz na `id` oryginału.
- Ktoś po Twojej stronie wie, że faktury nowych dostawców czekają na operatora w panelu.
- Monitorujesz dostępność usługi przez `GET https://parser.example.com/healthz` (bez klucza).

<a id="bledy"></a>

## Najczęstsze błędy integracji

- **Surowe body bez `Content-Type`**, np. `curl --data-binary @faktura.xml` — curl wysyła wtedy `application/x-www-form-urlencoded`, treść jest traktowana jak formularz i API zwraca `400 empty_body`. Dodaj `-H "Content-Type: application/xml"` albo użyj `-F file=@…`.
- **Pole formularza o innej nazwie** niż `file` (np. `plik`, `invoice`) → `400 empty_body`.
- **Import przy `needs_review`** — `invoice` jest wtedy niepełny (np. bez `product_index` lub `unit`).
- **`since` zamiast `updated_since` do synchronizacji** — `since` filtruje po czasie przyjęcia, więc gubi faktury zatwierdzone przez operatora później (rozdział 4).
- **Brak deduplikacji po `id` i `updated_at`** przy dostawie „co najmniej raz” — powtórzenia z marginesu i z granicy `updated_since` dublują import. Deduplikacja po samym `id` też jest błędem: pomija późniejsze zmiany tego samego dokumentu.
- **Zapamiętywanie czasu z własnego zegara** zamiast `max(updated_at)` odebranych dokumentów — różnica zegarów i czas trwania przebiegu przesuwają okno, a dokumenty giną.
- **Kolejna strona bez powtórzenia parametrów** — kursor nie pamięta filtrów: strona pobrana z samym `cursor` zwraca dokumenty we wszystkich statusach, po 100 na stronę.
- **Pusty `updated_since=` albo `cursor=`** (np. z niezainicjowanej zmiennej) — API zwraca `400 bad_request`; pierwszy przebieg zacznij od `updated_since=1970-01-01T00:00:00Z`, a `cursor` na pierwszej stronie pomiń.
- **Surowy `+` w czasie** (np. `updated_since=2026-10-11T08:00:00+02:00` wklejone do adresu) — w URL `+` oznacza spację, więc API zwraca `400 bad_request`; zapisz go jako `%2B` albo podawaj czas z `Z`.
- **Liczby zmiennoprzecinkowe** zamiast dziesiętnych — błędy zaokrągleń w kwotach.
- **Szukanie dokumentu innym kluczem** — każdy klucz widzi tylko swoje dokumenty (`404`).
- **Odpytywanie w ciasnej pętli** — operator potrzebuje minut lub godzin; stosuj rosnącą przerwę.
