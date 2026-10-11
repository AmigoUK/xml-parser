# Zestaw demo „Miesiąc faktur” — projekt zatwierdzony przez użytkownika 2026-10-11 („ok” = rekomendacje)

Wydanie: v0.6.0 (po v0.5.0); webhooki (Etap B planu API) przesunięte na v0.7.0.

- `demo/dataset/` + `manifest.json`; generator deterministyczny `tools/gen_demo_dataset.py` (seed RNG); dane w 100% fikcyjne (strażnik `tests/test_no_private_data.py`).
- Dostawcy: Alfa (XML własny PL), Beta (KSeF FA(3)-podobny), Gamma (UBL 2.1), Delta (CSV), Epsilon (JSON) + nowy „Zeta” (XML z angielskimi tagami) × 4 faktury z jednego miesiąca = 24 pliki.
- Pułapki: nowy dostawca, nieznane jednostki (pcs, kart., EA), towar spoza kartoteki, nowy alias jednostki w 3. fakturze, niezgodność sum (ostrzeżenie), duplikat (ta sama faktura 2×), brak waluty.
- Manifest: kolejność, dostawca, format, oczekiwany wynik przy pierwszym i kolejnym przebiegu.
- `/demo`: sekcja „Zestaw demo” — „Wczytaj pierwsze faktury (6)”, „Wczytaj pozostałe (18)”, „Wczytaj wszystko naraz”, „Resetuj zestaw demo” (= dotychczasowy pełny reset_demo), tabela postępu (status każdej faktury z bazy po nazwie pliku/source=demo).
- Import przez API: skrypt curl w Pomocy (Integracja/FAQ) na zestawie.
- Testy: manifest ↔ pliki; e2e: pierwsze 6 → needs_review, rozwiązanie podpowiedziami (tests/test_learning.py), pozostałe → statusy wg manifestu; reset → ponowny przebieg identyczny.
- Pomoc: opis zestawu w temacie demo/pierwsza faktura; README: akapit + ewentualny zrzut.
