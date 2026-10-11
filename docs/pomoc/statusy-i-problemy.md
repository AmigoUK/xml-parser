<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Statusy i problemy

## Statusy dokumentu

| Status (API) | W panelu | Znaczenie |
| --- | --- | --- |
| <a id="status-received"></a>`received` | Przyjęta | Stan przejściowy: plik zapisano, dokument czeka na przetworzenie. Zwykle widoczny tylko przez ułamek sekundy — przetwarzanie rusza od razu po przyjęciu. |
| <a id="status-approved"></a>`approved` | Zatwierdzona | Faktura odczytana bez problemów blokujących. Mogą wystąpić ostrzeżenia (np. niezgodność sumy w pozycji) — warto je przejrzeć, ale nie wstrzymują dokumentu. |
| <a id="status-needs_review"></a>`needs_review` | Do wyjaśnienia | Jest co najmniej jeden problem blokujący. Dokument czeka w „Kolejce” na decyzję operatora; po każdej decyzji poza „Odrzuć” jest przetwarzany ponownie. |
| <a id="status-duplicate"></a>`duplicate` | Duplikat | Ta sama faktura jest już w systemie (ten sam plik albo ten sam dostawca, rodzaj i numer dokumentu) w tym samym zakresie — kluczu API albo panelu. |
| <a id="status-rejected"></a>`rejected` | Odrzucona | Dokument odrzucony. Automatycznie — gdy pliku nie da się odczytać albo ma zbyt wiele pozycji (można go przetworzyć ponownie) — albo ręcznie przez operatora (wtedy cofa to tylko „Przywróć” w panelu). |

## Kody problemów

Każdy problem ma kod (`code` w API), wagę — **blokuje** (dokument czeka „Do wyjaśnienia”) albo **ostrzeżenie** (nie wstrzymuje zatwierdzenia) — i komunikat po polsku. Problemy tego samego rodzaju z wielu pozycji są łączone w jeden z licznikiem (`count`) i numerami pierwszych 20 pozycji (`line_nos`).

