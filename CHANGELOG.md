# Changelog

All notable changes to **xml-parser** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Limity wczytywania konfigurowane z env: `MAX_TREE_NODES` (domyślnie 200 000 węzłów drzewa — elementy, atrybuty, komórki CSV) i `MAX_LINES` (domyślnie 5 000 pozycji). Przekroczenie odrzuca dokument z czytelnym komunikatem po polsku zamiast przeciążać serwer; XML jest parsowany przyrostowo, więc limit przerywa wczytywanie przed załadowaniem całego pliku (SEC-1).
- Problemy z pozycji tego samego rodzaju są łączone w jeden z licznikiem i listą pierwszych 20 numerów pozycji (np. 10 000 × „brak przelicznika dla worek” → 1 problem „dotyczy 10 000 pozycji”); dotyczy braków przelicznika, nieprzypisanych towarów (ten sam kod/nazwa), błędów wartości i niezgodności sum pozycji (EDGE-5).
- CI GitHub Actions: testy oraz kontrola braku `private/` i `.env` w repozytorium (OPS-3).
- `tools/backup.sh` — kopia bazy i storage z retencją; opis odtwarzania w README (OPS-4).
- Healthcheck usługi `app`; `/healthz` sprawdza połączenie z bazą (503 przy awarii, pole `db`) (OPS-7).
- Limity zasobów kontenerów (`APP_MEM_LIMIT`, `APP_CPUS`, `DB_MEM_LIMIT`, `DB_CPUS`) i rotacja logów dockera (OPS-12, OPS-18).
- `requirements.lock` z przypiętymi zależnościami przechodnimi, używany w obrazie (OPS-6).
- Transformacja `decimal` przyjmuje separator dziesiętny jako argument (`{"decimal": ","}` / `{"decimal": "."}`); problem „niejednoznaczna liczba” ma w panelu gotowe podpowiedzi z podglądem obu wariantów (EDGE-11).
- Stawki VAT `zw`, `np` (także `np I` / `np II` z KSeF) i `oo` są zachowywane w `vat_rate` jako kod stawki; stawka w postaci ułamka (`0,23`) daje ostrzeżenie „prawdopodobnie ułamek, nie procent” (EDGE-10).
- Akcja „Przywróć” w panelu (POST z CSRF) dla dokumentu odrzuconego ręcznie; kto odrzucił, zapisywane jest w nowej kolumnie `documents.rejected_by` (migracja `3c7d2a91e5b4`) (BE-2).
- Mapowanie towaru po znormalizowanej nazwie dla pozycji bez kodu i GTIN (kolumna `product_mappings.supplier_name_norm`, także w CRUD mapowań); pozycja bez kodu, GTIN i nazwy może dostać towar tylko „dla tej faktury” (BE-3/EDGE-3).
- OpenAPI: schematy `Invoice`/`InvoiceLine` (`vat_rate` jako liczba-tekst albo kod `zw`/`np`/`oo`), pola `count` i `line_nos` w `Issue`, odpowiedź 409 dla `reprocess`.

