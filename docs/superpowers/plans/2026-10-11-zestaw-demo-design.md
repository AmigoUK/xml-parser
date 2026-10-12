# Zestaw demo „Miesiąc faktur” — projekt zatwierdzony przez użytkownika 2026-10-11 („ok” = rekomendacje)

**Status: zaimplementowany w v0.8.0** (projekt pierwotnie zaplanowany na v0.6.0; webhooki przesunięte na v0.7.0, zestaw demo na v0.8.0).

- `demo/dataset/` + `manifest.json`; generator deterministyczny `tools/gen_demo_dataset.py` (seed RNG, tryb `--check`); dane w 100% fikcyjne (strażnik `tests/test_no_private_data.py`).
- Dostawcy (6): Alfa (XML własny PL), Beta (KSeF FA(3)-podobny), Gamma (UBL 2.1), Epsilon (JSON), Zeta (CSV) + nowy „Eta Packaging Sp. z o.o.” (XML z angielskimi tagami) × 4 faktury z jednego miesiąca = 24 pliki. Delta (CSV) nie wchodzi do zestawu — zostaje próbką w `demo/samples`; jej pułapka `kart.` przeniesiona do trzeciej faktury Zety.
- Pułapki: nowy dostawca, nieznane jednostki (pcs, C62, H87, EA, wor., kart.), towar spoza kartoteki, nowy alias jednostki (PCE) w 3. fakturze, niezgodność sum (ostrzeżenie), duplikat bajtowy (ten sam plik 2×), brak waluty.
- Kontrakt manifestu: kolejność (`order`), faza (`first`/`rest`), dostawca, format oraz `expected.on_ingest` (status i problemy po wczytaniu) i `expected.after_resolve` (status po rozwiązaniu podpowiedziami; `null` dla faktur czystych); sumy sha256 plików sprawdzane przed wczytaniem.
- Duplikat rozpoznawany po bajtach (sha256 pliku), nie po numerze faktury: 20. plik jest kopią 14.
- Reguła R19: czwarte faktury dostawców zależą wyłącznie od nauki z pierwszej fazy (i kartoteki demo), więc faza „pozostałe” wczytana jedną partią, przed rozwiązaniem faktur 15–18, zgadza się z manifestem.
- `/demo`: karta „Zestaw demo” — „Wczytaj pierwsze (6)”, „Wczytaj pozostałe (18)”, „Wczytaj wszystko (24)”, „Resetuj zestaw demo” (administrator; dawniej „Wyczyść dane demo”), tabela postępu (status oczekiwany i rzeczywisty każdego pliku, source=demo); serwis `demo_dataset`.
- Import przez API: skrypt `app/help_examples/zestaw-demo.sh` (`XP_API_KEY`, fazy pierwsze/pozostale/wszystko), temat Pomocy `zestaw-demo` i FAQ `zestaw-demo-api`.
- Testy: manifest ↔ pliki; e2e: pierwsze 6 → needs_review, rozwiązanie podpowiedziami (tests/test_learning.py), pozostałe → statusy wg manifestu; reset → ponowny przebieg identyczny.
- Pomoc: temat `zestaw-demo`; README: sekcja „Tryb demo” i zrzut `14-demo-zestaw`.