| Kod | Blokuje | Co oznacza | Jak rozwiązać |
| --- | --- | --- | --- |
| <a id="unknown_supplier"></a>`unknown_supplier`<br>Nie rozpoznano dostawcy | tak | Żaden dostawca w bazie nie ma NIP/VAT odczytanego z faktury (albo NIP-u nie udało się odczytać). | Utwórz nowego dostawcę z danych faktury albo wskaż istniejącego. Gdy struktura pliku pasuje do szablonu innego dostawcy, panel proponuje skopiowanie jego reguł. Rozwiąż go najpierw — bez dostawcy nie powstanie szablon, alias, przelicznik ani mapowanie towaru. |
| <a id="unmapped_field"></a>`unmapped_field`<br>Brak wymaganego pola | zależnie<br>Blokuje; brak pozycji w korekcie lub fakturze zaliczkowej to tylko ostrzeżenie. | Szablon nie wskazuje, skąd wziąć wymagane pole (np. numer, datę, walutę, sumę brutto, dane dostawcy), albo nie wskazano elementu z pozycjami faktury. | Wybierz podpowiadaną ścieżkę w pliku, wskaż ją ręcznie albo ustaw stałą wartość domyślną (np. PLN). Dla pól pozycji wybierz „zapamiętaj w szablonie”. Szersze zmiany — w edytorze mapowań. |
| <a id="transform_error"></a>`transform_error`<br>Błąd transformacji | zależnie<br>Blokuje dla pól wymaganych, dla pozostałych — ostrzeżenie. | Krok łańcucha transformacji nie dał się wykonać (np. data nie pasuje do formatu, wartość nie pasuje do wyrażenia regularnego, kod GS1 nie zawiera wskazanego AI). | Popraw łańcuch transformacji pola w edytorze mapowań albo wskaż inną ścieżkę. |
| <a id="invalid_value"></a>`invalid_value`<br>Niepoprawna wartość | zależnie<br>Blokuje dla pól wymaganych, dla pozostałych — ostrzeżenie. | Wartość nie pasuje do typu pola: nieznana waluta (oczekiwany kod ISO 4217), nierozpoznana data, nieprawidłowa liczba albo GTIN z błędną cyfrą kontrolną. | Sprawdź, czy pole wskazuje właściwy element pliku; w razie potrzeby dodaj transformację (np. „date”, „map”, „decimal”) albo ustaw wartość domyślną. |
| <a id="ambiguous_number"></a>`ambiguous_number`<br>Niejednoznaczna liczba | tak | Liczba w postaci „1,234” lub „1.234” — separator może być dziesiętny albo tysięcy, a reszta dokumentu nie rozstrzyga, który to przypadek. Błąd o trzy rzędy wielkości nie może przejść po cichu. | Wybierz w panelu jeden z gotowych wariantów (z podglądem wartości) albo dodaj do pola transformację {"decimal": ","} lub {"decimal": "."} i przetwórz dokument ponownie. |
| <a id="vat_rate_fraction"></a>`vat_rate_fraction`<br>Stawka VAT wygląda na ułamek | nie | Stawka VAT jest liczbą między 0 a 1 (np. 0,23 zamiast 23) — prawdopodobnie pole wskazuje ułamek, a nie procent. | Sprawdź mapowanie pola „Stawka VAT %”; w razie potrzeby wskaż inne pole pliku. |
| <a id="unknown_unit"></a>`unknown_unit`<br>Nieznana jednostka miary | tak | Jednostka z faktury (np. „pcs”, „kart.”) nie jest naszym kodem jednostki ani aliasem — ani tego dostawcy, ani globalnym. | Wskaż odpowiadającą jej naszą jednostkę. Z „zapamiętaj” powstaje alias dostawcy; bez — przypisanie tylko dla tej faktury. |
| <a id="unmapped_product"></a>`unmapped_product`<br>Nie przypisano towaru | tak | Pozycji nie udało się dopasować do towaru z naszej kartoteki (po kodzie dostawcy, GTIN ani nazwie) albo ręcznie przypisany towar usunięto z kartoteki. | Przypisz towar z kartoteki albo dodaj nowy. Z „zapamiętaj” powstaje mapowanie towaru dostawcy, więc kolejne faktury dopasują się same. |
| <a id="missing_conversion"></a>`missing_conversion`<br>Brak przelicznika jednostki | tak | Jednostka pozycji nie jest jednostką bazową, a nie ma przelicznika na jednostkę bazową (np. 1 karton = ? szt). | Podaj przelicznik — dla wszystkich towarów dostawcy albo tylko dla tego towaru. Kropka jest zawsze separatorem dziesiętnym (np. 1.125). Przelicznik zawsze zostaje zapamiętany. |
| <a id="sum_mismatch_line"></a>`sum_mismatch_line`<br>Niezgodna suma w pozycji | nie | W pozycji ilość × cena różni się od wartości netto albo netto + VAT od brutto o więcej niż 0,01. | Sprawdź, czy pola ilości, ceny i wartości wskazują właściwe elementy (np. cena brutto zamiast netto). Jeśli faktura naprawdę tak wygląda — ostrzeżenie można zostawić. |
| <a id="sum_mismatch_total"></a>`sum_mismatch_total`<br>Niezgodna suma faktury | tak | Suma netto pozycji różni się od sumy netto faktury albo netto + VAT faktury od brutto (tolerancja 0,01). | Sprawdź mapowanie sum i wartości pozycji oraz element z pozycjami (czy nie pomija części pozycji). Popraw reguły w edytorze mapowań i zapisz nową wersję. |
| <a id="duplicate"></a>`duplicate`<br>Duplikat | tak | Ten sam plik albo faktura o tym samym dostawcy, rodzaju i numerze jest już w systemie w tym samym zakresie (ten sam klucz API albo panel). Dokumenty różnych zakresów nie są dla siebie duplikatami. | Jeśli to rzeczywiście inna faktura — „To nie duplikat — przetwórz”. W przeciwnym razie „Odrzuć”. Gdy oryginał zostanie odrzucony, jego duplikaty są przeliczane. |
| <a id="reprocess_required"></a>`reprocess_required`<br>Wymaga ponownego przetworzenia | tak | Ustawiany przy aktualizacji do v0.2.0: dokument był oznaczony jako duplikat dokumentu z innego zakresu (inny klucz API albo panel), a od v0.2.0 różne zakresy nie są dla siebie duplikatami. | „Przetwórz ponownie” w widoku dokumentu albo POST /api/v1/documents/{id}/reprocess. |
| <a id="unreadable"></a>`unreadable`<br>Plik nieczytelny | tak | Pliku nie da się odczytać: pusty, binarny (np. PDF), w kodowaniu UTF-16/UTF-32, niepoprawny XML/JSON/CSV, XML z DOCTYPE/ENTITY, zbyt głęboko zagnieżdżony albo z liczbą węzłów ponad limit. Dokument dostaje status „Odrzucona”. | Wgraj poprawny plik XML, JSON lub CSV w UTF-8. Ponowne przetworzenie jest możliwe (to odrzucenie automatyczne), ale pomoże tylko, gdy zmieniono limit. |
| <a id="too_many_lines"></a>`too_many_lines`<br>Zbyt wiele pozycji | tak | Liczba pozycji przekracza limit MAX_LINES. Dokument dostaje status „Odrzucona”. | Podziel fakturę na mniejsze pliki albo poproś administratora o podniesienie limitu MAX_LINES i przetwórz dokument ponownie. |
| <a id="file_missing"></a>`file_missing`<br>Brak pliku źródłowego | tak | W magazynie plików nie ma pliku tego dokumentu (np. utracony wolumen storage). | Wgraj fakturę ponownie albo odtwórz katalog storage z kopii zapasowej. |
| <a id="internal_error"></a>`internal_error`<br>Wewnętrzny błąd przetwarzania | tak | Nieoczekiwany błąd podczas przetwarzania (np. uszkodzona reguła szablonu). Dokument nie ginie — zostaje zapisany do wyjaśnienia. | Sprawdź reguły szablonu w edytorze mapowań; jeśli problem się powtarza, zgłoś go administratorowi (szczegóły są w logu aplikacji). |

