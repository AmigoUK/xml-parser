# Changelog

All notable changes to **xml-parser** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

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

## [0.0.1] — 2026-10-10

### Added
- Szkielet aplikacji Flask, konfiguracja z `.env`, Docker Compose (MariaDB 11.4), `/healthz`.
- Stopka z kredytami i wersją.
- Strażnik danych prywatnych (`tests/test_no_private_data.py`) + hook pre-commit.
- Specyfikacja projektowa i plan etapu 1.

[Unreleased]: https://github.com/AmigoUK/xml-parser/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AmigoUK/xml-parser/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/AmigoUK/xml-parser/releases/tag/v0.0.1
