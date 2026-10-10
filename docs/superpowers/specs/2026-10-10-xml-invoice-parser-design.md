# XML Parser faktur — specyfikacja projektowa

- **Data:** 2026-10-10
- **Status:** do przeglądu
- **Repo:** `git@github.com:AmigoUK/xml-parser.git`

## 1. Cel

Faktury od dostawców przychodzą w plikach strukturalnych (XML, czasem JSON/CSV), a każdy dostawca ma własny format. Tagi mają różne nazwy, jednostki miary są w obcych kodach (`pcs` zamiast `szt`), kody EAN mają prefiksy AI GS1, części pól brakuje.

System to **parser jako usługa (REST API)** dla innych systemów oraz **webowy panel po polsku**. Przy *pierwszym* problemie z danym dostawcą operator w panelu „negocjuje” sposób odczytu. Wynik zapisuje się jako **szablon dostawcy** i każda kolejna faktura tego dostawcy czyta się automatycznie. System uczy się z każdej nowej rozbieżności, ale nie jest przywiązany do jednego wzoru: czyta dowolny plik strukturalny.

Pierwsza wersja to **demo z opisem działania** (strona „O demo” + przykładowe faktury).

### Kryteria sukcesu
1. Pierwsza faktura nowego dostawcy kończy się statusem `needs_review` z listą konkretnych problemów i podpowiedziami.
2. Po rozwiązaniu problemów z opcją „zapamiętaj w szablonie” druga faktura tego dostawcy przechodzi do `approved` bez udziału operatora.
3. Ten sam mechanizm obsługuje różne formaty wejścia (XML własny, KSeF-podobny, UBL 2.1, CSV, JSON).
4. Inny system może wysłać fakturę przez API i odebrać znormalizowany JSON.

### Twarde ograniczenie — dane prywatne
Realne faktury dostawców (i dane nabywcy) **nigdy** nie trafiają do repozytorium. Leżą wyłącznie w `private/` (w `.gitignore`). Próbki demo w repo są w całości fikcyjne. Test-strażnik (`tests/test_no_private_data.py`) dzieli wszystkie pliki z `git ls-files` na tokeny i porównuje ich SHA-256 z listą hashy zakazanych tokenów (nazwy firm, numery VAT). Dzięki temu same zakazane wartości nie występują w repo nawet w teście.

## 2. Decyzje

| Temat | Decyzja |
|---|---|
| Rola | REST API + panel do uczenia szablonów i obsługi kolejki |
| Stack | Python 3.12, Flask, SQLAlchemy + Alembic, MariaDB, Docker Compose, lxml, rapidfuzz; Jinja2 + HTMX + Alpine.js + Bootstrap 5 — wszystko vendorowane (bez CDN) |
| Silnik | Deterministyczny szablon ścieżek + łańcuchy transformacji; **bez LLM** |
| Port | 5010; host i URL-e wyłącznie z `.env` (przenośność hostingu, dostęp po Tailscale) |
| Stopka | Kredyty autora + `· vX.Y.Z`, na każdej stronie poza pełnoekranowym edytorem mapowań |
| Wydania | SemVer od v0.0.1, `CHANGELOG.md` (Keep a Changelog 1.1.0), tagi, GitHub Releases |

Odrzucone podejścia: XSLT per dostawca (operator nie nauczy go przez UI), ekstrakcja przez LLM (niedeterministyczna, płatna, trudna do audytu).

## 3. Architektura — pipeline

```
wejście: upload w panelu | POST /api/v1/documents | [E2] IMAP | [E2] obserwowany folder
  1. ingest      zapis surowego pliku (storage/, sha256), wykrycie formatu XML/JSON/CSV
  2. normalize   SourceTree: płaskie ścieżki → wartości, wykrycie grupy powtarzalnej (pozycje)
  3. fingerprint hash posortowanego zbioru uogólnionych ścieżek (bez indeksów i prefiksów ns)
  4. identify    dostawca po NIP/VAT (ścieżki z synonimów i szablonów) → fallback: fingerprint
  5. apply       aktywna wersja szablonu → dokument kanoniczny + lista problemów
  6. validate    sumy, wymagane pola, duplikat (dostawca + numer)
  7. status      brak problemów blokujących → approved; w przeciwnym razie → needs_review
  8. negotiate   operator rozwiązuje problemy: „tylko ta faktura” | „zapamiętaj w szablonie”
                 → nowa wersja szablonu → ponowne przetworzenie (krok 5)
```

Statusy dokumentu: `received → parsed → approved | needs_review | duplicate | rejected`.

Problem (issue) to struktura `{code, severity: blocking|warning, field, line_no?, message_pl, source_path?, source_value?, suggestions[]}`. Kody MVP: `unknown_supplier`, `unmapped_field` (brak wymaganego pola), `transform_error`, `unknown_unit`, `missing_conversion`, `unmapped_product`, `sum_mismatch_line`, `sum_mismatch_total`, `duplicate`.

