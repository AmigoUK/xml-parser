<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Jednostki, aliasy i przeliczniki

Każda pozycja faktury kończy w **naszej** jednostce miary. Słowniki znajdziesz w menu *Dane*: „Jednostki”, „Aliasy jednostek” i „Przeliczniki”.

## Jednostki

Jednostka ma kod (zapisywany małymi literami, np. `szt`, `kg`), nazwę i znacznik **„jednostka bazowa”**. Pozycja w jednostce bazowej nie wymaga przelicznika; pozycja w jednostce niebazowej (np. `karton`, `worek`, `opak`) musi mieć przelicznik na jednostkę bazową — inaczej pojawia się problem [`missing_conversion`](statusy-i-problemy.md#missing_conversion). Jednostki używanej w dokumentach, aliasach, towarach lub przelicznikach nie można usunąć.

## Aliasy — globalne i dostawcy

Alias mówi, że zapis jednostki w pliku dostawcy (np. `pcs`, `kart.`, `C62`) oznacza naszą jednostkę. Kolejność rozpoznawania:

1. zapis równy kodowi naszej jednostki (bez spacji na brzegach, bez wielkości liter) — np. `KG` → `kg`;
2. alias **tego dostawcy**;
3. alias **globalny** (pole „Dostawca” puste = „wszyscy”).

Przy porównywaniu aliasów nie mają znaczenia wielkość liter, znaki diakrytyczne ani wielokrotne spacje. Alias zapamiętany w negocjacji jest zawsze aliasem dostawcy; aliasy globalne dodasz w słowniku. Jeden alias może istnieć tylko raz dla danego dostawcy (i raz globalnie). Nierozpoznana jednostka daje problem [`unknown_unit`](statusy-i-problemy.md#unknown_unit).

## Przeliczniki

Przelicznik „1 *z jednostki* = X *na jednostkę*” może dotyczyć dostawcy, towaru, obu albo wszystkich (puste pola = „wszyscy” / „wszystkie”). Wybierany jest najbardziej szczegółowy:

1. ten dostawca i ten towar,
2. ten dostawca, wszystkie towary,
3. wszyscy dostawcy, ten towar,
4. wszyscy dostawcy, wszystkie towary.

Po przeliczeniu ilość jest **mnożona** przez współczynnik, cena jednostkowa netto — **dzielona**, a w pozycji zapisywana jest jednostka docelowa i współczynnik (`conversion_factor`).

![Tabela przeliczników jednostek z kolumnami przelicznik, dostawca i towar oraz przyciskami Edytuj i Usuń](../../app/static/screenshots/07-przeliczniki.png)

*Przeliczniki jednostek zapamiętane w negocjacji: 1 worek = 25 kg (Młyn Beta) i 1 karton = 12 szt (Opakowania Delta), oba dla wszystkich towarów dostawcy.*

**Kropka jest zawsze separatorem dziesiętnym w przelicznikach** (w słowniku, w negocjacji i w transformacji `convert`): `1.125` = 1,125, a `1.000` = 1. Przecinek przed dokładnie trzema cyframi (`1,125`) jest niejednoznaczny i zostanie odrzucony z podpowiedzią, co wpisać. Przelicznik musi być większy od zera i mieć najwyżej 12 cyfr całkowitych.

## Przykład: „kart.” → szt ×12

Faktura CSV Opakowań Delta (próbka demo `delta.csv`) ma pozycję „Pudełko na tort 30x30”: ilość `2`, jednostka `kart.`, cena `96,00`.

1. Problem „Nieznana jednostka „kart.”” — wskaż `karton` (podpowiedź), z „zapamiętaj”: powstaje alias dostawcy `kart.` → `karton`.
2. `karton` nie jest jednostką bazową, więc pojawia się „brak przelicznika” — wpisz `1 karton = 12 szt` „dla wszystkich towarów dostawcy”.
3. Wynik pozycji: ilość `24` szt, cena netto `8.00`, przelicznik `12`.

Nie mapuj `kart.` bezpośrednio na `szt` — `szt` jest jednostką bazową, więc ilość nie zostałaby przeliczona (2 szt zamiast 24).

Ten sam scenariusz dla worków i kilogramów, z zrzutem i listą pułapek: [FAQ — „Dostawca sprzedaje w workach, a my liczymy w kilogramach”](faq.md#worek-na-kg).
