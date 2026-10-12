# Próbki demo

Wszystkie dane (firmy, NIP/VAT, adresy, numery, GTIN) są **fikcyjne**.
GTIN-y mają poprawne cyfry kontrolne (prefiks 590999…/400999… — nieprzydzielone, demonstracyjne).

| Plik | Format | Co pokazuje |
|---|---|---|
| alfa-1.xml | własny XML (PL) | nowy dostawca, brak waluty, `pcs`→`szt`, EAN z AI 01, partia i data z GS1-128 |
| alfa-2.xml | jw. | po nauczeniu na alfa-1 przechodzi automatycznie |
| beta-ksef.xml | KSeF FA(3)-podobny | `worek` → kg (×25), przelicznik |
| gamma-ubl.xml | UBL 2.1 | kody UN/ECE `C62`, `H87`, atrybut `unitCode` |
| delta.csv | CSV `;` | przecinek dziesiętny, data `DD.MM.RRRR`, `kart.` → szt (×12) |
| epsilon.json | JSON | `EA` → `szt`, dopasowanie towarów po GTIN |
| zeta.csv | CSV `;` | `wor.` → `worek`, przelicznik `1 worek = 25 kg` podpowiedziany z nazwy towaru — scenariusz z FAQ „worki → kilogramy” |

## Zestaw „Miesiąc faktur” (`demo/dataset/`)

Obok próbek leży pełny zestaw demo: 24 fikcyjne faktury sześciu dostawców z jednego miesiąca wraz z `manifest.json`
(kolejność, format, oczekiwane statusy). Powstaje deterministycznie z `tools/gen_demo_dataset.py`
(`--check` sprawdza, że pliki w repozytorium są identyczne co do bajtu z wynikiem generatora) i jest wczytywany z karty
„Zestaw demo” na stronie „O demo” albo skryptem `app/help_examples/zestaw-demo.sh`. Próbki z tego katalogu
pozostają szybką ścieżką: jeden plik, jedna lekcja (np. `delta.csv` z `kart.` → szt nie należy do zestawu).