## 4. Moduły

Każdy moduł ma jedną odpowiedzialność i jest testowany w izolacji. Silnik (`engine/`) nie zna Flaska ani bazy, a dane słownikowe dostaje przez interfejs `Lookups`.

| Moduł | Odpowiedzialność |
|---|---|
| `app/ingest/readers/xml.py` | XML → `SourceTree`. lxml z `resolve_entities=False`, `no_network=True`, bez `huge_tree`. Namespace usuwane ze ścieżek (lokalne nazwy), atrybuty jako `@attr`. |
| `app/ingest/readers/json.py` | JSON → `SourceTree` (listy = grupy powtarzalne). |
| `app/ingest/readers/csv.py` | CSV → `SourceTree`. Wykrycie separatora i kodowania. Wiersze jako pozycje, a kolumny stałe we wszystkich wierszach jako kandydaci na nagłówek. |
| `app/engine/tree.py` | `SourceTree`: `paths()`, `get(path)`, `groups()`, `detect_line_group()` (najliczniejsza grupa powtarzalna z liśćmi), `fingerprint()`. |
| `app/engine/gs1.py` | Parser GS1-128: AI 01 (GTIN-14 + cyfra kontrolna), 10 (partia, zmienna długość do FNC1/końca), 11/13/15/17 (YYMMDD → data). Walidacja GTIN-8/12/13/14. |
| `app/engine/transforms.py` | Rejestr transformacji z białej listy (bez `eval`): `trim`, `upper`, `lower`, `decimal` (przecinek/kropka/separator tysięcy), `strip_percent`, `date(format)`, `regex_extract(pattern, group)` (limit długości wzorca i wejścia), `map(dict)`, `unit_map`, `convert(factor)`, `constant(value)`, `concat(paths, sep)`, `split(sep, index)`, `negate`, `gs1(ai)`, `strip_ai_prefix`. |
| `app/engine/canonical.py` | Dataclassy dokumentu kanonicznego + definicja pól wymaganych. |
| `app/engine/template.py` | Model reguł szablonu i `apply(tree, rules, lookups) → (CanonicalInvoice, issues)`. |
| `app/engine/validate.py` | Walidacja: `qty × unit_price_net ≈ net` (tolerancja 0.01), `Σ net(pozycji) ≈ totals.net`, `net + vat ≈ gross`, duplikat. |
| `app/engine/suggest.py` | Podpowiedzi z % pewności: (1) pary ścieżka→pole z istniejących szablonów, (2) słownik synonimów `data/synonyms.yaml` (PL/EN/KSeF/UBL), (3) detektory typu wartości (NIP/VAT, data, kwota, GTIN, GS1-128, stawka %), (4) dopasowanie rozmyte nazw (rapidfuzz). To samo dla jednostek (aliasy, kody UN/ECE) i towarów (GTIN dokładnie → nazwa rozmyta). |
| `app/services/pipeline.py` | Orkiestracja kroków 1–7, zapis do `documents`. |
| `app/services/negotiation.py` | Zastosowanie rozwiązania problemu: jednorazowe (override na dokumencie) lub trwałe (nowa wersja szablonu / wpis w słowniku / mapowanie towaru). |
| `app/api/` | Blueprint REST v1. |
| `app/web/` | Blueprint panelu (Jinja2 + HTMX + Alpine). |

## 5. Dokument kanoniczny (wyjście API)

```json
{
  "doc_type": "invoice",
  "number": "FV/2026/10/001",
  "issue_date": "2026-10-09", "sale_date": null, "due_date": "2026-10-30",
  "payment_method": "przelew", "currency": "GBP",
  "supplier": {"name": "...", "tax_id": "...", "address": {"street": "...", "postcode": "...", "city": "...", "country": null}},
  "buyer":    {"name": "...", "tax_id": "...", "address": {"street": "...", "postcode": "...", "city": "...", "country": null}},
  "totals": {"net": "344.91", "vat": "0.00", "gross": "344.91"},
  "delivery_notes": ["WZ-001"],
  "corrected_invoice_number": null,
  "lines": [{
    "line_no": 1, "supplier_code": "A100", "gtin": "05900000000001", "name": "...",
    "qty": "5", "unit": "szt", "unit_source": "pcs", "conversion_factor": "1",
    "unit_price_net": "16.10", "net": "80.50", "vat_rate": "0", "vat": "0.00", "gross": "80.50",
    "batch": "260709", "expiry_date": "2027-07-09", "product_index": "TOW-0001"
  }]
}
```