<a id="duplikaty"></a>

## Duplikaty

- Duplikatem jest dokument, którego wcześniej przyjęty, „żywy” (zatwierdzony lub do wyjaśnienia) odpowiednik ma ten sam plik albo tego samego dostawcę, rodzaj dokumentu i numer (porównywany bez wielkości liter, akcentów i spacji wokół `/` i `-`). Oryginałem jest zawsze dokument przyjęty wcześniej.
- **Zakres**: duplikaty wykrywane są osobno dla każdego klucza API i osobno dla panelu (faktury wgrane w panelu i próbki demo). Ta sama faktura wysłana dwoma różnymi kluczami albo raz kluczem, raz w panelu — *nie* jest duplikatem.
- W panelu: „To nie duplikat — przetwórz” (zgoda zapisywana w dokumencie, który jest przetwarzany dalej) albo „Odrzuć”. Po odrzuceniu oryginału jego duplikaty są przeliczane.

<a id="odrzucenie"></a>

## Ręczne odrzucenie i „Przywróć”

„Odrzuć” ustawia status „Odrzucona” i zapisuje, kto odrzucił. Takiego dokumentu nie zmieni ani „Przetwórz ponownie”, ani rozwiązywanie problemów, ani API (`reprocess` zwraca 409 z kodem `rejected`). Cofnąć odrzucenie można tylko przyciskiem **„Przywróć”** w widoku dokumentu — dokument jest wtedy przetwarzany od nowa; jeśli w międzyczasie późniejsza kopia tej faktury stała się aktywna, wraca do statusu „Duplikat”. Odrzucenia automatyczne (`unreadable`, `too_many_lines`) można przetworzyć ponownie bez „Przywróć”.

<a id="liczby"></a>

## Liczby

- Rozpoznawany jest przecinek i kropka dziesiętna oraz separatory tysięcy: `1 234,56`, `1.234,56`, `1,234.56` → `1234.56`.
- Liczby ujemne: `-5`, `5-` (minus na końcu), `(5,00)` (nawiasy), także minus typograficzny.
- Zapis wykładniczy: `1e3` → `1000`.
- Dopiski waluty i procentu przed lub po liczbie są pomijane (np. `12,50 zł`); litery w środku liczby to błąd.
- **Niejednoznaczne** są zapisy z jednym separatorem i dokładnie trzema cyframi po nim (`1,234`, `1.234`). Jeśli inne liczby w dokumencie jednoznacznie wskazują separator, zostanie on użyty; w przeciwnym razie powstaje problem [`ambiguous_number`](#ambiguous_number). Rozwiązanie: transformacja `{"decimal": ","}` (przecinek dziesiętny) albo `{"decimal": "."}` (kropka dziesiętna) w regule pola — panel podpowiada oba warianty z podglądem.
- W wyniku (JSON) liczby są tekstem z kropką dziesiętną: kwoty z 2 miejscami, ceny z 2–4 miejscami.

<a id="stawki-vat"></a>

## Stawki VAT bez wartości liczbowej

Pole `vat_rate` przyjmuje liczbę procent (np. `23`, `8`, `0`) albo kod: `zw` (zwolnione), `np`, `np I`, `np II` (nie podlega) i `oo` (odwrotne obciążenie). Kody rozpoznawane są bez wielkości liter i kropki na końcu (np. `ZW`, `np.`) i trafiają do wyniku jako tekst. Stawka między 0 a 1 (np. `0,23`) daje ostrzeżenie [`vat_rate_fraction`](#vat_rate_fraction).
