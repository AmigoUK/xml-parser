<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Edytor mapowań

Edytor mapowań to pełnoekranowy widok do ręcznej edycji reguł szablonu na przykładzie konkretnej faktury. Otwierasz go z widoku dokumentu (link „Otwórz edytor mapowań” przy problemie z polem) albo ze szczegółów szablonu („Otwórz edytor” — edytor użyje najnowszego dokumentu tego szablonu). Link „? Pomoc” na pasku edytora otwiera tę stronę w nowej karcie.

## Układ

1. **Wybór elementu** (lewa kolumna) — drzewo pliku; kliknij element, aby go zaznaczyć. Pogrubione są elementy grupujące (mające elementy podrzędne). Ścieżki zawierają element główny, np. `Faktura/Naglowek/Numer`; atrybuty mają postać `…/Ilosc/@unitCode`; w JSON ścieżki zaczynają się od `root/`, a w CSV mają postać `csv/row/<nazwa kolumny>`.
2. **Element pozycji** — zaznacz element powtarzany dla każdej pozycji (np. `Faktura/Pozycje/Pozycja`) i kliknij „← ustaw” w karcie „Element z pozycjami faktury”. Bez niego szablonu nie da się zapisać.
3. **Przypisanie pola** (środkowa kolumna) — przy polu kliknij „←”, aby przypisać zaznaczony element, „×”, aby usunąć regułę. Pola pozycji muszą wskazywać element *wewnątrz* elementu z pozycjami — zapisywane są jako ścieżki względne. Gwiazdka oznacza pole wymagane. Przyciski pod polem to podpowiedzi z procentem pewności; pole „wartość domyślna” działa, gdy w pliku brak wartości.
4. **Łańcuch transformacji** — lista JSON w polu pod regułą, wykonywana od lewej do prawej, np. `["trim", {"gs1": "10"}]`. Krok bez argumentu to sama nazwa, krok z argumentem — obiekt z jedną parą `{"nazwa": argument}`.
5. **Podgląd** (prawa kolumna) — po każdej zmianie edytor przelicza dokument i pokazuje problemy oraz wynik w formacie kanonicznym; nic nie jest zapisywane. Przycisk „Podgląd” wymusza przeliczenie.
6. **Zapis wersji** — „Zapisz nową wersję” (opcjonalnie z komentarzem) tworzy nową wersję szablonu i przetwarza dokument ponownie. Gdy nowe reguły usuwają mapowanie pola wymaganego, edytor poprosi o potwierdzenie. Gdy w międzyczasie ktoś zapisał nowszą wersję, zapis zostanie odrzucony z prośbą o odświeżenie edytora — cudza praca nie zostanie nadpisana. Dla dokumentu bez rozpoznanego dostawcy zapisywane są reguły robocze.

## Transformacje (biała lista)

Dozwolone są wyłącznie poniższe transformacje — nieznana nazwa albo zły argument blokuje zapis z komunikatem. Transformacje liczbowe (`decimal`, `convert`, `negate`) zwracają liczbę zawsze z kropką dziesiętną.