Kwoty jako `Decimal` serializowany do stringa, bez floatów. Pola wymagane w MVP: `number`, `issue_date`, `currency`, `supplier.tax_id` lub `supplier.name`, `totals.gross`, a w pozycjach `name`, `qty`, `unit`, `net`.

## 6. Szablon dostawcy

Przechowywany jako JSON w `template_versions.rules`. Każda zmiana tworzy nową wersję, a dokument pamięta wersję, którą go przetworzono.

```json
{
  "line_path": "Faktura/Pozycje/Pozycja",
  "doc_type": {"constant": "invoice"},
  "header": {
    "number":         {"path": "Faktura/Naglowek/FakturaNumer"},
    "supplier.tax_id": {"path": "Faktura/Naglowek/DostawcaNIP", "transforms": ["trim"]}
  },
  "lines": {
    "vat_rate": {"path": "StawkaVat", "transforms": ["strip_percent", "decimal"]},
    "gtin":     {"path": "TowarKodEan", "transforms": ["strip_ai_prefix"]},
    "unit":     {"path": "TowarJm", "transforms": ["unit_map"]}
  },
  "defaults": {"currency": "GBP"}
}
```

Ścieżki w `lines` są względne do `line_path`. `unit_map` i `convert` korzystają ze słowników (aliasy jednostek, przeliczniki), a towar z `product_mappings`. Słowniki mają zasięg globalny lub per dostawca (per dostawca wygrywa).

## 7. Model danych (MariaDB)

- `suppliers` (id, name, tax_id, notes)
- `templates` (id, supplier_id NULL, name, fingerprint, active_version_id)
- `template_versions` (id, template_id, version, rules JSON, author, comment, created_at)
- `units` (id, code `szt`, name) · `unit_aliases` (alias `pcs`, unit_id, supplier_id NULL)
- `unit_conversions` (supplier_id NULL, product_id NULL, from_unit, to_unit, factor)
- `products` (id, index, name, gtin, unit_id) — nasza kartoteka, import CSV
- `product_mappings` (supplier_id, supplier_code NULL, supplier_gtin NULL, product_id)
- `documents` (id, source, filename, sha256, format, supplier_id, template_version_id, status, doc_type, number, issue_date, result JSON, issues JSON, overrides JSON, corrects_document_id NULL, api_key_id NULL, created_at, updated_at)
- `api_keys` (id, name, prefix, key_hash, active, webhook_url NULL, webhook_secret NULL, last_used_at)
- `users` (id, email, password_hash, role `admin|operator`) — w MVP jedno konto admin zakładane z `.env`
- `audit_log` (id, user_id, action, entity, entity_id, payload JSON, created_at)
- `price_history` [E2]

Surowe pliki leżą w `storage/` (wolumen Dockera, w `.gitignore`), nazwa = sha256.

## 8. REST API v1

Uwierzytelnianie nagłówkiem `X-API-Key`. Klucze są hashowane, a w UI widać tylko prefiks.

| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `/api/v1/documents` | multipart `file` lub surowe body → `201 {id, status, invoice?, issues[]}` |
| GET | `/api/v1/documents/{id}` | status, wynik kanoniczny, problemy |
| GET | `/api/v1/documents?status=&since=` | lista z filtrowaniem |
| POST | `/api/v1/documents/{id}/reprocess` | ponowne przetworzenie aktywną wersją szablonu |
| GET | `/api/v1/suppliers` | lista dostawców |
| GET/POST | `/api/v1/templates/{id}/export`, `/api/v1/templates/import` | [E2] |

Webhook [E2]: `POST webhook_url` przy przejściu do `approved` lub `rejected`, nagłówek `X-Signature: sha256=HMAC(body)`.
Dokumentacja: `openapi.yaml` + `/api/docs` (vendorowany Swagger UI). Błędy w formacie `{error: {code, message}}`.

## 9. Panel (język polski)

| Ekran | Zawartość |
|---|---|
| O demo | Opis działania krok po kroku z diagramem pipeline'u, przyciski „Wczytaj przykład …” dla każdej próbki, „Wyczyść dane demo”. Strona startowa w trybie demo. |
| Pulpit | Liczniki statusów, ostatnie dokumenty. |
| Wgraj fakturę | Drag & drop, po wgraniu przekierowanie do dokumentu. |
| Kolejka do wyjaśnienia | Lista `needs_review` z liczbą problemów. |
| Dokument | Po lewej drzewo źródła z wartościami, po prawej wynik kanoniczny (pozycje w tabeli). Pod spodem **kreator negocjacji**: problemy po kolei, każdy z podpowiedziami (% pewności), polem wyboru i przełącznikiem „tylko ta faktura / zapamiętaj w szablonie”. Przyciski „Przetwórz ponownie”, „Zatwierdź”, „Odrzuć”. |
| Edytor mapowań | Pełny ekran (bez stopki). Kliknięcie ścieżki źródła, potem pola docelowego tworzy regułę. Łańcuch transformacji z podglądem wyniku na żywo, podpowiedzi. |
| Dostawcy | CRUD. |
| Szablony | Lista, wersje, diff między wersjami, przywrócenie wersji. |
| Słowniki | Jednostki, aliasy, przeliczniki — CRUD. |
| Kartoteka towarów | CRUD + import CSV. Mapowania towarów dostawców — CRUD. |
| Klucze API | Tworzenie (klucz pokazany raz), dezaktywacja, edycja nazwy. |
| Historia | Log audytowy. |