### Changed
- Widok szczegółów dokumentu pokazuje maks. 50 kart problemów, 3 000 wierszy drzewa pliku i 500 pozycji wyniku (pełne dane w JSON) — strona dużej faktury nie ma już dziesiątek MB (EDGE-5).
- Wybór elementu z pozycjami: najpierw ścieżka pozycji z wyuczonych szablonów, potem grupa zawierająca typowe pola pozycji (ilość/cena + inne wg synonimów), dopiero potem najliczniejsza powtarzalna grupa. Synonim `qty` dla ilości (EDGE-4).
- Domyślny `APP_PORT` 18506 w compose (OPS-16).
- Obrazy bazowe przypięte do wersji (python 3.12.15-slim-trixie, mariadb 11.4.13) (OPS-5).
- Entrypoint: migracje z ponawianiem i backoffem; gunicorn z `--max-requests` (restart workerów) (OPS-10, OPS-12).
- Liczba w formie niejednoznacznej (jeden separator i dokładnie 3 cyfry po nim, np. `1,234` / `1.234`) blokuje dokument problemem `ambiguous_number`, chyba że separator jest ustawiony w transformacji `decimal` albo jednoznacznie wynika z innych wartości tego samego dokumentu; liczby z JSON-a (typ number) są zawsze jednoznaczne (EDGE-11).
- Waluta normalizowana do kodu ISO 4217 (`zł`/`zl` → PLN, `EURO`/`€` → EUR, `£` → GBP, wielkość liter, spacje); nieznana waluta to problem blokujący (EDGE-21).
- Litery wewnątrz liczby (np. `12a3`, `0.1+0.2`) są błędem zamiast być po cichu usuwane; dopiski waluty/procentu przed lub po liczbie (`£80.50`, `12,50 zł`, `23%`) działają jak dotąd (EDGE-1).
- Dokument jest duplikatem tylko względem wcześniej przyjętego (niższe id), nie-odrzuconego dokumentu; odrzucenie oryginału przelicza wskazujące na niego duplikaty, a „Przywróć” oryginału przywraca późniejszym kopiom status duplikatu (BE-5, EDGE-24).
- NIP/VAT dostawcy zapisywany w postaci znormalizowanej (bez spacji, myślników, kropek); „Utwórz dostawcę” z NIP istniejącego dostawcy podpina istniejącego, a CRUD odrzuca duplikat NIP; identyfikacja wybiera deterministycznie najstarszego dostawcę (BE-11/EDGE-9).
- Faktura korygująca / zaliczkowa (`doc_type` correction, advance, KOR, ZAL…) bez pozycji dostaje ostrzeżenie zamiast problemu blokującego; zwykła faktura bez pozycji nadal jest blokowana (EDGE-19).
- Edytor szablonów wymaga elementu z pozycjami (`line_path`) i prosi o potwierdzenie, gdy nowa wersja usuwa mapowanie pól wymaganych (EDGE-15).
- Przypisanie towaru „tylko dla tej faktury” do zagregowanego problemu obejmuje wszystkie pozycje z tym samym kodem/GTIN/nazwą.

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
- Przelicznik `1,000` / `1.000` w CRUD i negocjacji to błąd formularza zamiast cichego 1,0.
- Ponowne przetworzenie oryginału nie oznacza go jako duplikatu kopii zatwierdzonej przez „Dopuść duplikat” (BE-5).
- Ręczne przypisanie usuniętego towaru (lub jednostki) nie daje już statusu zatwierdzonego — pozycja dostaje problem blokujący (EDGE-7).
- Porównanie NIP/VAT uwzględnia prefiks kraju: `FR123456789` ≠ `DE123456789`; prefiks pomijany tylko, gdy po jednej stronie go brak (EDGE-8).
- Edytor nie zapisuje pustych reguł `{}` jako aktywnej wersji szablonu (EDGE-15).
- Numer pozycji `0`, ujemny lub większy niż liczba pozycji daje komunikat „Brak pozycji” zamiast trafiać w ostatnią pozycję (EDGE-25).

### Security
- DoS przez złożoność kwadratową: wykrywanie grupy pozycji działa w jednym przejściu drzewa, a podpowiedzi mapowań korzystają z indeksu sufiksów ścieżek (rozpoznawanie po samym typie wartości tylko dla pierwszych 1 000 ścieżek). Szeroki JSON 1,15 MB: 35,6 s → 1,0 s; XML 1,5 MB: 162 s → 1,5 s (SEC-1).
- Port aplikacji domyślnie wiązany tylko do 127.0.0.1 (`APP_BIND`); dostęp przez Tailscale wymaga ustawienia IP w `.env` (OPS-1).
- Kontener aplikacji działa jako użytkownik nie-root (uid 10001); entrypoint naprawia właściciela wolumenu storage (OPS-2).
- Wymagane `MARIADB_PASSWORD` i `MARIADB_ROOT_PASSWORD` w docker-compose (OPS-13).
- Rozszerzony `.dockerignore` (sekrety, testy, dokumentacja, narzędzia poza obrazem) (OPS-14).

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

[Unreleased]: https://github.com/AmigoUK/xml-parser/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/AmigoUK/xml-parser/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/AmigoUK/xml-parser/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/AmigoUK/xml-parser/releases/tag/v0.0.1
