# Project Overview
Uczący się parser faktur strukturalnych (XML w tym KSeF/UBL, JSON, CSV) do jednego dokumentu kanonicznego, z szablonami dostawców tworzonymi przez „negocjację” w panelu. Udostępnia REST API v1 (`X-API-Key`) dla innych systemów oraz panel webowy po polsku z trybem demo. Bez LLM — deterministyczne reguły i transformacje z białej listy.

# Tech Stack
- Python 3.12 (obraz `python:3.12-slim`), lokalnie `.venv/bin/python`
- Flask 3.1.3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.54, Flask-Migrate 4.1.0 (Alembic), Flask-Login 0.6.3, Flask-WTF 1.3.0 (CSRF)
- lxml 6.1.3, rapidfuzz 3.14.6, PyYAML 6.0.3, regex 2026.9.29 (timeouty przeciw ReDoS), python-dotenv 1.2.4
- MariaDB 11.4 (prod, PyMySQL 1.2.3, utf8mb4_unicode_ci); SQLite w testach
- gunicorn 26.2.0 (gthread), Docker Compose; frontend: Jinja2 + vendorowane Bootstrap 5 / HTMX / Alpine.js (bez CDN)
- Testy: pytest (`.venv/bin/python -m pytest -q`)

# Naming & Coding Conventions
- Kod i identyfikatory po angielsku; UI, komunikaty błędów, komentarze, CHANGELOG i commity po polsku.
- Układ: `app/ingest` (czytniki), `app/engine` (czysta logika: drzewo, transformacje, GS1, szablon, walidacja, podpowiedzi), `app/services` (orkiestracja + DB), `app/web` (panel), `app/api` (REST v1), testy w `tests/test_<obszar>.py`.
- Silnik (`app/engine`) bez dostępu do DB; błędy wejścia jako `ReaderError`/problemy (`issues`), nigdy surowy wyjątek → 500.
- Commity: `feat(scope): …` / `fix(scope): …` / `chore(release): vX.Y.Z — …`; SemVer + CHANGELOG (Keep a Changelog) + tag + GitHub Release.
- Stopka z kredytami na każdej stronie poza pełnoekranowym edytorem mapowań.
- Demo lokalnie: port hosta > 18500 (`APP_PORT` w `.env`), dostęp przez Tailscale MagicDNS.
- Po każdej zmianie treści pomocy (`app/help_content.py`, `app/templates/help/`) uruchom `.venv/bin/python tools/export_help.py` — `tests/test_help_export.py` pilnuje aktualności `docs/pomoc/`.
- Zrzuty ekranu do `docs/screenshots/` wyłącznie z odizolowanej instancji (świeża SQLite + fikcyjne próbki `demo/samples/`), nigdy z żywego demo.

# Protected Files
- `private/` — realne faktury dostawców i `forbidden-tokens.txt`. NIGDY nie czytać do repo, nie kopiować, nie cytować; nie może trafić do gita ani obrazu Docker.
- `.env` — sekrety lokalne (nie wypisywać wartości).
- `tests/test_no_private_data.py` — strażnik danych prywatnych; nie osłabiać.
- `migrations/versions/96049e3e3e09_schemat_poczatkowy.py` i każda już wydana migracja — nie edytować, zmiany schematu tylko nowymi migracjami.
