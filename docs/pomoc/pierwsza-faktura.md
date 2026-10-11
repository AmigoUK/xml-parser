<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Pierwsza faktura dostawcy

Pierwsza faktura nowego dostawcy prawie zawsze trafia do **Kolejki** ze statusem „Do wyjaśnienia”: system nie zna jeszcze dostawcy, jego jednostek ani towarów. Rozwiązujesz problemy w widoku dokumentu — to jest *negocjacja*. Po każdej decyzji dokument jest automatycznie przetwarzany ponownie.

![Kolejka do wyjaśnienia: pierwsze faktury nowych dostawców (gamma-ubl.xml, epsilon.json) ze statusem „Do wyjaśnienia” i liczbą problemów; numer w kolumnie „#” otwiera widok dokumentu.](../../app/static/screenshots/03-kolejka.png)

*Kolejka do wyjaśnienia: pierwsze faktury nowych dostawców (gamma-ubl.xml, epsilon.json) ze statusem „Do wyjaśnienia” i liczbą problemów; numer w kolumnie „#” otwiera widok dokumentu.*

## Widok dokumentu

- Na górze lista problemów (pokazywanych jest pierwszych 50; kolejne pojawią się po rozwiązaniu widocznych). Czerwony pasek i plakietka „blokuje” — problem blokujący; żółty — ostrzeżenie. Link **?** przy problemie prowadzi do jego opisu.
- Poniżej drzewo pliku źródłowego (po najechaniu widać pełną ścieżkę elementu) i wynik w formacie kanonicznym.
- Przyciski: „Przetwórz ponownie” (aktywną wersją szablonu), „JSON”, „Plik źródłowy”; przy dokumencie odrzuconym ręcznie — „Przywróć”.

![Widok dokumentu gamma-ubl.xml: na górze problemy blokujące z podpowiedziami (nowy dostawca, nieznane jednostki „C62” i „H87”, nieprzypisany towar) i przełącznikiem „Zapamiętaj”, niżej drzewo pliku źródłowego i wynik w formacie kanonicznym.](../../app/static/screenshots/04-dokument.png)

*Widok dokumentu gamma-ubl.xml: na górze problemy blokujące z podpowiedziami (nowy dostawca, nieznane jednostki „C62” i „H87”, nieprzypisany towar) i przełącznikiem „Zapamiętaj”, niżej drzewo pliku źródłowego i wynik w formacie kanonicznym.*

## „Tylko ta faktura” czy „zapamiętaj w szablonie”

Przy większości formularzy jest przełącznik **„Zapamiętaj w szablonie / słowniku dostawcy (inaczej — tylko ta faktura)”**, domyślnie włączony.

| Problem | Zapamiętaj (włączone) | Tylko ta faktura (wyłączone) |
| --- | --- | --- |
| Brak pola nagłówka | nowa wersja szablonu: ścieżka w pliku albo wartość domyślna | wartość zapisana tylko w tym dokumencie |
| Brak pola pozycji / elementu z pozycjami | nowa wersja szablonu | niedostępne — pola pozycji trzeba zapamiętać |
| Nieznana jednostka | alias jednostki tego dostawcy | przypisanie tylko w tym dokumencie |
| Nieprzypisany towar | mapowanie towaru dostawcy (kod, GTIN albo nazwa) | przypisanie w tym dokumencie (wszystkie pozycje z tym samym towarem) |
| Brak przelicznika | zawsze zapamiętywany — dla wszystkich towarów dostawcy albo tylko dla tego towaru |  |
| Dostawca, duplikat | decyzja zawsze zapisywana (nowy dostawca / przypisanie; „To nie duplikat” albo „Odrzuć”) |  |

Aliasów, przeliczników i mapowań towarów nie da się zapamiętać, dopóki dostawca nie jest rozpoznany — dlatego zaczynaj od problemu „Nie rozpoznano dostawcy”. Szablon dostawcy powstaje przy rozpoznaniu dostawcy.

## Ponowne przetworzenie

Każde rozwiązanie problemu (poza „Odrzuć”) przetwarza dokument ponownie. Ręcznie — przyciskiem „Przetwórz ponownie” (np. po zmianie kartoteki, słowników albo szablonu w edytorze) albo przez API (`POST /api/v1/documents/{id}/reprocess`). Dokument odrzucony ręcznie pozostaje odrzucony, dopóki nie użyjesz „Przywróć”.

## Przykład: alfa-1.xml → alfa-2.xml

Próbki demo są fikcyjne (Hurtownia Alfa). Po wczytaniu `alfa-1.xml` pojawiają się cztery problemy blokujące:

1. **Nie rozpoznano dostawcy** — „Utwórz i zapamiętaj” z nazwą i NIP-em odczytanymi z faktury (Hurtownia Alfa Sp. z o.o.).
2. **Brak wymaganego pola „Waluta”** — wybierz wartość domyślną `PLN` z zaznaczonym „zapamiętaj”; trafi do wartości domyślnych szablonu.
3. **Nieznana jednostka „pcs”** — wskaż `szt` (powstaje alias dostawcy `pcs` → `szt`).
4. **Pozycja 3: nie przypisano towaru** (A-300 Masa marcepanowa 5 kg) — przypisz podpowiadany `TOW-0003`; powstaje mapowanie kodu dostawcy na nasz towar.

Pozostałe pozycje zostały dopasowane po GTIN z kartoteki. Dokument dostaje status „Zatwierdzona”. Teraz wczytaj `alfa-2.xml`: dostawca jest rozpoznawany po NIP, szablon po odcisku struktury, a alias i mapowanie z pierwszej faktury działają — faktura zostaje **zatwierdzona automatycznie**, bez pytań.