| Nazwa | Działanie | Argument | Przykład kroku | Wejście → wyjście |
| --- | --- | --- | --- | --- |
| <a id="t-trim"></a>`trim` | Usuń spacje z brzegów<br>Usuwa białe znaki z początku i końca. | brak | `"trim"` | `„ ABC ”` → `„ABC”` |
| <a id="t-upper"></a>`upper` | Wielkie litery | brak | `"upper"` | `„abc”` → `„ABC”` |
| <a id="t-lower"></a>`lower` | Małe litery | brak | `"lower"` | `„ABC”` → `„abc”` |
| <a id="t-decimal"></a>`decimal` | Liczba; separator dziesiętny jako argument, np. {"decimal": ","}<br>Bez argumentu separator jest wnioskowany z dokumentu; forma niejednoznaczna („1,234”) daje problem „ambiguous_number”. Wynik zawsze z kropką. | opcjonalny separator dziesiętny: "," albo "." | `{"decimal": ","}` | `„1 234,50”` → `„1234.5”` |
| <a id="t-strip_percent"></a>`strip_percent` | Usuń znak %<br>Typowo przed stawką VAT. | brak | `"strip_percent"` | `„23%”` → `„23”` |
| <a id="t-date"></a>`date` | Data wg formatu (np. %d.%m.%Y)<br>Wynik w formacie RRRR-MM-DD. | format daty w notacji strftime (wymagany) | `{"date": "%d.%m.%Y"}` | `„09.10.2026”` → `„2026-10-09”` |
| <a id="t-regex_extract"></a>`regex_extract` | Wytnij wyrażeniem regularnym<br>Wzorzec maks. 200 znaków, dopasowywane pierwsze 1 000 znaków wartości, limit czasu 0,2 s (ochrona przed ReDoS). | obiekt {"pattern": …, "group": …}; group domyślnie 0 | `{"regex_extract": {"pattern": "(\\d+)$", "group": 1}}` | `„FV/2026/123”` → `„123”` |
| <a id="t-map"></a>`map` | Zamień wartości wg słownika<br>Wartość spoza słownika przechodzi bez zmian. | słownik wartość źródłowa → wartość docelowa | `{"map": {"EA": "szt", "KGM": "kg"}}` | `„EA”` → `„szt”` |
| <a id="t-convert"></a>`convert` | Pomnóż przez współczynnik<br>Mnoży wartość przez współczynnik — ta sama reguła co przy przelicznikach. | współczynnik > 0 (liczba albo tekst; kropka = separator dziesiętny) | `{"convert": 12}` | `„2”` → `„24”` |
| <a id="t-constant"></a>`constant` | Stała wartość<br>Zastępuje wartość ze źródła stałą. | stała wartość | `{"constant": "PLN"}` | — → `„PLN”` |
| <a id="t-concat"></a>`concat` | Połącz kilka pól<br>Łączy wartości kilku elementów (puste są pomijane). W pozycjach ścieżki są względne wobec pozycji. | obiekt {"paths": \[ścieżki\], "sep": separator}; sep domyślnie spacja | `{"concat": {"paths": ["Faktura/Sprzedawca/Ulica", "Faktura/Sprzedawca/Miasto"], "sep": ", "}}` | — → `„Polna 1, Opole”` |
| <a id="t-split"></a>`split` | Podziel i weź część<br>Numeracja części od 0. | obiekt {"sep": separator, "index": nr części}; domyślnie spacja i 0 | `{"split": {"sep": " ", "index": 1}}` | `„Kowalski Jan”` → `„Jan”` |
| <a id="t-negate"></a>`negate` | Zmień znak (korekty)<br>Zmiana znaku — np. dla korekt. | brak | `"negate"` | `„100.00”` → `„-100”` |
| <a id="t-gs1"></a>`gs1` | Wyciągnij AI z kodu GS1-128<br>AI z datą (np. 17) zwraca datę RRRR-MM-DD. | numer AI, np. "10" (partia) albo "17" (data ważności) | `{"gs1": "10"}` | `„(01)05909999000013(10)ABC123(17)271231”` → `„ABC123”` |
| <a id="t-strip_ai_prefix"></a>`strip_ai_prefix` | Usuń prefiks AI 01 z EAN<br>Usuwa prefiks AI „01” z 16-cyfrowego zapisu EAN/GTIN; inne wartości bez zmian. | brak | `"strip_ai_prefix"` | `„0105909999000013”` → `„05909999000013”` |

Przykład dla `concat` zakłada w pliku elementy `Faktura/Sprzedawca/Ulica` = „Polna 1” i `Faktura/Sprzedawca/Miasto` = „Opole”.

## Liczby w transformacjach

- Rozpoznawane są separatory tysięcy (spacja, twarda spacja, apostrof), dopiski waluty/procentu (np. „zł”, „PLN”, „%”), nawiasy i minus na końcu jako liczba ujemna oraz zapis wykładniczy (`1.5e3` → `1500`).
- Wartość dłuższa niż 100 znaków albo z ponad 18 cyframi całkowitymi nie jest liczbą.
- Forma niejednoznaczna („1,234”) bez wskazanego separatora daje problem [`ambiguous_number`](statusy-i-problemy.md#ambiguous_number).
- Współczynnik `convert` podlega tej samej regule co przeliczniki: kropka jest zawsze dziesiętna, wynik musi być większy od zera i mieć najwyżej 12 cyfr całkowitych.
