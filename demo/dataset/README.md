# Zestaw demo „Miesiąc faktur”

<!-- Wygenerowano przez tools/gen_demo_dataset.py — nie edytuj ręcznie. -->

Miesiąc pracy działu zakupów fikcyjnej „Piekarni Demo”: 24 faktury od sześciu dostawców z października 2026 w trzech formatach (XML, JSON, CSV). Pierwsza faktura każdego dostawcy wymaga negocjacji, kolejne przechodzą automatycznie albo pokazują jedną nową pułapkę (nowa jednostka, nowy towar, brak waluty, niezgodność sumy, duplikat). Wszystkie dane (firmy, NIP/VAT, adresy, numery, GTIN) są **fikcyjne**.

Plik `manifest.json` opisuje każdy plik i oczekiwany wynik: `on_ingest` — status i kody problemów zaraz po wczytaniu (w kolejności `order`, na świeżej bazie z kartoteką demo), `after_resolve` — po wybraniu pierwszej podpowiedzi przy każdym problemie (z „zapamiętaj w szablonie”). Zgodność manifestu z zachowaniem parsera sprawdza `tests/test_demo_dataset_files.py`.

## Dostawcy

| Klucz | Dostawca | NIP/VAT | Format |
|---|---|---|---|
| alfa | Hurtownia Alfa Sp. z o.o. | 9990000011 | XML |
| beta | Młyn Beta Sp. z o.o. | 9990000022 | XML |
| eta | Eta Packaging Sp. z o.o. | 9990000077 | XML |
| gamma | Gamma Aromen GmbH | DE999999999 | XML |
| epsilon | Epsilon Dairy Ltd | GB999000044 | JSON |
| zeta | Hurtownia Zeta Sp. j. | 9990000066 | CSV |

## Pliki

| Nr | Plik | Dostawca | Co pokazuje | Po wczytaniu | Po pierwszych podpowiedziach |
|---|---|---|---|---|---|
| 1 | 01-alfa-1.xml | Hurtownia Alfa Sp. z o.o. | nowy dostawca, brak waluty, jednostka „pcs”, towar po kodzie dostawcy | do przejrzenia: `unknown_supplier`, `unknown_unit`, `unmapped_field`, `unmapped_product` | zatwierdzona |
| 2 | 02-beta-1.xml | Młyn Beta Sp. z o.o. | nowy dostawca (KSeF), „worek” → kg ×25 z nazwy towaru, towar po nazwie | do przejrzenia: `missing_conversion`, `unknown_supplier`, `unmapped_product` | zatwierdzona |
| 3 | 03-eta-1.xml | Eta Packaging Sp. z o.o. | nowy dostawca (XML z angielskimi tagami), jednostka „pcs”, towar po nazwie | do przejrzenia: `unknown_supplier`, `unknown_unit`, `unmapped_product` | zatwierdzona |
| 4 | 04-gamma-1.xml | Gamma Aromen GmbH | nowy dostawca (UBL 2.1), kody jednostek „C62”/„H87”, towar po nazwie | do przejrzenia: `unknown_supplier`, `unknown_unit`, `unmapped_product` | zatwierdzona |
| 5 | 05-epsilon-1.json | Epsilon Dairy Ltd | nowy dostawca (JSON), jednostka „EA”, towary rozpoznane po GTIN | do przejrzenia: `unknown_supplier`, `unknown_unit` | zatwierdzona |
| 6 | 06-zeta-1.csv | Hurtownia Zeta Sp. j. | nowy dostawca (CSV), „wor.” → worek (obok pełnej nazwy „worek”), 1 worek = 25 kg z nazwy towaru, towary spoza kartoteki | do przejrzenia: `missing_conversion`, `unknown_supplier`, `unknown_unit`, `unmapped_product` | zatwierdzona |
| 7 | 07-alfa-2.xml | Hurtownia Alfa Sp. z o.o. | druga faktura — przechodzi automatycznie | zatwierdzona | — |
| 8 | 08-beta-2.xml | Młyn Beta Sp. z o.o. | druga faktura — przechodzi automatycznie | zatwierdzona | — |
| 9 | 09-eta-2.xml | Eta Packaging Sp. z o.o. | druga faktura — przechodzi automatycznie | zatwierdzona | — |
| 10 | 10-gamma-2.xml | Gamma Aromen GmbH | druga faktura — przechodzi automatycznie | zatwierdzona | — |
| 11 | 11-epsilon-2.json | Epsilon Dairy Ltd | druga faktura — przechodzi automatycznie | zatwierdzona | — |
| 12 | 12-zeta-2.csv | Hurtownia Zeta Sp. j. | druga faktura — przechodzi automatycznie | zatwierdzona | — |
| 13 | 13-alfa-3.xml | Hurtownia Alfa Sp. z o.o. | niezgodność sumy w pozycji (ilość × cena ≠ netto) — ostrzeżenie, faktura zatwierdzona | zatwierdzona: `sum_mismatch_line` (ostrzeżenie) | — |
| 14 | 14-beta-3.xml | Młyn Beta Sp. z o.o. | czysta faktura | zatwierdzona | — |
| 15 | 15-eta-3.xml | Eta Packaging Sp. z o.o. | towar spoza kartoteki (nowy GTIN) — „utwórz towar” | do przejrzenia: `unmapped_product` | zatwierdzona |
| 16 | 16-gamma-3.xml | Gamma Aromen GmbH | nowy alias jednostki „PCE” zamiast „C62” | do przejrzenia: `unknown_unit` | zatwierdzona |
| 17 | 17-epsilon-3.json | Epsilon Dairy Ltd | brak klucza waluty — pierwsza podpowiedź to PLN, ale ten dostawca rozlicza się w GBP: wybierz GBP | do przejrzenia: `unmapped_field` | zatwierdzona |
| 18 | 18-zeta-3.csv | Hurtownia Zeta Sp. j. | „kart.” → karton (obok pełnej nazwy „karton”), 1 karton = 20 szt z nazwy towaru, nowy towar | do przejrzenia: `missing_conversion`, `unknown_unit`, `unmapped_product` | zatwierdzona |
| 19 | 19-alfa-4.xml | Hurtownia Alfa Sp. z o.o. | czysta faktura | zatwierdzona | — |
| 20 | 20-beta-3-ponownie.xml | Młyn Beta Sp. z o.o. | ten sam plik co 14-beta-3.xml wysłany drugi raz — duplikat | duplikat: `duplicate` | — |
| 21 | 21-eta-4.xml | Eta Packaging Sp. z o.o. | czysta faktura | zatwierdzona | — |
| 22 | 22-gamma-4.xml | Gamma Aromen GmbH | czysta faktura | zatwierdzona | — |
| 23 | 23-epsilon-4.json | Epsilon Dairy Ltd | czysta faktura | zatwierdzona | — |
| 24 | 24-zeta-4.csv | Hurtownia Zeta Sp. j. | czysta faktura | zatwierdzona | — |

Wczytanie wszystkiego naraz bez nauki: pliki 01–19 i 21–24 trafiają do kolejki (nieznany dostawca), plik 20 jest duplikatem pliku 14.

## Regeneracja

```
.venv/bin/python tools/gen_demo_dataset.py          # zapisuje pliki do demo/dataset/
.venv/bin/python tools/gen_demo_dataset.py --check  # kod 0, gdy pliki są aktualne
```

Generator jest deterministyczny (ziarno 20261001 losuje tylko ilości): ta sama wersja daje te same bajty, więc pliki są commitowane, a test pilnuje, że nikt ich nie zmienił ręcznie.