Każda lista CRUD ma przyciski edycji i usuwania. Logowanie w MVP: jedno konto admin z `.env`.

## 10. Bezpieczeństwo

- XML: brak rozwiązywania encji, brak sieci, brak `huge_tree` (ochrona przed XXE i billion laughs).
- Limit uploadu 10 MB (konfigurowalny).
- Klucze API hashowane (SHA-256), hasła hashowane (werkzeug), CSRF w formularzach (Flask-WTF).
- Transformacje wyłącznie z białej listy. Regex z limitem długości wzorca i wejścia.
- Sekrety, host i URL-e tylko z `.env`. W repo jest wyłącznie `.env.example`.

## 11. Próbki demo (fikcyjne, w repo — `demo/samples/`)

1. `alfa-1.xml` — „Hurtownia Alfa”: polskie tagi, jednostka `pcs`, EAN z prefiksem AI `01`, kod GS1-128, stawka `0%`.
2. `alfa-2.xml` — druga faktura Alfa. Po nauczeniu na #1 przechodzi automatycznie.
3. `beta-ksef.xml` — format podobny do KSeF FA(3).
4. `gamma-ubl.xml` — UBL 2.1, kody jednostek UN/ECE (`C62`, `H87`).
5. `delta.csv` — przecinek dziesiętny, jednostka `kart.` wymagająca przelicznika ×12.
6. `epsilon.json` — faktura w JSON.
7. `alfa-1-korekta.xml` — korekta do #1 [E2].

Wszystkie nazwy, numery VAT, adresy i GTIN-y są fikcyjne. GTIN-y mają poprawne cyfry kontrolne, żeby walidacja działała.

## 12. Etapy

**Etap 1 — MVP demo (v0.1.0):** scaffold, Docker i release management (v0.0.1); czytniki; drzewo i fingerprint; GS1 i transformacje; silnik szablonów; słowniki jednostek i przeliczników; kartoteka i mapowania towarów; walidacja i duplikaty; pipeline, statusy i kolejka; kreator negocjacji, wersjonowanie szablonów i ponowne przetworzenie; podpowiedzi; API v1 z kluczami i OpenAPI; strona demo z próbkami i resetem; konto admin; stopka.

**Etap 2 (v0.2.x+):** faktury korygujące (wykrycie, ujemne ilości, powiązanie z fakturą pierwotną); webhooki; konta i role + audyt per użytkownik; eksport/import szablonów; alerty zmian cen (`price_history`, próg %); pobieranie z IMAP i obserwowanego folderu.

**Etap 3 — backlog:** XML osadzony w PDF/A-3 (Factur-X/ZUGFeRD); pobieranie z API KSeF; przeliczanie walut po kursie (NBP/BoE); upload ZIP; statystyki (% auto-zatwierdzeń per dostawca, czas obsługi); eksport do systemów docelowych (np. PZ); test regresji szablonu na archiwum faktur dostawcy przed aktywacją nowej wersji.

## 13. Testy i weryfikacja

- **Jednostkowe (pytest):** każdy czytnik; drzewo, wykrycie pozycji, fingerprint (stabilny przy zmianie kolejności i liczby pozycji); każda transformacja (GS1 z AI 01/15/10, przecinki dziesiętne, `0%`, daty); `apply` szablonu; walidacja sum i duplikatów; podpowiedzi (synonimy i detektory).
- **Akceptacyjny „uczenia”:** `alfa-1.xml` przez API → `needs_review` (nieznany dostawca, `pcs`, niezmapowane towary) → rozwiązania z „zapamiętaj” → `approved`; `alfa-2.xml` → od razu `approved`. To samo dla `delta.csv` z przelicznikiem `kart.` → `szt` ×12.
- **Strażnik danych prywatnych:** `tests/test_no_private_data.py` (hashe tokenów, opis w sekcji 1).
- **Lokalnie, poza repo:** realna faktura z `private/samples/` przechodzi ten sam scenariusz uczenia.
- **E2E:** `docker compose up`, panel na `:5010`, przejście ścieżki demo w przeglądarce, sprawdzenie stopki z wersją, `/api/docs`, `curl -H "X-API-Key: …" -F file=@demo/samples/alfa-1.xml …/api/v1/documents`.
