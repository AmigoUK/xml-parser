<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Kartoteka i mapowania towarów

Każda pozycja faktury powinna wskazywać towar z **naszej kartoteki** (pole `product_index` w wyniku). Kartotekę i mapowania znajdziesz w menu *Dane*.

## Kartoteka towarów

Towar ma **indeks** (unikalny, maks. 64 znaki), nazwę (maks. 255 znaków), opcjonalny GTIN/EAN i jednostkę. GTIN jest sprawdzany (cyfra kontrolna, długość) i zapisywany jako 14 cyfr. Przy dodawaniu towaru z negocjacji podpowiadany jest kolejny wolny indeks `TOW-nnnn` (gdy wpisany indeks jest zajęty, nadawany jest kolejny wolny). Towaru użytego w dokumentach, mającego mapowania lub przeliczniki nie można usunąć.

![Kartoteka towarów demo: indeks, nazwa, GTIN i jednostka (JM) każdego towaru; „Import CSV” i „Dodaj” w prawym górnym rogu.](../../app/static/screenshots/06-kartoteka.png)

*Kartoteka towarów demo: indeks, nazwa, GTIN i jednostka (JM) każdego towaru; „Import CSV” i „Dodaj” w prawym górnym rogu.*

## Import CSV

*Kartoteka towarów* → „Import CSV”. Format pliku:

- pierwszy wiersz to nagłówek; kolumny rozpoznawane po nazwie (bez wielkości liter):

  | Pole | Dopuszczalne nazwy kolumny | Wymagana |
  | --- | --- | --- |
  | Indeks | `indeks`, `code`, `kod` | tak |
  | Nazwa | `nazwa`, `name` | tak |
  | GTIN/EAN | `gtin`, `ean` | nie |
  | Jednostka | `jednostka`, `jm`, `unit` | nie |
- separator `;`, `,` lub tabulator (wykrywany automatycznie, domyślnie `;`);
- kodowanie UTF-8 (także z BOM) albo Windows-1250;
- maks. 2 MB i 20 000 wierszy danych (nadmiarowe są pomijane).

```
indeks;nazwa;gtin;jednostka
TOW-0101;Mąka pszenna typ 650;5909999000105;kg
TOW-0102;Cukier puder 1 kg;;szt
```

Zasady importu:

- istniejący indeks jest **aktualizowany** (nazwa; GTIN i jednostka tylko, gdy podane), nowy — dodawany;
- wiersze bez indeksu lub nazwy są pomijane; za długi indeks/nazwa albo błędny GTIN — wiersz pominięty z błędem;
- nieznana jednostka — towar zostaje zaimportowany bez zmiany jednostki, a w raporcie pojawia się błąd;
- po imporcie widać podsumowanie: dodano / zaktualizowano / błędy; konflikt danych w bazie przerywa import i nic nie zostaje zapisane.

## Mapowania towarów dostawcy

Mapowanie łączy towar *u dostawcy* z naszym towarem. Powstaje w negocjacji (przypisanie towaru z „zapamiętaj”) albo ręcznie w *Mapowaniach towarów*. Pozycja jest dopasowywana w tej kolejności:

1. po **kodzie towaru dostawcy** (mapowanie tego dostawcy);
2. po **GTIN** z mapowań tego dostawcy;
3. po **nazwie** — tylko gdy pozycja nie ma ani kodu, ani GTIN (nazwa porównywana bez wielkości liter i nadmiarowych spacji);
4. po **GTIN z kartoteki** — towar o tym samym GTIN (dlatego np. próbka `epsilon.json` dopasowuje towary sama).

Mapowanie zapisuje kod i GTIN pozycji (jeśli je ma), a nazwę — tylko gdy brak obu. Pozycji bez kodu, GTIN i nazwy nie da się zapamiętać — przypisz towar tylko dla tej faktury. Nieprzypisany towar daje problem [`unmapped_product`](statusy-i-problemy.md#unmapped_product).
