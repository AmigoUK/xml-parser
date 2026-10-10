# XML Parser faktur — Etap 1 (MVP demo v0.1.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uczący się parser faktur strukturalnych (XML/JSON/CSV) z REST API i panelem po polsku. Pierwsza faktura dostawcy trafia do „negocjacji”, a kolejne są czytane automatycznie z zapamiętanego szablonu.

**Architecture:** Czysty silnik (`app/engine/`, bez Flaska i bazy) zamienia plik na `SourceTree` (płaskie ścieżki) i stosuje deklaratywny szablon (ścieżka + łańcuch transformacji). Słowniki (jednostki, przeliczniki, towary) dostaje przez interfejs `Lookups`. Warstwa usług (`app/services/`) robi pipeline: ingest → identyfikacja dostawcy → apply → walidacja → status, a także negocjację, która zapisuje nowe wersje szablonów i wpisy słownikowe. Flask udostępnia REST API v1 (klucze API) i panel Jinja2 + HTMX + Alpine.js.

**Tech Stack:** Python 3.12, Flask 3.1.3, Flask-SQLAlchemy 3.1.1 + SQLAlchemy 2.0.54, Flask-Migrate 4.1.0, Flask-Login 0.6.3, Flask-WTF 1.3.0, lxml 6.1.3, rapidfuzz 3.14.6, PyYAML 6.0.3, PyMySQL 1.2.3, gunicorn 26.2.0, python-dotenv 1.2.4, MariaDB 11.4, Docker Compose; testy: pytest 9.1.1 (SQLite in-memory). Frontend vendorowany: Bootstrap 5.3.3, htmx 2.0.4, Alpine.js 3.14.8, swagger-ui-dist 5.18.2.

**Spec:** `docs/superpowers/specs/2026-10-10-xml-invoice-parser-design.md`

## Global Constraints

- Cały interfejs, komunikaty problemów i błędów API (`message`) **po polsku**, z pełnymi znakami diakrytycznymi. Identyfikatory w kodzie i kody problemów po angielsku.
- **Realne faktury i dane nabywcy nigdy w repo.** Tylko `private/` (w `.gitignore`). Próbki w `demo/samples/` są w całości fikcyjne. Przed **każdym** commitem: `git add …` → `pytest tests/test_no_private_data.py -q` (hook `pre-commit` robi to automatycznie).
- Zakazane jest wpisywanie do śledzonych plików nazw i numerów VAT z prywatnych faktur. Strażnik zna je wyłącznie jako hashe SHA-256.
- Kwoty zawsze jako `Decimal`, a w wyniku JSON jako stringi: kwoty pieniężne 2 miejsca (`"80.50"`), ceny jednostkowe 2–4 miejsca, ilości bez zbędnych zer (`"5"`, `"2.5"`). Nigdy `float`.
- Daty w wyniku jako ISO `YYYY-MM-DD`.
- Brak hardkodów domen, hostów, ścieżek i sekretów: wszystko z `.env` lub configu (`.env.example` w repo).
- Bez CDN w runtime: wszystkie biblioteki frontendowe w `app/static/vendor/`.
- Port aplikacji 5010. Bind hosta konfigurowalny (`APP_BIND`, domyślnie `0.0.0.0`, żeby działał dostęp przez Tailscale).
- Stopka z kredytami na każdej stronie panelu **poza** pełnoekranowym edytorem mapowań: `dev@attv.uk · Project & Development: Tomasz 'Amigo' Lewandowski · www.attv.uk · GitHub · v{wersja}`, GitHub → `https://github.com/AmigoUK/xml-parser`.
- Wersja: jedyne źródło to `pyproject.toml` `[project] version`. Start `0.0.1`, koniec etapu `0.1.0`. CHANGELOG w formacie Keep a Changelog 1.1.0.
- Commity kończą się dwiema liniami: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` oraz `Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N`.
- Listy CRUD zawsze z przyciskami „Edytuj” i „Usuń”, nie tylko „Dodaj”.
- Transformacje wyłącznie z białej listy (brak `eval`). Regex: wzorzec ≤ 200 znaków, wejście ≤ 1000 znaków.
- XML z `<!DOCTYPE` lub `<!ENTITY` jest odrzucany. Parser lxml: `resolve_entities=False`, `no_network=True`, `huge_tree=False`.
- Limit rozmiaru dokumentu 10 MB (`MAX_DOCUMENT_BYTES`).

## Review Focus

1. **Plik nieczytelny lub pusty** (zły XML, pusty upload, CSV bez wierszy, binarka): dokument dostaje status `rejected` z polskim komunikatem `unreadable`, a API zwraca 201 z tym statusem, nie 500. → test w Task 11 (`test_unreadable_file_rejected`) i Task 13 (`test_api_empty_body_400`).
2. **Liczby w lokalnych formatach** (`1 234,56`, `1.234,56`, `12,5`, `0%`, wartości z symbolem waluty `£80.50`) muszą dać poprawny `Decimal`, a nie błąd ani zły wynik. → `test_to_decimal_formats` w Task 5.
3. **Faktura jednopozycyjna** (brak powtarzalnego elementu): wykrycie pozycji musi zadziałać po nazwach podpowiedzi (`Pozycja`, `FaWiersz`, `InvoiceLine`, `items`, `row`). → `test_detect_single_line_by_hint` w Task 3.
4. **Ta sama faktura wgrana dwa razy** (identyczny plik lub ten sam dostawca i numer): status `duplicate`, bez podwójnego zatwierdzenia. → `test_duplicate_same_file` i `test_duplicate_same_supplier_number` w Task 11.
5. **Nowy dostawca w znanym formacie** (inny NIP, struktura jak istniejący szablon): system nie może przypisać faktury do starego dostawcy. Ma pokazać `unknown_supplier` z odczytanymi danymi nowego dostawcy i podpowiedzią sklonowania szablonu. → `test_same_format_new_supplier_not_misattributed` w Task 11.

---

## File Structure

```
xml-parser/
├── pyproject.toml                 # metadane + wersja (jedyne źródło)
├── requirements.txt / requirements-dev.txt
├── Dockerfile, docker-compose.yml, docker/entrypoint.sh, .env.example, .dockerignore
├── CHANGELOG.md, README.md
├── tools/pre-commit               # uruchamia strażnika danych prywatnych
├── data/synonyms.yaml             # słownik synonimów tagów + jednostek UN/ECE
├── demo/samples/                  # fikcyjne faktury demo (7 plików, korekta w E2)
├── migrations/                    # Alembic (Flask-Migrate)
├── app/
│   ├── __init__.py                # create_app()
│   ├── config.py                  # Config z env
│   ├── extensions.py              # db, migrate, login_manager, csrf
│   ├── version.py                 # __version__ z pyproject.toml
│   ├── models.py                  # wszystkie modele SQLAlchemy
│   ├── engine/                    # CZYSTY silnik — bez Flaska/bazy
│   │   ├── tree.py                # Node, SourceTree, ścieżki, wykrycie pozycji, fingerprint
│   │   ├── values.py              # to_decimal, fmt_*, parse_date, normalize_gtin
│   │   ├── gs1.py                 # parser GS1-128, GTIN check digit
│   │   ├── transforms.py          # rejestr transformacji, apply_chain
│   │   ├── canonical.py           # definicje pól, empty_invoice, get/set_path
│   │   ├── issues.py              # Issue, BLOCKING/WARNING
│   │   ├── lookups.py             # protokół Lookups + MemoryLookups
│   │   ├── template.py            # apply_template
│   │   ├── validate.py            # validate_invoice
│   │   └── suggest.py             # synonimy, kandydaci, draft_rules, podpowiedzi
│   ├── ingest/
│   │   ├── __init__.py            # read_document(), ReaderError
│   │   ├── xml_reader.py, json_reader.py, csv_reader.py
│   ├── services/
│   │   ├── storage.py             # surowe pliki po sha256
│   │   ├── lookups_db.py          # DbLookups (implementacja Lookups na bazie)
│   │   ├── templates.py           # new_version, active_rules, ensure_template
│   │   ├── pipeline.py            # ingest, process, identify, enrich
│   │   ├── negotiation.py         # resolve(...) — akcje negocjacji
│   │   ├── apikeys.py             # create_key, verify_key
│   │   ├── audit.py               # audit()
│   │   └── seed.py                # seed_base, seed_demo, reset_demo
│   ├── api/__init__.py, api/routes.py
│   ├── web/                       # blueprinty panelu
│   │   ├── __init__.py            # register_web(app)
│   │   ├── auth.py, documents.py, crud.py, catalog.py, templates_views.py,
│   │   ├── apikeys.py, history.py, demo.py
│   ├── templates/                 # Jinja2 (po polsku)
│   └── static/ (app.css, editor.js, openapi.yaml, vendor/)
└── tests/
```

---
### Task 1: Scaffold aplikacji, Docker, strażnik danych prywatnych, wydanie v0.0.1

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `docker/entrypoint.sh`, `CHANGELOG.md`, `README.md`, `tools/pre-commit`
- Create: `app/__init__.py`, `app/config.py`, `app/extensions.py`, `app/version.py`, `app/templates/base.html`, `app/templates/_footer.html`, `app/static/app.css`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_no_private_data.py`, `tests/test_app.py`

**Interfaces:**
- Produces: `create_app(config_overrides: dict | None = None) -> Flask`; `app.extensions`: `db`, `migrate`, `login_manager`, `csrf`; `app.version.__version__: str`; szablon `base.html` z blokami `title`, `content`, `scripts` i zmienną `full_screen` (gdy `True`, bez stopki i navbara); context processor wstrzykujący `APP_VERSION`, `REPO_URL`, `DEMO_MODE`; endpoint `GET /healthz` → `{"status": "ok", "version": ...}`; fixture'y pytest `app`, `client`.

- [ ] **Step 1: Pliki projektu i zależności**

`pyproject.toml`:
```toml
[project]
name = "xml-parser"
version = "0.0.1"
description = "Uczący się parser faktur strukturalnych (XML/JSON/CSV) z REST API i panelem po polsku"
requires-python = ">=3.12"
authors = [{ name = "Tomasz 'Amigo' Lewandowski", email = "dev@attv.uk" }]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`requirements.txt`:
```
Flask==3.1.3
Flask-SQLAlchemy==3.1.1
SQLAlchemy==2.0.54
Flask-Migrate==4.1.0
Flask-Login==0.6.3
Flask-WTF==1.3.0
lxml==6.1.3
rapidfuzz==3.14.6
PyYAML==6.0.3
PyMySQL==1.2.3
gunicorn==26.2.0
python-dotenv==1.2.4
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==9.1.1
pip-audit==2.10.1
```

`.env.example`:
```
# Skopiuj do .env i uzupełnij. .env NIE trafia do repo.
SECRET_KEY=zmien-mnie
DATABASE_URL=mysql+pymysql://xmlparser:xmlparser@db:3306/xmlparser?charset=utf8mb4
MARIADB_ROOT_PASSWORD=zmien-mnie-root
MARIADB_DATABASE=xmlparser
MARIADB_USER=xmlparser
MARIADB_PASSWORD=xmlparser
STORAGE_DIR=/data/storage
MAX_DOCUMENT_BYTES=10485760
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=zmien-mnie
DEMO_MODE=1
# Klucz API demo pokazywany na stronie „O demo” (tylko w DEMO_MODE)
DEMO_API_KEY=xp_demo_klucz_do_testow
APP_BIND=0.0.0.0
APP_PORT=5010
```

`.dockerignore`:
```
.git
private
storage
instance
.env
__pycache__
.pytest_cache
.venv
```

- [ ] **Step 2: Napisz test strażnika danych prywatnych**

`tests/test_no_private_data.py`:
```python
"""Strażnik: realne dane z prywatnych faktur nie mogą trafić do repo.

Zakazane tokeny są tu wyłącznie jako hashe SHA-256 (lowercase), więc
same wartości nigdy nie pojawiają się w repozytorium.
"""
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_TOKEN_HASHES = {
    "bf1de09ecdbd051341e4344e07884693445abdecfd8d9695317d14c3afe2270c",
    "9a6a353599794dc0e07351237d116847cca3fd9d6a9effee79805bdb21c57a95",
    "f2349a70106ea129def6e6b62e0505e2267783edd015da3d8e2e9ffd0b9107ee",
    "9bcbe73fc1df836ef09d7d90a8ef20598e6319a7fc21bdd37087a973c6392e1d",
    "5c890b739c35d9fb67180027dfefe4195d9f9c6b538890678f298aa7402eace5",
    "8a86d9be614a932d5feaa99da5907762fda94f4f507ec6d3c85864fc0753136a",
    "548fa96aba65633304907742583b612def240a1c415b693e98143463119cd0ff",
}
TOKEN_RE = re.compile(r"[a-z0-9]+")


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [ROOT / p for p in out.split("\0") if p]


def find_violations(text: str) -> set[str]:
    hits = set()
    for token in TOKEN_RE.findall(text.lower()):
        if hashlib.sha256(token.encode()).hexdigest() in FORBIDDEN_TOKEN_HASHES:
            hits.add(token[:2] + "…")
    return hits


def test_clean_text_has_no_violations():
    # Pozytywnego przypadku nie da się przetestować bez wpisania zakazanego tokenu do repo.
    # Ręczna weryfikacja (lokalnie, poza repo): python -c "from tests.test_no_private_data import
    # find_violations; print(find_violations(open('private/samples/<plik>').read()))" -> niepusty zbiór.
    assert find_violations("Hurtownia Alfa FA/2026/10/001 PL9990000011") == set()


def test_private_dir_is_ignored():
    res = subprocess.run(
        ["git", "check-ignore", "private/samples/x.xml"], cwd=ROOT, capture_output=True
    )
    assert res.returncode == 0, "katalog private/ musi być w .gitignore"


def test_no_private_data_in_tracked_files():
    problems = {}
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = find_violations(text)
        if hits:
            problems[str(path.relative_to(ROOT))] = sorted(hits)
    assert not problems, f"Prywatne dane w śledzonych plikach: {problems}"
```

`tools/pre-commit` (wykonywalny):
```sh
#!/bin/sh
# Instalacja: ln -sf ../../tools/pre-commit .git/hooks/pre-commit
exec python3 -m pytest tests/test_no_private_data.py -q -p no:cacheprovider
```

- [ ] **Step 3: Napisz testy aplikacji (failing)**

`tests/conftest.py`:
```python
import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "STORAGE_DIR": str(tmp_path / "storage"),
        "WTF_CSRF_ENABLED": False,
        "DEMO_MODE": True,
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "haslo123",
        "DEMO_API_KEY": "xp_test_demo_key",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
```

`tests/test_app.py`:
```python
import tomllib
from pathlib import Path

from app.version import __version__

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_from_pyproject():
    expected = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert __version__ == expected and __version__.count(".") == 2


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok", "version": __version__}
```

- [ ] **Step 4: Uruchom testy — mają nie przejść**

Najpierw środowisko:
```bash
cd /var/www/html/xml-parser
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest tests/test_app.py -q
```
Expected: FAIL (`ModuleNotFoundError: No module named 'app'`).

- [ ] **Step 5: Implementacja szkieletu aplikacji**

`app/version.py`:
```python
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _read_version() -> str:
    try:
        with _PYPROJECT.open("rb") as fh:
            return tomllib.load(fh)["project"]["version"]
    except (OSError, KeyError):
        return "0.0.0"


__version__ = _read_version()
```

`app/extensions.py`:
```python
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Zaloguj się, aby kontynuować."
csrf = CSRFProtect()
```

`app/config.py`:
```python
import os


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "tak"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///xmlparser-dev.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")
    MAX_DOCUMENT_BYTES = int(os.environ.get("MAX_DOCUMENT_BYTES", 10 * 1024 * 1024))
    MAX_CONTENT_LENGTH = MAX_DOCUMENT_BYTES + 64 * 1024
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    DEMO_MODE = _bool("DEMO_MODE", "1")
    DEMO_API_KEY = os.environ.get("DEMO_API_KEY", "")
    REPO_URL = "https://github.com/AmigoUK/xml-parser"
```

`app/__init__.py`:
```python
from dotenv import load_dotenv
from flask import Flask, jsonify

from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .version import __version__


def create_app(config_overrides: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_DOCUMENT_BYTES"] + 64 * 1024

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    @app.context_processor
    def inject_globals():
        return {
            "APP_VERSION": __version__,
            "REPO_URL": app.config["REPO_URL"],
            "DEMO_MODE": app.config["DEMO_MODE"],
        }

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=__version__)

    return app
```

`app/templates/_footer.html`:
```html
<footer class="app-footer">
  <a href="mailto:dev@attv.uk">dev@attv.uk</a>
  <span class="sep">·</span>
  <span>Project &amp; Development: Tomasz &lsquo;Amigo&rsquo; Lewandowski</span>
  <span class="sep">·</span>
  <a href="https://www.attv.uk" target="_blank" rel="noreferrer">www.attv.uk</a>
  <span class="sep">·</span>
  <a href="{{ REPO_URL }}" target="_blank" rel="noreferrer">GitHub</a>
  <span class="sep">·</span>
  <span>v{{ APP_VERSION }}</span>
</footer>
```

`app/templates/base.html` (navbar uzupełnimy w Task 14; teraz minimalny):
```html
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <title>{% block title %}Parser faktur{% endblock %} · XML Parser</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='vendor/bootstrap.min.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
</head>
<body class="{% if full_screen %}full-screen{% endif %}">
  {% if not full_screen %}{% block nav %}{% endblock %}{% endif %}
  <main class="{% if full_screen %}editor-main{% else %}container py-4{% endif %}">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'danger' if cat == 'error' else cat }} alert-dismissible">{{ msg }}</div>
      {% endfor %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
  {% if not full_screen %}{% include "_footer.html" %}{% endif %}
  <script src="{{ url_for('static', filename='vendor/bootstrap.bundle.min.js') }}"></script>
  <script src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>
  <script defer src="{{ url_for('static', filename='vendor/alpine.min.js') }}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

`app/static/app.css`:
```css
:root { --muted: #6c757d; }
body { display: flex; flex-direction: column; min-height: 100vh; background: #f6f7f9; }
main { flex: 1; }
.app-footer { border-top: 1px solid #dee2e6; background: #fff; padding: .5rem 1rem;
  text-align: center; font-size: 11px; color: var(--muted); }
.app-footer a { color: var(--muted); text-decoration: none; }
.app-footer a:hover { color: #343a40; }
.app-footer .sep { margin: 0 .5rem; color: #ced4da; }
.tree-row { font-family: ui-monospace, monospace; font-size: 12px; white-space: nowrap; }
.tree-row .val { color: #0d6efd; }
.issue-blocking { border-left: 4px solid #dc3545; }
.issue-warning { border-left: 4px solid #ffc107; }
body.full-screen main.editor-main { padding: 0; height: 100vh; overflow: hidden; }
.conf { font-size: 11px; color: var(--muted); }
```

Pobierz biblioteki frontendowe do `app/static/vendor/` (jednorazowo, pliki wchodzą do repo — runtime bez CDN):
```bash
V=app/static/vendor; mkdir -p $V
curl -fsSL -o $V/bootstrap.min.css https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css
curl -fsSL -o $V/bootstrap.bundle.min.js https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js
curl -fsSL -o $V/htmx.min.js https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js
curl -fsSL -o $V/alpine.min.js https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js
curl -fsSL -o $V/swagger-ui.css https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.18.2/swagger-ui.css
curl -fsSL -o $V/swagger-ui-bundle.js https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.18.2/swagger-ui-bundle.js
ls -la $V
```

- [ ] **Step 6: Docker**

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=app:create_app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x docker/entrypoint.sh
EXPOSE 5010
ENTRYPOINT ["docker/entrypoint.sh"]
```

`docker/entrypoint.sh`:
```sh
#!/bin/sh
set -e
mkdir -p "${STORAGE_DIR:-/data/storage}"
if [ -d migrations ]; then flask db upgrade; fi
if flask --help | grep -q " seed"; then flask seed; fi
exec gunicorn -w 2 -b 0.0.0.0:5010 --access-logfile - "app:create_app()"
```

`docker-compose.yml`:
```yaml
services:
  db:
    image: mariadb:11.4
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD}
      MARIADB_DATABASE: ${MARIADB_DATABASE:-xmlparser}
      MARIADB_USER: ${MARIADB_USER:-xmlparser}
      MARIADB_PASSWORD: ${MARIADB_PASSWORD}
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"]
    volumes: [dbdata:/var/lib/mysql]
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 5s
      retries: 20
  app:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
    ports:
      - "${APP_BIND:-0.0.0.0}:${APP_PORT:-5010}:5010"
    volumes: [storage:/data/storage]
volumes:
  dbdata:
  storage:
```

- [ ] **Step 7: CHANGELOG i README**

`CHANGELOG.md`:
```markdown
# Changelog

All notable changes to **xml-parser** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [0.0.1] — 2026-10-10

### Added
- Szkielet aplikacji Flask, konfiguracja z `.env`, Docker Compose (MariaDB 11.4), `/healthz`.
- Stopka z kredytami i wersją.
- Strażnik danych prywatnych (`tests/test_no_private_data.py`) + hook pre-commit.
- Specyfikacja projektowa i plan etapu 1.

[Unreleased]: https://github.com/AmigoUK/xml-parser/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/AmigoUK/xml-parser/releases/tag/v0.0.1
```

`README.md`:
````markdown
# XML Parser faktur

Uczący się parser faktur strukturalnych (XML, JSON, CSV): REST API dla innych systemów
oraz panel po polsku do „negocjowania” odczytu przy pierwszej fakturze dostawcy.
Specyfikacja: `docs/superpowers/specs/2026-10-10-xml-invoice-parser-design.md`.

## Uruchomienie (Docker)

```bash
cp .env.example .env   # uzupełnij hasła
docker compose up -d --build
# panel: http://<host>:5010
```

## Rozwój lokalny

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ln -sf ../../tools/pre-commit .git/hooks/pre-commit
pytest
```

## Dane prywatne

Realne faktury trzymaj **wyłącznie** w `private/` (ignorowane przez git).
Hook pre-commit i test `tests/test_no_private_data.py` blokują ich przypadkowe dodanie.
````

- [ ] **Step 8: Uruchom testy — mają przejść**

```bash
chmod +x tools/pre-commit docker/entrypoint.sh
ln -sf ../../tools/pre-commit .git/hooks/pre-commit
git add -A
pytest -q
```
Expected: PASS (5 testów). `git status --short` nie pokazuje `private/` ani `.venv/` (`.venv/` jest w `.gitignore`).

- [ ] **Step 9: Sprawdź build Dockera**

```bash
cp .env.example .env
docker compose build app && docker compose up -d
curl -fsS http://127.0.0.1:5010/healthz
docker compose down
```
Expected: `{"status":"ok","version":"0.0.1"}`.

- [ ] **Step 10: Commit, tag, push, GitHub Release v0.0.1**

```bash
git commit -m "chore(release): v0.0.1 — szkielet aplikacji, Docker, strażnik danych prywatnych

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
git tag -a v0.0.1 -m "v0.0.1 — szkielet aplikacji"
git push -u origin main && git push origin v0.0.1
gh release create v0.0.1 --title "v0.0.1" --notes "$(awk '/^## \[0.0.1\]/{f=1;next}/^## \[/{f=0}f' CHANGELOG.md)"
```
Jeśli repo na GitHubie nie istnieje: `gh repo create AmigoUK/xml-parser --private --source . --push` (najpierw zapytaj użytkownika o widoczność, domyślnie private).

---

### Task 2: Fikcyjne próbki demo

**Files:**
- Create: `demo/samples/alfa-1.xml`, `demo/samples/alfa-2.xml`, `demo/samples/beta-ksef.xml`, `demo/samples/gamma-ubl.xml`, `demo/samples/delta.csv`, `demo/samples/epsilon.json`, `demo/samples/README.md`
- Test: `tests/test_samples.py`

**Interfaces:**
- Produces: pliki próbek, z których korzystają testy Task 3–12 i strona demo (Task 17). Stałe (fikcyjne) wartości używane w testach:
  - Alfa: NIP `PL9990000011`, nazwa „Hurtownia Alfa Sp. z o.o.”, numery `FA/2026/10/001` i `FA/2026/10/002`, brak tagu waluty (celowo), jednostka `pcs`, EAN z prefiksem AI `01`, GS1-128 z AI 01/15/10.
  - Beta (KSeF-podobny): NIP `9990000022`, waluta PLN, jednostka `worek` (25 kg).
  - Gamma (UBL 2.1): VAT `DE999999999`, EUR, jednostki `C62`/`H87`.
  - Delta (CSV `;`, przecinek dziesiętny): NIP `9990000033`, PLN, jednostka `kart.` (12 szt).
  - Epsilon (JSON): VAT `GB999000044`, GBP, jednostka `EA`.

- [ ] **Step 1: Napisz test**

`tests/test_samples.py`:
```python
import csv
import io
import json
from pathlib import Path

from lxml import etree

SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"
EXPECTED = {"alfa-1.xml", "alfa-2.xml", "beta-ksef.xml", "gamma-ubl.xml", "delta.csv", "epsilon.json"}


def test_all_samples_present():
    assert EXPECTED <= {p.name for p in SAMPLES.iterdir()}


def test_xml_samples_well_formed():
    for name in ("alfa-1.xml", "alfa-2.xml", "beta-ksef.xml", "gamma-ubl.xml"):
        etree.fromstring((SAMPLES / name).read_bytes())


def test_json_and_csv_parse():
    json.loads((SAMPLES / "epsilon.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(io.StringIO((SAMPLES / "delta.csv").read_text(encoding="utf-8")), delimiter=";"))
    assert len(rows) == 2
```

- [ ] **Step 2: Uruchom — FAIL** (`pytest tests/test_samples.py` → brak katalogu).

- [ ] **Step 3: Utwórz próbki**

`demo/samples/alfa-1.xml` (celowo bez waluty i bez tagów partii/daty ważności — dane są tylko w kodzie GS1-128):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <Type>Invoice</Type>
    <Version>1</Version>
    <Language>PL</Language>
    <Faktura>
        <Naglowek>
            <DostawcaNIP>PL9990000011</DostawcaNIP>
            <DostawcaNazwa>Hurtownia Alfa Sp. z o.o.</DostawcaNazwa>
            <DostawcaAdresKodPocztowy>00-950</DostawcaAdresKodPocztowy>
            <DostawcaAdresMiejscowosc>Przykładowo</DostawcaAdresMiejscowosc>
            <DostawcaAdresUlica>ul. Testowa 1</DostawcaAdresUlica>
            <NabywcaNIP>PL9990000099</NabywcaNIP>
            <NabywcaNazwa>Piekarnia Demo Sp. z o.o.</NabywcaNazwa>
            <NabywcaAdresKodPocztowy>00-951</NabywcaAdresKodPocztowy>
            <NabywcaAdresMiejscowosc>Przykładowo</NabywcaAdresMiejscowosc>
            <NabywcaAdresUlica>ul. Demonstracyjna 2</NabywcaAdresUlica>
            <FakturaNumer>FA/2026/10/001</FakturaNumer>
            <FakturaDataWystawienia>2026-10-09</FakturaDataWystawienia>
            <FakturaDataPlatnosci>2026-10-30</FakturaDataPlatnosci>
            <FakturaTypPlatnosci>Przelew</FakturaTypPlatnosci>
            <FakturaWartoscNetto>155.50</FakturaWartoscNetto>
            <FakturaWartoscVat>0.00</FakturaWartoscVat>
            <FakturaWartoscBrutto>155.50</FakturaWartoscBrutto>
            <FakturaNumeryWZ>WZ-ALFA-0001</FakturaNumeryWZ>
        </Naglowek>
        <Pozycje>
            <Pozycja>
                <TowarKod>A-100</TowarKod>
                <TowarKodEan>0105909999000013</TowarKodEan>
                <TowarKodEan128>01059099990000131527070910L2607</TowarKodEan128>
                <TowarNazwa>Posypka czekoladowa 1 kg</TowarNazwa>
                <TowarJm>pcs</TowarJm>
                <Ilosc>4</Ilosc>
                <CenaNetto>12.50</CenaNetto>
                <WartoscNetto>50.00</WartoscNetto>
                <StawkaVat>0%</StawkaVat>
                <WartoscVat>0.00</WartoscVat>
                <WartoscBrutto>50.00</WartoscBrutto>
            </Pozycja>
            <Pozycja>
                <TowarKod>A-200</TowarKod>
                <TowarKodEan>0105909999000020</TowarKodEan>
                <TowarKodEan128>01059099990000201527080110L2608</TowarKodEan128>
                <TowarNazwa>Mak niebieski 500 g</TowarNazwa>
                <TowarJm>pcs</TowarJm>
                <Ilosc>10</Ilosc>
                <CenaNetto>4.20</CenaNetto>
                <WartoscNetto>42.00</WartoscNetto>
                <StawkaVat>0%</StawkaVat>
                <WartoscVat>0.00</WartoscVat>
                <WartoscBrutto>42.00</WartoscBrutto>
            </Pozycja>
            <Pozycja>
                <TowarKod>A-300</TowarKod>
                <TowarKodEan>0105909999000037</TowarKodEan>
                <TowarKodEan128>01059099990000371527123110L2612</TowarKodEan128>
                <TowarNazwa>Masa marcepanowa 5 kg</TowarNazwa>
                <TowarJm>pcs</TowarJm>
                <Ilosc>2</Ilosc>
                <CenaNetto>31.75</CenaNetto>
                <WartoscNetto>63.50</WartoscNetto>
                <StawkaVat>0%</StawkaVat>
                <WartoscVat>0.00</WartoscVat>
                <WartoscBrutto>63.50</WartoscBrutto>
            </Pozycja>
        </Pozycje>
    </Faktura>
</Document>
```

`demo/samples/alfa-2.xml` — ta sama struktura i nagłówek dostawcy/nabywcy co `alfa-1.xml`, z różnicami:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <Type>Invoice</Type>
    <Version>1</Version>
    <Language>PL</Language>
    <Faktura>
        <Naglowek>
            <DostawcaNIP>PL9990000011</DostawcaNIP>
            <DostawcaNazwa>Hurtownia Alfa Sp. z o.o.</DostawcaNazwa>
            <DostawcaAdresKodPocztowy>00-950</DostawcaAdresKodPocztowy>
            <DostawcaAdresMiejscowosc>Przykładowo</DostawcaAdresMiejscowosc>
            <DostawcaAdresUlica>ul. Testowa 1</DostawcaAdresUlica>
            <NabywcaNIP>PL9990000099</NabywcaNIP>
            <NabywcaNazwa>Piekarnia Demo Sp. z o.o.</NabywcaNazwa>
            <NabywcaAdresKodPocztowy>00-951</NabywcaAdresKodPocztowy>
            <NabywcaAdresMiejscowosc>Przykładowo</NabywcaAdresMiejscowosc>
            <NabywcaAdresUlica>ul. Demonstracyjna 2</NabywcaAdresUlica>
            <FakturaNumer>FA/2026/10/002</FakturaNumer>
            <FakturaDataWystawienia>2026-10-10</FakturaDataWystawienia>
            <FakturaDataPlatnosci>2026-10-31</FakturaDataPlatnosci>
            <FakturaTypPlatnosci>Przelew</FakturaTypPlatnosci>
            <FakturaWartoscNetto>96.00</FakturaWartoscNetto>
            <FakturaWartoscVat>0.00</FakturaWartoscVat>
            <FakturaWartoscBrutto>96.00</FakturaWartoscBrutto>
            <FakturaNumeryWZ>WZ-ALFA-0002</FakturaNumeryWZ>
        </Naglowek>
        <Pozycje>
            <Pozycja>
                <TowarKod>A-100</TowarKod>
                <TowarKodEan>0105909999000013</TowarKodEan>
                <TowarKodEan128>01059099990000131527071510L2607</TowarKodEan128>
                <TowarNazwa>Posypka czekoladowa 1 kg</TowarNazwa>
                <TowarJm>pcs</TowarJm>
                <Ilosc>6</Ilosc>
                <CenaNetto>12.50</CenaNetto>
                <WartoscNetto>75.00</WartoscNetto>
                <StawkaVat>0%</StawkaVat>
                <WartoscVat>0.00</WartoscVat>
                <WartoscBrutto>75.00</WartoscBrutto>
            </Pozycja>
            <Pozycja>
                <TowarKod>A-200</TowarKod>
                <TowarKodEan>0105909999000020</TowarKodEan>
                <TowarKodEan128>01059099990000201527080110L2608</TowarKodEan128>
                <TowarNazwa>Mak niebieski 500 g</TowarNazwa>
                <TowarJm>pcs</TowarJm>
                <Ilosc>5</Ilosc>
                <CenaNetto>4.20</CenaNetto>
                <WartoscNetto>21.00</WartoscNetto>
                <StawkaVat>0%</StawkaVat>
                <WartoscVat>0.00</WartoscVat>
                <WartoscBrutto>21.00</WartoscBrutto>
            </Pozycja>
        </Pozycje>
    </Faktura>
</Document>
```

`demo/samples/beta-ksef.xml` (struktura wzorowana na KSeF FA(3), wartości fikcyjne):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">
  <Naglowek>
    <KodFormularza kodSystemowy="FA (3)" wersjaSchemy="1-0E">FA</KodFormularza>
    <WariantFormularza>3</WariantFormularza>
    <DataWytworzeniaFa>2026-10-08T10:00:00Z</DataWytworzeniaFa>
  </Naglowek>
  <Podmiot1>
    <DaneIdentyfikacyjne><NIP>9990000022</NIP><Nazwa>Młyn Beta Sp. z o.o.</Nazwa></DaneIdentyfikacyjne>
    <Adres><KodKraju>PL</KodKraju><AdresL1>ul. Młyńska 5</AdresL1><AdresL2>00-952 Przykładowo</AdresL2></Adres>
  </Podmiot1>
  <Podmiot2>
    <DaneIdentyfikacyjne><NIP>9990000099</NIP><Nazwa>Piekarnia Demo Sp. z o.o.</Nazwa></DaneIdentyfikacyjne>
    <Adres><KodKraju>PL</KodKraju><AdresL1>ul. Demonstracyjna 2</AdresL1><AdresL2>00-951 Przykładowo</AdresL2></Adres>
  </Podmiot2>
  <Fa>
    <KodWaluty>PLN</KodWaluty>
    <P_1>2026-10-08</P_1>
    <P_2>FV/B/1024/2026</P_2>
    <P_13_1>1000.00</P_13_1>
    <P_14_1>50.00</P_14_1>
    <P_15>1050.00</P_15>
    <RodzajFaktury>VAT</RodzajFaktury>
    <FaWiersz>
      <NrWierszaFa>1</NrWierszaFa>
      <Indeks>M-450</Indeks>
      <GTIN>5909999000044</GTIN>
      <P_7>Mąka pszenna typ 450 25 kg</P_7>
      <P_8A>worek</P_8A>
      <P_8B>20</P_8B>
      <P_9A>40.00</P_9A>
      <P_11>800.00</P_11>
      <P_12>5</P_12>
    </FaWiersz>
    <FaWiersz>
      <NrWierszaFa>2</NrWierszaFa>
      <Indeks>M-750</Indeks>
      <GTIN>5909999000051</GTIN>
      <P_7>Mąka żytnia typ 750 25 kg</P_7>
      <P_8A>worek</P_8A>
      <P_8B>5</P_8B>
      <P_9A>40.00</P_9A>
      <P_11>200.00</P_11>
      <P_12>5</P_12>
    </FaWiersz>
    <Platnosc>
      <TerminPlatnosci><Termin>2026-10-22</Termin></TerminPlatnosci>
      <FormaPlatnosci>6</FormaPlatnosci>
    </Platnosc>
  </Fa>
</Faktura>
```

`demo/samples/gamma-ubl.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID>
  <cbc:ID>GAM-2026-0315</cbc:ID>
  <cbc:IssueDate>2026-10-06</cbc:IssueDate>
  <cbc:DueDate>2026-11-05</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Gamma Aromen GmbH</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>Beispielstraße 7</cbc:StreetName><cbc:CityName>Musterstadt</cbc:CityName><cbc:PostalZone>99999</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE999999999</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Piekarnia Demo Sp. z o.o.</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>ul. Demonstracyjna 2</cbc:StreetName><cbc:CityName>Przykładowo</cbc:CityName><cbc:PostalZone>00-951</cbc:PostalZone><cac:Country><cbc:IdentificationCode>PL</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>PL9990000099</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">5.46</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">78.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">78.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">83.46</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">83.46</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">12</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">30.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>Wanilia burbon laski 10 szt</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>G-01</cbc:ID></cac:SellersItemIdentification>
      <cac:StandardItemIdentification><cbc:ID schemeID="0160">4009999000011</cbc:ID></cac:StandardItemIdentification>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">2.50</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID>
    <cbc:InvoicedQuantity unitCode="H87">24</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">48.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>Aromat rumowy 100 ml</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>G-02</cbc:ID></cac:SellersItemIdentification>
      <cac:StandardItemIdentification><cbc:ID schemeID="0160">4009999000028</cbc:ID></cac:StandardItemIdentification>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">2.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>
```

`demo/samples/delta.csv` (UTF-8, separator `;`, przecinek dziesiętny, data `DD.MM.RRRR`):
```
NrFaktury;DataWystawienia;Waluta;SprzedawcaNIP;SprzedawcaNazwa;Kod;Nazwa;EAN;Ilosc;JM;CenaNetto;WartoscNetto;StawkaVAT;WartoscVAT;WartoscBrutto;RazemNetto;RazemVAT;RazemBrutto
D/77/2026;09.10.2026;PLN;9990000033;Opakowania Delta S.C.;D-10;Pudełko na tort 30x30;5909999000068;2;kart.;96,00;192,00;23;44,16;236,16;312,00;71,76;383,76
D/77/2026;09.10.2026;PLN;9990000033;Opakowania Delta S.C.;D-20;Podkład pod tort 28 cm;5909999000075;1;kart.;120,00;120,00;23;27,60;147,60;312,00;71,76;383,76
```

`demo/samples/epsilon.json`:
```json
{
  "invoice": {
    "number": "E-2026-0042",
    "issue_date": "2026-10-07",
    "due_date": "2026-11-06",
    "currency": "GBP",
    "seller": {
      "name": "Epsilon Dairy Ltd",
      "vat_number": "GB999000044",
      "address": {"street": "1 Example Street", "city": "Testford", "postcode": "TF1 1AA"}
    },
    "buyer": {"name": "Piekarnia Demo Ltd", "vat_number": "GB999000055"},
    "totals": {"net": 45.60, "vat": 0, "gross": 45.60},
    "items": [
      {"sku": "E-1", "ean": "5909999000082", "description": "Masło 82% 1 kg", "quantity": 6, "uom": "EA",
       "unit_price": 5.10, "net_amount": 30.60, "vat_rate": 0},
      {"sku": "E-2", "ean": "5909999000099", "description": "Śmietanka 30% 1 l", "quantity": 5, "uom": "EA",
       "unit_price": 3.00, "net_amount": 15.00, "vat_rate": 0}
    ]
  }
}
```

`demo/samples/README.md`:
```markdown
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
```

- [ ] **Step 4: Uruchom — PASS:** `pytest tests/test_samples.py tests/test_no_private_data.py -q` (po `git add demo tests`).

- [ ] **Step 5: Commit**
```bash
git add demo tests/test_samples.py
git commit -m "feat(demo): fikcyjne próbki faktur w 5 formatach

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 3: SourceTree i czytniki XML/JSON/CSV

**Files:**
- Create: `app/engine/__init__.py` (pusty), `app/engine/tree.py`
- Create: `app/ingest/__init__.py`, `app/ingest/xml_reader.py`, `app/ingest/json_reader.py`, `app/ingest/csv_reader.py`
- Test: `tests/engine/__init__.py`, `tests/engine/test_tree.py`, `tests/test_readers.py`

**Interfaces:**
- Produces:
  - `Node(name: str, text: str | None = None, attrs: dict[str,str] = {}, children: list[Node] = [])`, `Node.add(child) -> Node`, `Node.path -> str` (ścieżka absolutna z nazwą korzenia, np. `Document/Faktura/Naglowek`).
  - `SourceTree(root: Node, fmt: str)`; metody: `leaf_items() -> list[tuple[str,str]]` (ścieżka, wartość; atrybuty jako `…/@attr`), `leaf_paths() -> list[str]` (unikalne, w kolejności dokumentu), `path_set() -> set[str]`, `nodes_at(abs_path) -> list[Node]`, `values(path, context: Node | None = None) -> list[str]` (bez `context` ścieżka absolutna, z `context` względna), `first(path, context=None) -> str | None`, `detect_line_group() -> str | None`, `group_paths() -> list[str]` (ścieżki węzłów z dziećmi, w kolejności), `fingerprint() -> str` (16 znaków hex), `display_rows() -> list[dict]` (`{"path","name","value","depth"}` do UI).
  - `relative_path(path: str, base: str) -> str | None`, `jaccard(a: set, b: set) -> float`.
  - `read_document(data: bytes, filename: str | None = None) -> SourceTree`, `ReaderError(ValueError)` (polski komunikat).

- [ ] **Step 1: Testy drzewa**

`tests/engine/test_tree.py`:
```python
from app.engine.tree import Node, SourceTree, jaccard, relative_path


def build():
    root = Node("Doc")
    head = root.add(Node("Head"))
    head.add(Node("Nr", "F/1"))
    lines = root.add(Node("Lines"))
    for i in range(3):
        ln = lines.add(Node("Line"))
        ln.add(Node("Name", f"Towar {i}"))
        ln.add(Node("Qty", str(i + 1), attrs={"unit": "pcs"}))
    return SourceTree(root, "xml")


def test_paths_and_values():
    t = build()
    assert t.first("Doc/Head/Nr") == "F/1"
    assert t.values("Doc/Lines/Line/Name") == ["Towar 0", "Towar 1", "Towar 2"]
    assert "Doc/Lines/Line/Qty/@unit" in t.leaf_paths()
    line = t.nodes_at("Doc/Lines/Line")[1]
    assert t.first("Qty", context=line) == "2"
    assert t.first("Qty/@unit", context=line) == "pcs"
    assert t.first("Doc/Missing") is None


def test_detect_line_group():
    assert build().detect_line_group() == "Doc/Lines/Line"


def test_detect_single_line_by_hint():
    root = Node("Faktura")
    root.add(Node("Numer", "1"))
    w = root.add(Node("Pozycje")).add(Node("Pozycja"))
    w.add(Node("Nazwa", "X"))
    assert SourceTree(root, "xml").detect_line_group() == "Faktura/Pozycje/Pozycja"


def test_nested_repeats_prefer_outermost():
    root = Node("Inv")
    for _ in range(2):
        ln = root.add(Node("InvoiceLine"))
        for _ in range(3):
            ln.add(Node("Note")).add(Node("Text", "x"))
    assert SourceTree(root, "xml").detect_line_group() == "Inv/InvoiceLine"


def test_fingerprint_stable_across_line_count():
    a = build()
    root = Node("Doc")
    root.add(Node("Head")).add(Node("Nr", "F/2"))
    ln = root.add(Node("Lines")).add(Node("Line"))
    ln.add(Node("Name", "Inny"))
    ln.add(Node("Qty", "9", attrs={"unit": "kg"}))
    assert SourceTree(root, "xml").fingerprint() == a.fingerprint()
    assert len(a.fingerprint()) == 16


def test_helpers():
    assert relative_path("A/B/C/D", "A/B") == "C/D"
    assert relative_path("A/X", "A/B") is None
    assert jaccard({"a", "b"}, {"a", "b", "c", "d"}) == 0.5
    assert jaccard(set(), set()) == 0.0
```

- [ ] **Step 2: Testy czytników**

`tests/test_readers.py`:
```python
from pathlib import Path

import pytest

from app.ingest import ReaderError, read_document

SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"


def test_xml_alfa():
    t = read_document((SAMPLES / "alfa-1.xml").read_bytes(), "alfa-1.xml")
    assert t.fmt == "xml"
    assert t.first("Document/Faktura/Naglowek/FakturaNumer") == "FA/2026/10/001"
    assert t.detect_line_group() == "Document/Faktura/Pozycje/Pozycja"


def test_xml_namespaces_stripped_and_attrs():
    t = read_document((SAMPLES / "gamma-ubl.xml").read_bytes())
    assert t.first("Invoice/ID") == "GAM-2026-0315"
    assert t.detect_line_group() == "Invoice/InvoiceLine"
    line = t.nodes_at("Invoice/InvoiceLine")[0]
    assert t.first("InvoicedQuantity/@unitCode", context=line) == "C62"


def test_xml_rejects_doctype():
    evil = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>'
    with pytest.raises(ReaderError, match="DOCTYPE"):
        read_document(evil)


def test_xml_malformed():
    with pytest.raises(ReaderError):
        read_document(b"<a><b></a>")


def test_json_epsilon_keeps_number_strings():
    t = read_document((SAMPLES / "epsilon.json").read_bytes(), "epsilon.json")
    assert t.fmt == "json"
    assert t.first("root/invoice/totals/net") == "45.60"
    assert t.detect_line_group() == "root/invoice/items"
    assert t.values("root/invoice/items/quantity") == ["6", "5"]


def test_csv_delta():
    t = read_document((SAMPLES / "delta.csv").read_bytes(), "delta.csv")
    assert t.fmt == "csv"
    assert t.detect_line_group() == "csv/row"
    assert t.values("csv/row/JM") == ["kart.", "kart."]
    assert t.first("csv/row/NrFaktury") == "D/77/2026"


def test_csv_cp1250_fallback():
    data = "Nr;Nazwa\n1;Mąka\n".encode("cp1250")
    t = read_document(data, "x.csv")
    assert t.first("csv/row/Nazwa") == "Mąka"


@pytest.mark.parametrize("data", [b"", b"   ", b"Nr;Nazwa\n"])
def test_empty_inputs_rejected(data):
    with pytest.raises(ReaderError):
        read_document(data, "x.csv")
```

- [ ] **Step 3: Uruchom — FAIL** (`pytest tests/engine/test_tree.py tests/test_readers.py` → ImportError).

- [ ] **Step 4: Implementacja `app/engine/tree.py`**

```python
"""Drzewo źródłowe niezależne od formatu (XML/JSON/CSV) i operacje na ścieżkach."""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator

LINE_HINTS = ("pozycja", "fawiersz", "invoiceline", "row", "item", "items", "line", "lines", "wiersz")


@dataclass(eq=False)
class Node:
    name: str
    text: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)

    def add(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    @property
    def path(self) -> str:
        parts, node = [], self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return "/".join(reversed(parts))


def relative_path(path: str, base: str) -> str | None:
    prefix = base + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


class SourceTree:
    def __init__(self, root: Node, fmt: str):
        self.root = root
        self.fmt = fmt

    def iter_nodes(self) -> Iterator[Node]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def leaf_items(self) -> list[tuple[str, str]]:
        out = []
        for node in self.iter_nodes():
            p = node.path
            if node.text not in (None, ""):
                out.append((p, node.text))
            for k, v in node.attrs.items():
                if v not in (None, ""):
                    out.append((f"{p}/@{k}", v))
        return out

    def leaf_paths(self) -> list[str]:
        seen: dict[str, None] = {}
        for p, _ in self.leaf_items():
            seen.setdefault(p, None)
        return list(seen)

    def path_set(self) -> set[str]:
        return set(self.leaf_paths())

    def group_paths(self) -> list[str]:
        seen: dict[str, None] = {}
        for node in self.iter_nodes():
            if node.children:
                seen.setdefault(node.path, None)
        return list(seen)

    def _descend(self, nodes: list[Node], segments: list[str]) -> list[Node]:
        for seg in segments:
            nodes = [c for n in nodes for c in n.children if c.name == seg]
            if not nodes:
                break
        return nodes

    def nodes_at(self, abs_path: str) -> list[Node]:
        segs = abs_path.split("/")
        if not segs or segs[0] != self.root.name:
            return []
        return self._descend([self.root], segs[1:])

    def values(self, path: str, context: Node | None = None) -> list[str]:
        segs = path.split("/")
        attr = segs.pop()[1:] if segs and segs[-1].startswith("@") else None
        if context is None:
            if not segs or segs[0] != self.root.name:
                return []
            nodes = self._descend([self.root], segs[1:])
        else:
            nodes = self._descend([context], segs)
        if attr is not None:
            return [n.attrs[attr] for n in nodes if n.attrs.get(attr) not in (None, "")]
        return [n.text for n in nodes if n.text not in (None, "")]

    def first(self, path: str, context: Node | None = None) -> str | None:
        vals = self.values(path, context)
        return vals[0] if vals else None

    def detect_line_group(self) -> str | None:
        counts = Counter(n.path for n in self.iter_nodes() if n.children and n is not self.root)
        candidates = [p for p, c in counts.items() if c >= 2]
        outer = [p for p in candidates if not any(p.startswith(o + "/") for o in candidates)]
        if outer:
            return sorted(outer, key=lambda p: (-counts[p], p.count("/")))[0]
        hinted = [p for p in counts if p.rsplit("/", 1)[-1].lower() in LINE_HINTS]
        if hinted:
            return sorted(hinted, key=lambda p: p.count("/"))[0]
        return None

    def fingerprint(self) -> str:
        blob = "\n".join(sorted(self.path_set())).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def display_rows(self) -> list[dict]:
        rows = []

        def walk(node: Node, depth: int) -> None:
            rows.append({"path": node.path, "name": node.name, "value": node.text, "depth": depth})
            for k, v in node.attrs.items():
                rows.append({"path": f"{node.path}/@{k}", "name": f"@{k}", "value": v, "depth": depth + 1})
            for c in node.children:
                walk(c, depth + 1)

        walk(self.root, 0)
        return rows
```

Uwaga: w `test_detect_single_line_by_hint` węzeł `Pozycje` ma 1 dziecko z dziećmi, a hint `pozycja` pasuje tylko do `Faktura/Pozycje/Pozycja`, bo `pozycje` nie jest na liście. Dlatego test przejdzie.

- [ ] **Step 5: Implementacja czytników**

`app/ingest/__init__.py`:
```python
from app.engine.tree import SourceTree


class ReaderError(ValueError):
    """Plik nie daje się odczytać — komunikat po polsku dla operatora."""


def detect_format(data: bytes) -> str:
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head == b"<":
        return "xml"
    if head in (b"{", b"["):
        return "json"
    return "csv"


def read_document(data: bytes, filename: str | None = None) -> SourceTree:
    if not data or not data.strip():
        raise ReaderError("Plik jest pusty.")
    fmt = detect_format(data)
    if fmt == "xml":
        from .xml_reader import read_xml
        return read_xml(data)
    if fmt == "json":
        from .json_reader import read_json
        return read_json(data)
    from .csv_reader import read_csv
    return read_csv(data)
```

`app/ingest/xml_reader.py`:
```python
from lxml import etree

from app.engine.tree import Node, SourceTree

from . import ReaderError

_PARSER_KW = dict(
    resolve_entities=False, no_network=True, huge_tree=False,
    remove_comments=True, remove_pis=True, load_dtd=False,
)


def _local(tag: str) -> str:
    return etree.QName(tag).localname


def _convert(el) -> Node:
    text = (el.text or "").strip() or None
    attrs = {_local(k): v.strip() for k, v in el.attrib.items()}
    node = Node(_local(el.tag), text, attrs)
    for child in el:
        if isinstance(child.tag, str):
            node.add(_convert(child))
    return node


def read_xml(data: bytes) -> SourceTree:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise ReaderError("Pliki XML z deklaracją DOCTYPE/ENTITY są odrzucane ze względów bezpieczeństwa.")
    try:
        root = etree.fromstring(data, etree.XMLParser(**_PARSER_KW))
    except etree.XMLSyntaxError as exc:
        raise ReaderError(f"Niepoprawny XML: {exc.msg} (linia {exc.lineno}).") from exc
    return SourceTree(_convert(root), "xml")
```

`app/ingest/json_reader.py`:
```python
import json

from app.engine.tree import Node, SourceTree

from . import ReaderError


def _scalar(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _build(name: str, value, parent: Node) -> None:
    if isinstance(value, dict):
        node = parent.add(Node(name))
        for k, v in value.items():
            if isinstance(v, list):
                for item in v:
                    _build(k, item, node)
            else:
                _build(k, v, node)
    elif isinstance(value, list):
        for item in value:
            _build(name, item, parent)
    else:
        parent.add(Node(name, _scalar(value)))


def read_json(data: bytes) -> SourceTree:
    try:
        obj = json.loads(data.decode("utf-8-sig"), parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReaderError(f"Niepoprawny JSON: {exc}.") from exc
    root = Node("root")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                for item in v:
                    _build(k, item, root)
            else:
                _build(k, v, root)
    elif isinstance(obj, list):
        for item in obj:
            _build("item", item, root)
    else:
        raise ReaderError("JSON nie zawiera obiektu ani listy.")
    if not root.children:
        raise ReaderError("JSON jest pusty.")
    return SourceTree(root, "json")
```

`app/ingest/csv_reader.py`:
```python
import csv
import io

from app.engine.tree import Node, SourceTree

from . import ReaderError


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


def read_csv(data: bytes) -> SourceTree:
    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ReaderError("Plik CSV jest pusty.") from None
    names = [(h.strip().replace("/", "_") or f"kol{i + 1}") for i, h in enumerate(header)]
    root = Node("csv")
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        rnode = root.add(Node("row"))
        for name, cell in zip(names, row):
            rnode.add(Node(name, cell.strip() or None))
    if not root.children:
        raise ReaderError("Plik CSV nie zawiera żadnych wierszy danych.")
    return SourceTree(root, "csv")
```

- [ ] **Step 6: Uruchom — PASS:** `pytest tests/engine/test_tree.py tests/test_readers.py -q`. Jeśli `test_csv_cp1250_fallback` daje inny separator po sniffingu, sprawdź, czy `Sniffer` dostał `delimiters=";,\t|"`.

- [ ] **Step 7: Commit**
```bash
git add app/engine app/ingest tests/engine tests/test_readers.py
git commit -m "feat(engine): SourceTree i bezpieczne czytniki XML/JSON/CSV

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---

### Task 4: GS1-128 i GTIN

**Files:**
- Create: `app/engine/gs1.py`
- Test: `tests/engine/test_gs1.py`

**Interfaces:**
- Produces: `GS1Error(ValueError)`, `gtin_check_digit(body: str) -> str`, `is_valid_gtin(code: str) -> bool` (8/12/13/14 cyfr), `parse_gs1(code: str) -> dict[str, str]` (AI → surowa wartość; obsługuje zapis z nawiasami `(01)…(10)…` oraz separator FNC1 `\x1d`), `gs1_date(yymmdd: str) -> str` (ISO; `DD=00` → ostatni dzień miesiąca), `DATE_AIS: set[str]`.

- [ ] **Step 1: Testy**

`tests/engine/test_gs1.py`:
```python
import pytest

from app.engine.gs1 import GS1Error, gs1_date, gtin_check_digit, is_valid_gtin, parse_gs1


def test_check_digit():
    assert gtin_check_digit("590999900001") == "3"
    assert is_valid_gtin("5909999000013")
    assert is_valid_gtin("05909999000013")
    assert not is_valid_gtin("5909999000014")
    assert not is_valid_gtin("59099990000")
    assert not is_valid_gtin("abc")


def test_parse_plain_sequence():
    assert parse_gs1("01059099990000131527070910L2607") == {
        "01": "05909999000013", "15": "270709", "10": "L2607",
    }


def test_parse_with_fnc1_separator():
    assert parse_gs1("0105909999000013" + "10L26" + "\x1d" + "15270709") == {
        "01": "05909999000013", "10": "L26", "15": "270709",
    }


def test_parse_parenthesised():
    assert parse_gs1("(01)05909999000013(17)271231(10)ABC") == {
        "01": "05909999000013", "17": "271231", "10": "ABC",
    }


def test_invalid_gtin_in_gs1():
    with pytest.raises(GS1Error):
        parse_gs1("0105909999000014")


def test_unknown_ai():
    with pytest.raises(GS1Error):
        parse_gs1("99ABC")


def test_dates():
    assert gs1_date("270709") == "2027-07-09"
    assert gs1_date("270200") == "2027-02-28"
    assert gs1_date("991231") == "1999-12-31"
```

- [ ] **Step 2: Uruchom — FAIL.**

- [ ] **Step 3: Implementacja `app/engine/gs1.py`**

```python
"""Minimalny parser GS1-128 (AI najczęstsze w logistyce spożywczej)."""
import calendar
import re

FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "12": 6, "13": 6, "15": 6, "16": 6, "17": 6, "20": 2}
VARIABLE = {"10": 20, "21": 20, "22": 20, "30": 8, "37": 8, "240": 30, "241": 30}
DATE_AIS = {"11", "12", "13", "15", "16", "17"}
GS = "\x1d"
_PAREN = re.compile(r"\((\d{2,4})\)([^(]*)")


class GS1Error(ValueError):
    pass


def gtin_check_digit(body: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def is_valid_gtin(code: str) -> bool:
    code = (code or "").strip()
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    return gtin_check_digit(code[:-1]) == code[-1]


def _validate(out: dict[str, str]) -> dict[str, str]:
    if "01" in out and not is_valid_gtin(out["01"]):
        raise GS1Error(f"Błędna cyfra kontrolna GTIN w kodzie GS1: {out['01']}")
    return out


def parse_gs1(code: str) -> dict[str, str]:
    s = (code or "").strip()
    if not s:
        raise GS1Error("Pusty kod GS1.")
    if "(" in s:
        out = {ai: val for ai, val in _PAREN.findall(s)}
        if not out:
            raise GS1Error(f"Nie rozpoznano kodu GS1: {code}")
        return _validate(out)
    out: dict[str, str] = {}
    i = 0
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai2, ai3 = s[i:i + 2], s[i:i + 3]
        if ai2 in FIXED:
            n = FIXED[ai2]
            val = s[i + 2:i + 2 + n]
            if len(val) < n:
                raise GS1Error(f"Za krótka wartość dla AI {ai2}.")
            out[ai2] = val
            i += 2 + n
            continue
        ai, max_len = (ai2, VARIABLE[ai2]) if ai2 in VARIABLE else (ai3, VARIABLE.get(ai3))
        if max_len is None:
            raise GS1Error(f"Nieznany identyfikator AI '{ai2}' na pozycji {i} w kodzie GS1.")
        start = i + len(ai)
        end = s.find(GS, start)
        end = len(s) if end == -1 else end
        val = s[start:min(end, start + max_len)]
        out[ai] = val
        i = start + len(val)
    return _validate(out)


def gs1_date(yymmdd: str) -> str:
    if not re.fullmatch(r"\d{6}", yymmdd or ""):
        raise GS1Error(f"Niepoprawna data GS1: {yymmdd}")
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    year = 2000 + yy if yy <= 49 else 1900 + yy
    if not 1 <= mm <= 12:
        raise GS1Error(f"Niepoprawny miesiąc w dacie GS1: {yymmdd}")
    if dd == 0:
        dd = calendar.monthrange(year, mm)[1]
    return f"{year:04d}-{mm:02d}-{dd:02d}"
```

- [ ] **Step 4: PASS:** `pytest tests/engine/test_gs1.py -q`

- [ ] **Step 5: Commit**
```bash
git add app/engine/gs1.py tests/engine/test_gs1.py
git commit -m "feat(engine): parser GS1-128 i walidacja GTIN

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---

### Task 5: Wartości (liczby, daty, GTIN) i transformacje

**Files:**
- Create: `app/engine/values.py`, `app/engine/transforms.py`
- Test: `tests/engine/test_values.py`, `tests/engine/test_transforms.py`

**Interfaces:**
- Consumes: `parse_gs1`, `gs1_date`, `DATE_AIS`, `is_valid_gtin` (Task 4); `SourceTree`, `Node` (Task 3).
- Produces:
  - `values.py`: `to_decimal(raw) -> Decimal` (ValueError z polskim komunikatem), `fmt_money(d: Decimal) -> str` (2 miejsca), `fmt_price(d) -> str` (2–4 miejsca), `fmt_qty(d) -> str` (bez zbędnych zer), `parse_date(raw: str) -> str` (ISO; ValueError), `normalize_gtin(raw: str) -> str` (14 cyfr; ValueError).
  - `transforms.py`: `TransformError(ValueError)`, `TransformContext(tree: SourceTree | None = None, node: Node | None = None)`, `REGISTRY: dict[str, Callable]`, `TRANSFORM_LABELS: dict[str, str]` (polskie opisy do UI), `apply_chain(value: str | None, chain: list, ctx: TransformContext | None = None) -> str | None`. Element łańcucha to `"nazwa"` albo `{"nazwa": argument}`.

- [ ] **Step 1: Testy wartości**

`tests/engine/test_values.py`:
```python
from decimal import Decimal

import pytest

from app.engine.values import fmt_money, fmt_price, fmt_qty, normalize_gtin, parse_date, to_decimal


@pytest.mark.parametrize("raw,expected", [
    ("80.50", "80.50"), ("12,5", "12.5"), ("1 234,56", "1234.56"), ("1.234,56", "1234.56"),
    ("1,234.56", "1234.56"), ("£80.50", "80.50"), ("-3,10", "-3.10"), ("1 000", "1000"),
    ("5", "5"), ("0", "0"),
])
def test_to_decimal_formats(raw, expected):
    assert to_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", "--"])
def test_to_decimal_invalid(raw):
    with pytest.raises(ValueError):
        to_decimal(raw)


def test_formatters():
    assert fmt_money(Decimal("80.5")) == "80.50"
    assert fmt_money(Decimal("1.005")) == "1.01"
    assert fmt_price(Decimal("8")) == "8.00"
    assert fmt_price(Decimal("1.6")) == "1.60"
    assert fmt_price(Decimal("0.12345")) == "0.1235"
    assert fmt_qty(Decimal("5.000")) == "5"
    assert fmt_qty(Decimal("2.50")) == "2.5"
    assert fmt_qty(Decimal("500")) == "500"


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-09", "2026-10-09"), ("09.10.2026", "2026-10-09"), ("09/10/2026", "2026-10-09"),
    ("20261009", "2026-10-09"), ("2026-10-08T10:00:00Z", "2026-10-08"),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        parse_date("32.13.2026")


def test_normalize_gtin():
    assert normalize_gtin("5909999000013") == "05909999000013"
    assert normalize_gtin(" 05909999000013 ") == "05909999000013"
    with pytest.raises(ValueError):
        normalize_gtin("5909999000014")
```

- [ ] **Step 2: Testy transformacji**

`tests/engine/test_transforms.py`:
```python
import pytest

from app.engine.transforms import REGISTRY, TransformContext, TransformError, apply_chain
from app.engine.tree import Node, SourceTree


def test_simple_chain():
    assert apply_chain(" 0% ", ["trim", "strip_percent", "decimal"]) == "0"
    assert apply_chain("abc", ["upper"]) == "ABC"
    assert apply_chain(None, ["trim"]) is None


def test_strip_ai_prefix():
    assert apply_chain("0105909999000013", ["strip_ai_prefix"]) == "05909999000013"
    assert apply_chain("5909999000013", ["strip_ai_prefix"]) == "5909999000013"


def test_gs1_transform():
    code = "01059099990000131527070910L2607"
    assert apply_chain(code, [{"gs1": "10"}]) == "L2607"
    assert apply_chain(code, [{"gs1": "15"}]) == "2027-07-09"
    assert apply_chain(code, [{"gs1": "01"}]) == "05909999000013"
    with pytest.raises(TransformError):
        apply_chain(code, [{"gs1": "17"}])


def test_date_and_map_and_convert():
    assert apply_chain("09-10-26", [{"date": "%d-%m-%y"}]) == "2026-10-09"
    assert apply_chain("6", [{"map": {"6": "przelew", "1": "gotówka"}}]) == "przelew"
    assert apply_chain("x", [{"map": {"6": "przelew"}}]) == "x"
    assert apply_chain("2,5", [{"convert": "12"}]) == "30"
    assert apply_chain("10", ["negate"]) == "-10"


def test_regex_split_constant():
    assert apply_chain("FV 123/2026", [{"regex_extract": {"pattern": r"(\d+)/", "group": 1}}]) == "123"
    assert apply_chain("00-952 Przykładowo", [{"split": {"sep": " ", "index": 0}}]) == "00-952"
    assert apply_chain(None, [{"constant": "PLN"}]) == "PLN"
    with pytest.raises(TransformError):
        apply_chain("x", [{"regex_extract": {"pattern": "a" * 201}}])


def test_concat_uses_context():
    root = Node("R")
    root.add(Node("A", "ul. X"))
    root.add(Node("B", "1"))
    ctx = TransformContext(tree=SourceTree(root, "xml"))
    assert apply_chain(None, [{"concat": {"paths": ["R/A", "R/B"], "sep": " "}}], ctx) == "ul. X 1"


def test_unknown_transform():
    with pytest.raises(TransformError, match="Nieznana transformacja"):
        apply_chain("x", ["eval"])


def test_registry_whitelist():
    assert set(REGISTRY) == {
        "trim", "upper", "lower", "decimal", "strip_percent", "date", "regex_extract", "map",
        "convert", "constant", "concat", "split", "negate", "gs1", "strip_ai_prefix",
    }
```

- [ ] **Step 3: Uruchom — FAIL.**

- [ ] **Step 4: Implementacja `app/engine/values.py`**

```python
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .gs1 import is_valid_gtin

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y.%m.%d")


def to_decimal(raw) -> Decimal:
    if raw is None:
        raise ValueError("Brak wartości liczbowej.")
    s = str(raw).strip().replace(" ", "").replace(" ", "")
    s = re.sub(r"[^\d,.\-+]", "", s)
    if not re.search(r"\d", s):
        raise ValueError(f"Nieprawidłowa liczba: {raw!r}")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") == 1:
        s = s.replace(",", ".")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Nieprawidłowa liczba: {raw!r}") from None


def fmt_money(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_price(d: Decimal) -> str:
    q = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize()
    s = format(q, "f")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def fmt_qty(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def parse_date(raw: str) -> str:
    s = (raw or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T", s):
        s = s[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Nierozpoznany format daty: {raw!r}")


def normalize_gtin(raw: str) -> str:
    s = re.sub(r"\s", "", raw or "")
    if not is_valid_gtin(s):
        raise ValueError(f"Niepoprawny GTIN/EAN (cyfra kontrolna lub długość): {raw!r}")
    return s.zfill(14)
```

Uwaga do `fmt_qty`: `Decimal("500").normalize()` daje `5E+2`, ale `format(..., "f")` zwraca `"500"`. Test to sprawdza.

- [ ] **Step 5: Implementacja `app/engine/transforms.py`**

```python
"""Biała lista transformacji wartości. Każda: (value, arg, ctx) -> str | None."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .gs1 import DATE_AIS, GS1Error, gs1_date, parse_gs1
from .tree import Node, SourceTree
from .values import fmt_qty, to_decimal

MAX_PATTERN = 200
MAX_INPUT = 1000


class TransformError(ValueError):
    pass


@dataclass
class TransformContext:
    tree: SourceTree | None = None
    node: Node | None = None


def _need(value):
    if value is None:
        raise TransformError("Brak wartości wejściowej.")
    return value


def _decimal(v, arg, ctx):
    if v is None:
        return None
    try:
        return fmt_qty(to_decimal(v))
    except ValueError as exc:
        raise TransformError(str(exc)) from exc


def _date(v, arg, ctx):
    if v is None:
        return None
    try:
        return datetime.strptime(v.strip(), arg).date().isoformat()
    except (ValueError, TypeError) as exc:
        raise TransformError(f"Data {v!r} nie pasuje do formatu {arg!r}.") from exc


def _regex(v, arg, ctx):
    if v is None:
        return None
    pattern = (arg or {}).get("pattern", "")
    group = int((arg or {}).get("group", 0))
    if len(pattern) > MAX_PATTERN:
        raise TransformError("Wyrażenie regularne jest za długie (max 200 znaków).")
    try:
        m = re.search(pattern, v[:MAX_INPUT])
    except re.error as exc:
        raise TransformError(f"Błędne wyrażenie regularne: {exc}.") from exc
    if not m:
        raise TransformError(f"Wartość {v!r} nie pasuje do wzorca.")
    return m.group(group)


def _convert(v, arg, ctx):
    if v is None:
        return None
    try:
        return fmt_qty(to_decimal(v) * to_decimal(arg))
    except ValueError as exc:
        raise TransformError(str(exc)) from exc


def _negate(v, arg, ctx):
    if v is None:
        return None
    try:
        return fmt_qty(-to_decimal(v))
    except ValueError as exc:
        raise TransformError(str(exc)) from exc


def _concat(v, arg, ctx):
    if not ctx or not ctx.tree:
        raise TransformError("Brak kontekstu dokumentu dla 'concat'.")
    parts = []
    for p in (arg or {}).get("paths", []):
        val = ctx.tree.first(p, ctx.node) if ctx.node is not None else ctx.tree.first(p)
        if val:
            parts.append(val)
    return (arg or {}).get("sep", " ").join(parts) or None


def _split(v, arg, ctx):
    if v is None:
        return None
    pieces = v.split((arg or {}).get("sep", " "))
    idx = int((arg or {}).get("index", 0))
    try:
        return pieces[idx].strip()
    except IndexError:
        raise TransformError(f"Brak części nr {idx} po podziale {v!r}.") from None


def _gs1(v, arg, ctx):
    if v is None:
        return None
    try:
        parsed = parse_gs1(v)
    except GS1Error as exc:
        raise TransformError(str(exc)) from exc
    ai = str(arg)
    if ai not in parsed:
        raise TransformError(f"Kod GS1 nie zawiera AI ({ai}).")
    return gs1_date(parsed[ai]) if ai in DATE_AIS else parsed[ai]


def _strip_ai_prefix(v, arg, ctx):
    if v and len(v) == 16 and v.startswith("01") and v.isdigit():
        return v[2:]
    return v


REGISTRY: dict[str, Callable[[Any, Any, TransformContext | None], str | None]] = {
    "trim": lambda v, a, c: v.strip() if v is not None else None,
    "upper": lambda v, a, c: v.upper() if v is not None else None,
    "lower": lambda v, a, c: v.lower() if v is not None else None,
    "decimal": _decimal,
    "strip_percent": lambda v, a, c: v.replace("%", "").strip() if v is not None else None,
    "date": _date,
    "regex_extract": _regex,
    "map": lambda v, a, c: (a or {}).get(v, v) if v is not None else None,
    "convert": _convert,
    "constant": lambda v, a, c: None if a is None else str(a),
    "concat": _concat,
    "split": _split,
    "negate": _negate,
    "gs1": _gs1,
    "strip_ai_prefix": _strip_ai_prefix,
}

TRANSFORM_LABELS = {
    "trim": "Usuń spacje z brzegów",
    "upper": "Wielkie litery",
    "lower": "Małe litery",
    "decimal": "Liczba (przecinek/kropka)",
    "strip_percent": "Usuń znak %",
    "date": "Data wg formatu (np. %d.%m.%Y)",
    "regex_extract": "Wytnij wyrażeniem regularnym",
    "map": "Zamień wartości wg słownika",
    "convert": "Pomnóż przez współczynnik",
    "constant": "Stała wartość",
    "concat": "Połącz kilka pól",
    "split": "Podziel i weź część",
    "negate": "Zmień znak (korekty)",
    "gs1": "Wyciągnij AI z kodu GS1-128",
    "strip_ai_prefix": "Usuń prefiks AI 01 z EAN",
}


def apply_chain(value: str | None, chain: list, ctx: TransformContext | None = None) -> str | None:
    for step in chain or []:
        if isinstance(step, str):
            name, arg = step, None
        elif isinstance(step, dict) and len(step) == 1:
            name, arg = next(iter(step.items()))
        else:
            raise TransformError(f"Niepoprawny krok transformacji: {step!r}")
        fn = REGISTRY.get(name)
        if fn is None:
            raise TransformError(f"Nieznana transformacja: {name!r}")
        value = fn(value, arg, ctx)
    return value
```

- [ ] **Step 6: PASS:** `pytest tests/engine -q`

- [ ] **Step 7: Commit**
```bash
git add app/engine/values.py app/engine/transforms.py tests/engine/test_values.py tests/engine/test_transforms.py
git commit -m "feat(engine): normalizacja liczb/dat/GTIN i biała lista transformacji

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 6: Model kanoniczny, problemy (Issue) i interfejs Lookups

**Files:**
- Create: `app/engine/canonical.py`, `app/engine/issues.py`, `app/engine/lookups.py`
- Test: `tests/engine/test_canonical.py`

**Interfaces:**
- Produces:
  - `canonical.py`: stałe rodzajów `TEXT, DATE, MONEY, PRICE, DECIMAL, GTIN, UNIT, LIST`; `FieldDef(key, label, kind=TEXT, required=False)`; `HEADER_FIELDS: list[FieldDef]`, `LINE_FIELDS: list[FieldDef]`, `HEADER_KEYS: set[str]`, `LINE_KEYS: set[str]`, `FIELD_LABELS: dict[str,str]`; `empty_invoice() -> dict`; `get_path(d: dict, dotted: str)`; `set_path(d: dict, dotted: str, value) -> None`.
  - `issues.py`: `BLOCKING = "blocking"`, `WARNING = "warning"`; `@dataclass Issue(code, severity, message, field=None, line_no=None, source_path=None, source_value=None, suggestions: list[dict] = [])` z `to_dict()`; `has_blocking(issues: list[Issue | dict]) -> bool`. Kody: `unreadable, unknown_supplier, unmapped_field, transform_error, invalid_value, unknown_unit, missing_conversion, unmapped_product, sum_mismatch_line, sum_mismatch_total, duplicate`.
  - `lookups.py`: `Protocol Lookups` z metodami `unit_for_alias(alias: str, supplier_id: int | None) -> str | None`, `is_base_unit(code: str) -> bool`, `conversion(supplier_id: int | None, product_code: str | None, from_unit: str) -> tuple[str, Decimal] | None`, `product_for(supplier_id: int | None, supplier_code: str | None, gtin: str | None) -> str | None` (zwraca nasz indeks `Product.code`); `MemoryLookups` (dataclass do testów: `units: dict[str,bool]` kod→czy bazowa, `aliases: dict[tuple[str, int|None], str]`, `conversions: dict[tuple[int|None, str|None, str], tuple[str, Decimal]]`, `product_by_code: dict[tuple[int|None, str], str]`, `product_by_gtin: dict[str, str]` (GTIN-14 → indeks)).

- [ ] **Step 1: Testy**

`tests/engine/test_canonical.py`:
```python
from decimal import Decimal

from app.engine.canonical import HEADER_KEYS, LINE_KEYS, empty_invoice, get_path, set_path
from app.engine.issues import BLOCKING, WARNING, Issue, has_blocking
from app.engine.lookups import MemoryLookups


def test_paths():
    inv = empty_invoice()
    set_path(inv, "supplier.address.city", "Przykładowo")
    assert get_path(inv, "supplier.address.city") == "Przykładowo"
    assert get_path(inv, "buyer.tax_id") is None
    assert inv["lines"] == []
    assert {"number", "supplier.tax_id", "totals.gross"} <= HEADER_KEYS
    assert {"qty", "unit", "gtin"} <= LINE_KEYS


def test_issue_helpers():
    issues = [Issue("x", WARNING, "uwaga"), Issue("y", BLOCKING, "stop").to_dict()]
    assert has_blocking(issues)
    assert not has_blocking([Issue("x", WARNING, "uwaga")])
    assert Issue("a", BLOCKING, "m").to_dict()["suggestions"] == []


def test_memory_lookups():
    lk = MemoryLookups(
        units={"szt": True, "karton": False},
        aliases={("pcs", 1): "szt", ("kart.", None): "karton"},
        conversions={(1, None, "karton"): ("szt", Decimal("12"))},
        product_by_code={(1, "A-1"): "TOW-1"},
        product_by_gtin={"05909999000013": "TOW-2"},
    )
    assert lk.unit_for_alias("PCS", 1) == "szt"
    assert lk.unit_for_alias("pcs", 2) is None
    assert lk.unit_for_alias("Kart.", 7) == "karton"
    assert lk.unit_for_alias("SZT", None) == "szt"
    assert not lk.is_base_unit("karton") and lk.is_base_unit("szt")
    assert lk.conversion(1, "TOW-9", "karton") == ("szt", Decimal("12"))
    assert lk.conversion(2, None, "karton") is None
    assert lk.product_for(1, "A-1", None) == "TOW-1"
    assert lk.product_for(5, "zzz", "05909999000013") == "TOW-2"
    assert lk.product_for(5, None, None) is None
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: `app/engine/canonical.py`**

```python
from dataclasses import dataclass

TEXT, DATE, MONEY, PRICE, DECIMAL, GTIN, UNIT, LIST = (
    "text", "date", "money", "price", "decimal", "gtin", "unit", "list")


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str = TEXT
    required: bool = False


HEADER_FIELDS = [
    FieldDef("doc_type", "Typ dokumentu"),
    FieldDef("number", "Numer faktury", TEXT, True),
    FieldDef("issue_date", "Data wystawienia", DATE, True),
    FieldDef("sale_date", "Data sprzedaży", DATE),
    FieldDef("due_date", "Termin płatności", DATE),
    FieldDef("payment_method", "Forma płatności"),
    FieldDef("currency", "Waluta", TEXT, True),
    FieldDef("supplier.name", "Dostawca — nazwa"),
    FieldDef("supplier.tax_id", "Dostawca — NIP/VAT"),
    FieldDef("supplier.address.street", "Dostawca — ulica"),
    FieldDef("supplier.address.postcode", "Dostawca — kod pocztowy"),
    FieldDef("supplier.address.city", "Dostawca — miejscowość"),
    FieldDef("supplier.address.country", "Dostawca — kraj"),
    FieldDef("buyer.name", "Nabywca — nazwa"),
    FieldDef("buyer.tax_id", "Nabywca — NIP/VAT"),
    FieldDef("buyer.address.street", "Nabywca — ulica"),
    FieldDef("buyer.address.postcode", "Nabywca — kod pocztowy"),
    FieldDef("buyer.address.city", "Nabywca — miejscowość"),
    FieldDef("buyer.address.country", "Nabywca — kraj"),
    FieldDef("totals.net", "Suma netto", MONEY),
    FieldDef("totals.vat", "Suma VAT", MONEY),
    FieldDef("totals.gross", "Suma brutto", MONEY, True),
    FieldDef("delivery_notes", "Numery WZ", LIST),
    FieldDef("corrected_invoice_number", "Nr faktury korygowanej"),
]

LINE_FIELDS = [
    FieldDef("supplier_code", "Kod towaru dostawcy"),
    FieldDef("gtin", "GTIN/EAN", GTIN),
    FieldDef("name", "Nazwa towaru", TEXT, True),
    FieldDef("qty", "Ilość", DECIMAL, True),
    FieldDef("unit", "Jednostka miary", UNIT, True),
    FieldDef("unit_price_net", "Cena netto", PRICE),
    FieldDef("net", "Wartość netto", MONEY, True),
    FieldDef("vat_rate", "Stawka VAT %", DECIMAL),
    FieldDef("vat", "Wartość VAT", MONEY),
    FieldDef("gross", "Wartość brutto", MONEY),
    FieldDef("batch", "Partia / seria"),
    FieldDef("expiry_date", "Data ważności", DATE),
]

HEADER_KEYS = {f.key for f in HEADER_FIELDS}
LINE_KEYS = {f.key for f in LINE_FIELDS}
FIELD_LABELS = {f.key: f.label for f in HEADER_FIELDS + LINE_FIELDS}
FIELD_LABELS["line_path"] = "Element z pozycjami faktury"


def _address() -> dict:
    return {"street": None, "postcode": None, "city": None, "country": None}


def empty_invoice() -> dict:
    return {
        "doc_type": "invoice", "number": None, "issue_date": None, "sale_date": None,
        "due_date": None, "payment_method": None, "currency": None,
        "supplier": {"name": None, "tax_id": None, "address": _address()},
        "buyer": {"name": None, "tax_id": None, "address": _address()},
        "totals": {"net": None, "vat": None, "gross": None},
        "delivery_notes": [], "corrected_invoice_number": None, "lines": [],
    }


def get_path(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_path(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
```

- [ ] **Step 4: `app/engine/issues.py`**

```python
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field  # atrybut Issue.field przesłoniłby dataclasses.field

BLOCKING = "blocking"
WARNING = "warning"


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    field: str | None = None
    line_no: int | None = None
    source_path: str | None = None
    source_value: str | None = None
    suggestions: list[dict] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def has_blocking(issues) -> bool:
    for i in issues:
        sev = i.severity if isinstance(i, Issue) else i.get("severity")
        if sev == BLOCKING:
            return True
    return False
```

- [ ] **Step 5: `app/engine/lookups.py`**

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class Lookups(Protocol):
    def unit_for_alias(self, alias: str, supplier_id: int | None) -> str | None: ...
    def is_base_unit(self, code: str) -> bool: ...
    def conversion(self, supplier_id: int | None, product_code: str | None,
                   from_unit: str) -> tuple[str, Decimal] | None: ...
    def product_for(self, supplier_id: int | None, supplier_code: str | None,
                    gtin: str | None) -> str | None: ...


def norm_alias(alias: str) -> str:
    return (alias or "").strip().lower()


@dataclass
class MemoryLookups:
    units: dict[str, bool] = field(default_factory=lambda: {"szt": True, "kg": True, "l": True, "m": True})
    aliases: dict[tuple[str, int | None], str] = field(default_factory=dict)
    conversions: dict[tuple[int | None, str | None, str], tuple[str, Decimal]] = field(default_factory=dict)
    product_by_code: dict[tuple[int | None, str], str] = field(default_factory=dict)
    product_by_gtin: dict[str, str] = field(default_factory=dict)

    def unit_for_alias(self, alias, supplier_id):
        a = norm_alias(alias)
        if a in self.units:
            return a
        return self.aliases.get((a, supplier_id)) or self.aliases.get((a, None))

    def is_base_unit(self, code):
        return self.units.get(code, True)

    def conversion(self, supplier_id, product_code, from_unit):
        for key in ((supplier_id, product_code, from_unit), (supplier_id, None, from_unit),
                    (None, product_code, from_unit), (None, None, from_unit)):
            if key in self.conversions:
                return self.conversions[key]
        return None

    def product_for(self, supplier_id, supplier_code, gtin):
        if supplier_code and (supplier_id, supplier_code) in self.product_by_code:
            return self.product_by_code[(supplier_id, supplier_code)]
        if gtin:
            return self.product_by_gtin.get(gtin.zfill(14))
        return None
```

- [ ] **Step 6: PASS:** `pytest tests/engine/test_canonical.py -q`

- [ ] **Step 7: Commit**
```bash
git add app/engine/canonical.py app/engine/issues.py app/engine/lookups.py tests/engine/test_canonical.py
git commit -m "feat(engine): model kanoniczny faktury, Issue i interfejs Lookups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---

### Task 7: Silnik szablonu — `apply_template`

**Files:**
- Create: `app/engine/template.py`
- Test: `tests/engine/test_template.py`

**Interfaces:**
- Consumes: `SourceTree` (Task 3), `apply_chain`, `TransformContext`, `TransformError` (Task 5), `to_decimal`, `fmt_*`, `parse_date`, `normalize_gtin` (Task 5), `HEADER_FIELDS`, `LINE_FIELDS`, `empty_invoice`, `get_path`, `set_path` (Task 6), `Issue`, `BLOCKING`, `WARNING` (Task 6), `Lookups` (Task 6).
- Produces: `ApplyResult(invoice: dict, issues: list[Issue])`; `apply_template(tree: SourceTree, rules: dict, lookups: Lookups, supplier_id: int | None = None, overrides: dict | None = None) -> ApplyResult`.
  - Format reguł: `{"line_path": str, "header": {key: rule}, "lines": {key: rule}, "defaults": {key: value}, "line_defaults": {key: value}}`, gdzie `rule = {"path": str, "transforms": [...]}` albo `{"constant": value, "transforms": [...]}`. Ścieżki w `header` są absolutne, a w `lines` względne do `line_path`.
  - Format `overrides`: `{"fields": {header_key: value}, "units": {alias: unit_code}, "products": {"<line_no>": product_code}, "allow_duplicate": bool}`.
  - Jednostka (`unit`) jest zawsze rozwiązywana przez `lookups.unit_for_alias` / `overrides.units`, nie przez transformację. To świadome uproszczenie względem specu, który wymieniał `unit_map` jako transformację. Surowa jednostka trafia do `unit_source`.
  - Kolejność per pozycja: pola z reguł → jednostka → towar (override → lookup) → przelicznik (gdy jednostka nie jest bazowa) → sprawdzenie wymaganych pól.

- [ ] **Step 1: Testy**

`tests/engine/test_template.py`:
```python
from decimal import Decimal
from pathlib import Path

from app.engine.issues import BLOCKING, WARNING, has_blocking
from app.engine.lookups import MemoryLookups
from app.engine.template import apply_template
from app.ingest import read_document

SAMPLES = Path(__file__).resolve().parents[2] / "demo" / "samples"

ALFA_RULES = {
    "line_path": "Document/Faktura/Pozycje/Pozycja",
    "header": {
        "number": {"path": "Document/Faktura/Naglowek/FakturaNumer"},
        "issue_date": {"path": "Document/Faktura/Naglowek/FakturaDataWystawienia"},
        "supplier.tax_id": {"path": "Document/Faktura/Naglowek/DostawcaNIP"},
        "supplier.name": {"path": "Document/Faktura/Naglowek/DostawcaNazwa"},
        "totals.net": {"path": "Document/Faktura/Naglowek/FakturaWartoscNetto"},
        "totals.gross": {"path": "Document/Faktura/Naglowek/FakturaWartoscBrutto"},
        "delivery_notes": {"path": "Document/Faktura/Naglowek/FakturaNumeryWZ"},
    },
    "lines": {
        "supplier_code": {"path": "TowarKod"},
        "gtin": {"path": "TowarKodEan", "transforms": ["strip_ai_prefix"]},
        "name": {"path": "TowarNazwa"},
        "qty": {"path": "Ilosc"},
        "unit": {"path": "TowarJm"},
        "unit_price_net": {"path": "CenaNetto"},
        "net": {"path": "WartoscNetto"},
        "vat_rate": {"path": "StawkaVat", "transforms": ["strip_percent"]},
        "batch": {"path": "TowarKodEan128", "transforms": [{"gs1": "10"}]},
        "expiry_date": {"path": "TowarKodEan128", "transforms": [{"gs1": "15"}]},
    },
    "defaults": {},
}


def alfa():
    return read_document((SAMPLES / "alfa-1.xml").read_bytes())


def full_lookups():
    return MemoryLookups(
        aliases={("pcs", 1): "szt"},
        product_by_gtin={"05909999000013": "TOW-0001", "05909999000020": "TOW-0002",
                         "05909999000037": "TOW-0003"},
    )


def codes(res):
    return [i.code for i in res.issues]


def test_missing_currency_is_blocking_then_default_fixes():
    res = apply_template(alfa(), ALFA_RULES, full_lookups(), supplier_id=1)
    assert codes(res) == ["unmapped_field"]
    assert res.issues[0].field == "currency" and res.issues[0].severity == BLOCKING
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"}}
    res = apply_template(alfa(), rules, full_lookups(), supplier_id=1)
    assert res.issues == []
    inv = res.invoice
    assert inv["currency"] == "GBP" and inv["number"] == "FA/2026/10/001"
    assert inv["delivery_notes"] == ["WZ-ALFA-0001"]
    assert inv["totals"]["gross"] == "155.50"
    l1 = inv["lines"][0]
    assert l1["gtin"] == "05909999000013" and l1["unit"] == "szt" and l1["unit_source"] == "pcs"
    assert l1["qty"] == "4" and l1["unit_price_net"] == "12.50" and l1["net"] == "50.00"
    assert l1["vat_rate"] == "0" and l1["batch"] == "L2607" and l1["expiry_date"] == "2027-07-09"
    assert l1["product_index"] == "TOW-0001" and l1["line_no"] == 1


def test_unknown_unit_reported_once_per_alias_and_override_fixes():
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"}}
    lk = full_lookups()
    lk.aliases = {}
    res = apply_template(alfa(), rules, lk, supplier_id=1)
    assert codes(res) == ["unknown_unit"]
    assert res.issues[0].source_value == "pcs"
    res = apply_template(alfa(), rules, lk, supplier_id=1, overrides={"units": {"pcs": "szt"}})
    assert res.issues == []


def test_unmapped_product_per_line_and_override():
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"}}
    lk = full_lookups()
    del lk.product_by_gtin["05909999000037"]
    res = apply_template(alfa(), rules, lk, supplier_id=1)
    assert codes(res) == ["unmapped_product"] and res.issues[0].line_no == 3
    res = apply_template(alfa(), rules, lk, supplier_id=1, overrides={"products": {"3": "TOW-0003"}})
    assert res.issues == []


def test_conversion_applied_and_missing_conversion():
    tree = read_document((SAMPLES / "delta.csv").read_bytes())
    rules = {
        "line_path": "csv/row",
        "header": {"number": {"path": "csv/row/NrFaktury"}, "issue_date": {"path": "csv/row/DataWystawienia"},
                   "currency": {"path": "csv/row/Waluta"}, "supplier.tax_id": {"path": "csv/row/SprzedawcaNIP"},
                   "totals.gross": {"path": "csv/row/RazemBrutto"}},
        "lines": {"supplier_code": {"path": "Kod"}, "name": {"path": "Nazwa"}, "gtin": {"path": "EAN"},
                  "qty": {"path": "Ilosc"}, "unit": {"path": "JM"}, "unit_price_net": {"path": "CenaNetto"},
                  "net": {"path": "WartoscNetto"}},
    }
    lk = MemoryLookups(units={"szt": True, "karton": False}, aliases={("kart.", 3): "karton"},
                       product_by_gtin={"05909999000068": "TOW-0006", "05909999000075": "TOW-0007"})
    res = apply_template(tree, rules, lk, supplier_id=3)
    assert codes(res) == ["missing_conversion", "missing_conversion"]
    lk.conversions[(3, None, "karton")] = ("szt", Decimal("12"))
    res = apply_template(tree, rules, lk, supplier_id=3)
    assert res.issues == []
    l1 = res.invoice["lines"][0]
    assert res.invoice["issue_date"] == "2026-10-09"
    assert (l1["qty"], l1["unit"], l1["unit_price_net"], l1["net"], l1["conversion_factor"]) == \
        ("24", "szt", "8.00", "192.00", "12")


def test_transform_error_and_invalid_value():
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"},
             "lines": {**ALFA_RULES["lines"], "expiry_date": {"path": "TowarKodEan128", "transforms": [{"gs1": "17"}]},
                       "gtin": {"path": "TowarKodEan"}}}
    res = apply_template(alfa(), rules, full_lookups(), supplier_id=1)
    sev = {i.code: i.severity for i in res.issues}
    # oba problemy dotyczą pól niewymaganych -> tylko ostrzeżenia
    assert sev["transform_error"] == WARNING and sev["invalid_value"] == WARNING
    # surowy 16-cyfrowy EAN nie pasuje do kartoteki -> towar nieprzypisany (blokujący)
    assert sev["unmapped_product"] == BLOCKING and has_blocking(res.issues)


def test_missing_line_path_blocks():
    res = apply_template(alfa(), {"header": {}, "lines": {}}, full_lookups())
    assert any(i.field == "line_path" and i.severity == BLOCKING for i in res.issues)


def test_constant_rule_and_field_override():
    rules = {**ALFA_RULES, "header": {**ALFA_RULES["header"], "currency": {"constant": "EUR"}}}
    res = apply_template(alfa(), rules, full_lookups(), 1, overrides={"fields": {"currency": "PLN"}})
    assert res.invoice["currency"] == "PLN" and res.issues == []
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implementacja `app/engine/template.py`**

```python
"""Zastosowanie deklaratywnego szablonu do drzewa źródłowego."""
from __future__ import annotations

from dataclasses import dataclass, field

from .canonical import (DATE, DECIMAL, GTIN, HEADER_FIELDS, LINE_FIELDS, LIST, MONEY, PRICE, TEXT,
                        UNIT, FieldDef, empty_invoice, get_path, set_path)
from .issues import BLOCKING, WARNING, Issue
from .lookups import Lookups
from .transforms import TransformContext, TransformError, apply_chain
from .tree import Node, SourceTree
from .values import fmt_money, fmt_price, fmt_qty, normalize_gtin, parse_date, to_decimal


@dataclass
class ApplyResult:
    invoice: dict
    issues: list[Issue] = field(default_factory=list)


def _eval_rule(tree: SourceTree, rule: dict | None, node: Node | None, f: FieldDef,
               issues: list[Issue], line_no: int | None):
    """Zwraca (surowa_wartość, ścieżka_źródłowa). Dla LIST surowa wartość to lista."""
    if not rule:
        return None, None
    src = rule.get("path")
    if "constant" in rule:
        raw = None if rule["constant"] is None else str(rule["constant"])
    elif src:
        vals = tree.values(src, node) if node is not None else tree.values(src)
        if f.kind == LIST:
            return (vals or None), src
        raw = vals[0] if vals else None
    else:
        raw = None
    try:
        raw = apply_chain(raw, rule.get("transforms") or [], TransformContext(tree, node))
    except TransformError as exc:
        issues.append(Issue("transform_error", BLOCKING if f.required else WARNING,
                            f"{f.label}: {exc}", field=f.key, line_no=line_no, source_path=src,
                            source_value=raw))
        return None, src
    return raw, src


def _coerce(f: FieldDef, raw, issues: list[Issue], line_no: int | None, src: str | None):
    if raw is None or raw == "" or raw == []:
        return [] if f.kind == LIST else None
    try:
        if f.kind == LIST:
            items = raw if isinstance(raw, list) else str(raw).split(",")
            return [str(x).strip() for x in items if str(x).strip()]
        if f.kind in (TEXT, UNIT):
            return str(raw).strip()
        if f.kind == DATE:
            return parse_date(str(raw))
        if f.kind == MONEY:
            return fmt_money(to_decimal(raw))
        if f.kind == PRICE:
            return fmt_price(to_decimal(raw))
        if f.kind == DECIMAL:
            return fmt_qty(to_decimal(raw))
        if f.kind == GTIN:
            return normalize_gtin(str(raw))
    except ValueError as exc:
        issues.append(Issue("invalid_value", BLOCKING if f.required else WARNING,
                            f"{f.label}: {exc}", field=f.key, line_no=line_no, source_path=src,
                            source_value=str(raw)))
        return str(raw) if f.kind == GTIN else None
    return raw


def apply_template(tree: SourceTree, rules: dict, lookups: Lookups, supplier_id: int | None = None,
                   overrides: dict | None = None) -> ApplyResult:
    rules = rules or {}
    overrides = overrides or {}
    field_over = overrides.get("fields") or {}
    unit_over = {k.strip().lower(): v for k, v in (overrides.get("units") or {}).items()}
    product_over = overrides.get("products") or {}
    defaults = rules.get("defaults") or {}
    line_defaults = rules.get("line_defaults") or {}
    invoice = empty_invoice()
    issues: list[Issue] = []

    # --- nagłówek ---
    failed: set[str] = set()
    for f in HEADER_FIELDS:
        before = len(issues)
        raw, src = _eval_rule(tree, (rules.get("header") or {}).get(f.key), None, f, issues, None)
        if raw in (None, "", []) and f.key in defaults:
            raw = defaults[f.key]
        if f.key in field_over:
            raw = field_over[f.key]
        value = _coerce(f, raw, issues, None, src)
        if len(issues) > before:
            failed.add(f.key)
        if f.key == "doc_type" and not value:
            value = "invoice"
        set_path(invoice, f.key, value)
    for f in HEADER_FIELDS:
        if f.required and get_path(invoice, f.key) in (None, "") and f.key not in failed:
            issues.append(Issue("unmapped_field", BLOCKING,
                                f"Brak wymaganego pola „{f.label}” — wskaż je w pliku albo ustaw wartość domyślną.",
                                field=f.key))
    if not get_path(invoice, "supplier.tax_id") and not get_path(invoice, "supplier.name"):
        issues.append(Issue("unmapped_field", BLOCKING,
                            "Brak danych dostawcy — wskaż pole z NIP/VAT albo nazwą dostawcy.",
                            field="supplier.tax_id"))

    # --- pozycje ---
    line_path = rules.get("line_path")
    nodes: list[Node] = []
    if not line_path:
        issues.append(Issue("unmapped_field", BLOCKING, "Nie wskazano elementu zawierającego pozycje faktury.",
                            field="line_path"))
    else:
        nodes = tree.nodes_at(line_path)
        if not nodes:
            issues.append(Issue("unmapped_field", BLOCKING,
                                f"Nie znaleziono pozycji pod ścieżką „{line_path}”.", field="line_path"))

    seen_units: set[str] = set()
    missing_reported: set[str] = set()
    for line_no, node in enumerate(nodes, start=1):
        line = {"line_no": line_no, "unit_source": None, "product_index": None, "conversion_factor": "1"}
        failed_line: set[str] = set()
        for f in LINE_FIELDS:
            before = len(issues)
            raw, src = _eval_rule(tree, (rules.get("lines") or {}).get(f.key), node, f, issues, line_no)
            if raw in (None, "") and f.key in line_defaults:
                raw = line_defaults[f.key]
            if len(issues) > before:
                failed_line.add(f.key)
            if f.kind == UNIT:
                alias = str(raw).strip() if raw not in (None, "") else None
                line["unit_source"] = alias
                unit = None
                if alias:
                    unit = unit_over.get(alias.lower()) or lookups.unit_for_alias(alias, supplier_id)
                    if unit is None and alias.lower() not in seen_units:
                        seen_units.add(alias.lower())
                        issues.append(Issue("unknown_unit", BLOCKING,
                                            f"Nieznana jednostka miary „{alias}” — wskaż odpowiadającą jej naszą jednostkę.",
                                            field="unit", line_no=line_no, source_path=src, source_value=alias))
                    if unit is None:
                        failed_line.add("unit")
                line["unit"] = unit
                continue
            line[f.key] = _coerce(f, raw, issues, line_no, src)
            if len(issues) > before:
                failed_line.add(f.key)

        # towar
        code = product_over.get(str(line_no)) or lookups.product_for(supplier_id, line.get("supplier_code"),
                                                                     line.get("gtin"))
        line["product_index"] = code
        if not code:
            label = " ".join(x for x in (line.get("supplier_code"), line.get("name")) if x)
            issues.append(Issue("unmapped_product", BLOCKING,
                                f"Pozycja {line_no}: nie przypisano towaru z naszej kartoteki ({label}).",
                                field="product_index", line_no=line_no, source_value=label or None))

        # przelicznik
        unit = line.get("unit")
        if unit and not lookups.is_base_unit(unit):
            conv = lookups.conversion(supplier_id, code, unit)
            if conv is None:
                issues.append(Issue("missing_conversion", BLOCKING,
                                    f"Pozycja {line_no}: brak przelicznika dla jednostki „{unit}” na jednostkę bazową.",
                                    field="unit", line_no=line_no, source_value=unit))
            else:
                to_unit, factor = conv
                if line.get("qty"):
                    line["qty"] = fmt_qty(to_decimal(line["qty"]) * factor)
                if line.get("unit_price_net"):
                    line["unit_price_net"] = fmt_price(to_decimal(line["unit_price_net"]) / factor)
                line["unit"] = to_unit
                line["conversion_factor"] = fmt_qty(factor)

        for f in LINE_FIELDS:
            if (f.required and line.get(f.key) in (None, "") and f.key not in failed_line
                    and f.key not in missing_reported):
                missing_reported.add(f.key)
                issues.append(Issue("unmapped_field", BLOCKING,
                                    f"Brak wymaganego pola pozycji „{f.label}” — wskaż je w pliku.",
                                    field=f.key, line_no=line_no))
        invoice["lines"].append(line)

    return ApplyResult(invoice, issues)
```

- [ ] **Step 4: PASS:** `pytest tests/engine/test_template.py -q`. Jeżeli `test_transform_error_and_invalid_value` daje `invalid_value` jako blocking: GTIN nie jest wymagany, więc `severity` musi być `WARNING`. Sprawdź `FieldDef("gtin", ..., GTIN)` bez `required`.

- [ ] **Step 5: Commit**
```bash
git add app/engine/template.py tests/engine/test_template.py
git commit -m "feat(engine): apply_template — reguły, jednostki, towary, przeliczniki, override'y

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---

### Task 8: Walidacja sum

**Files:**
- Create: `app/engine/validate.py`
- Test: `tests/engine/test_validate.py`

**Interfaces:**
- Consumes: `Issue`, `BLOCKING`, `WARNING` (Task 6), `to_decimal` (Task 5), format faktury z Task 7.
- Produces: `validate_invoice(invoice: dict) -> list[Issue]`; tolerancja `TOL = Decimal("0.01")`. Niezgodność w pozycji to `WARNING` (`sum_mismatch_line`), a w sumach nagłówka `BLOCKING` (`sum_mismatch_total`).

- [ ] **Step 1: Testy**

`tests/engine/test_validate.py`:
```python
from app.engine.canonical import empty_invoice
from app.engine.issues import BLOCKING, WARNING
from app.engine.validate import validate_invoice


def inv(lines, net=None, vat=None, gross=None):
    i = empty_invoice()
    i["lines"] = lines
    i["totals"] = {"net": net, "vat": vat, "gross": gross}
    return i


def line(qty, price, net, vat=None, gross=None):
    return {"line_no": 1, "qty": qty, "unit_price_net": price, "net": net, "vat": vat, "gross": gross}


def test_consistent_invoice_has_no_issues():
    i = inv([line("4", "12.50", "50.00", "0.00", "50.00"), line("10", "4.20", "42.00")], "92.00", "0.00", "92.00")
    assert validate_invoice(i) == []


def test_rounding_within_tolerance():
    assert validate_invoice(inv([line("3", "3.333", "10.00")], "10.00")) == []


def test_line_mismatch_is_warning():
    issues = validate_invoice(inv([line("4", "12.50", "51.00")], "51.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_line", WARNING)]


def test_line_net_vat_gross_mismatch_is_warning():
    issues = validate_invoice(inv([line("1", "10.00", "10.00", "2.30", "12.00")], "10.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_line", WARNING)]


def test_totals_mismatch_blocking():
    issues = validate_invoice(inv([line("1", "10.00", "10.00")], "11.00", "0.00", "11.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_total", BLOCKING)]
    issues = validate_invoice(inv([line("1", "10.00", "10.00")], "10.00", "2.30", "12.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_total", BLOCKING)]


def test_missing_values_are_skipped():
    assert validate_invoice(inv([line(None, None, "10.00")], None, None, "10.00")) == []
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implementacja `app/engine/validate.py`**

```python
from decimal import ROUND_HALF_UP, Decimal

from .issues import BLOCKING, WARNING, Issue
from .values import to_decimal

TOL = Decimal("0.01")


def _d(v):
    if v in (None, ""):
        return None
    try:
        return to_decimal(v)
    except ValueError:
        return None


def _r(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_invoice(invoice: dict) -> list[Issue]:
    issues: list[Issue] = []
    lines = invoice.get("lines") or []
    for ln in lines:
        no = ln.get("line_no")
        qty, price, net = _d(ln.get("qty")), _d(ln.get("unit_price_net")), _d(ln.get("net"))
        vat, gross = _d(ln.get("vat")), _d(ln.get("gross"))
        if qty is not None and price is not None and net is not None and abs(_r(qty * price) - net) > TOL:
            issues.append(Issue("sum_mismatch_line", WARNING,
                                f"Pozycja {no}: ilość × cena = {_r(qty * price)}, a wartość netto = {net}.",
                                field="net", line_no=no))
        elif net is not None and vat is not None and gross is not None and abs(net + vat - gross) > TOL:
            issues.append(Issue("sum_mismatch_line", WARNING,
                                f"Pozycja {no}: netto + VAT = {net + vat}, a brutto = {gross}.",
                                field="gross", line_no=no))
    t = invoice.get("totals") or {}
    t_net, t_vat, t_gross = _d(t.get("net")), _d(t.get("vat")), _d(t.get("gross"))
    nets = [_d(ln.get("net")) for ln in lines]
    if t_net is not None and lines and all(n is not None for n in nets):
        s = sum(nets, Decimal("0"))
        if abs(s - t_net) > TOL:
            issues.append(Issue("sum_mismatch_total", BLOCKING,
                                f"Suma netto pozycji ({s}) różni się od sumy netto faktury ({t_net}).",
                                field="totals.net"))
    if t_net is not None and t_vat is not None and t_gross is not None and abs(t_net + t_vat - t_gross) > TOL:
        issues.append(Issue("sum_mismatch_total", BLOCKING,
                            f"Netto + VAT faktury ({t_net + t_vat}) różni się od brutto ({t_gross}).",
                            field="totals.gross"))
    return issues
```

- [ ] **Step 4: PASS:** `pytest tests/engine/test_validate.py -q`

- [ ] **Step 5: Commit**
```bash
git add app/engine/validate.py tests/engine/test_validate.py
git commit -m "feat(engine): walidacja sum pozycji i nagłówka

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 9: Słownik synonimów i podpowiedzi (`suggest`)

**Files:**
- Create: `data/synonyms.yaml`, `app/engine/suggest.py`
- Test: `tests/engine/test_suggest.py`

**Interfaces:**
- Consumes: `SourceTree`, `relative_path` (Task 3), `parse_gs1`, `is_valid_gtin`, `GS1Error` (Task 4), `apply_chain`, `TransformError`, `parse_date`, `to_decimal` (Task 5), `HEADER_FIELDS`, `LINE_FIELDS`, `LINE_KEYS`, `FieldDef` (Task 6).
- Produces:
  - `load_synonyms(path: Path | None = None) -> dict` (klucze: `header`, `lines`, `units`).
  - `Candidate(path, transforms, confidence, reason, preview)` + `to_dict()` (dodaje `"kind": "path"`).
  - `suffix_match(path: str, synonym: str) -> bool` (porównanie końcowych segmentów, bez rozróżniania wielkości liter).
  - `learned_pairs(rule_sets: Iterable[dict]) -> dict[tuple[str, str], str]` (z istniejących szablonów).
  - `field_candidates(tree, field_key, line_path, synonyms, learned=None, limit=5) -> list[Candidate]`.
  - `draft_rules(tree, synonyms, learned=None, threshold=0.5) -> dict` (format reguł z Task 7).
  - `unit_candidates(alias: str, unit_codes: list[str], synonyms: dict, limit=5) -> list[dict]` → `{"kind": "unit", "unit", "confidence", "reason"}`.
  - `product_candidates(line: dict, products: list[dict], limit=5) -> list[dict]` (`products`: `{"code","name","gtin"}`) → `{"kind": "product", "code", "name", "confidence", "reason"}`.
  - `supplier_candidates(name, tax_id, suppliers: list[dict], limit=5) -> list[dict]` (`suppliers`: `{"id","name","tax_id"}`) → `{"kind": "use_supplier", "supplier_id", "name", "confidence", "reason"}`.
  - `norm_tax_id(value: str | None) -> str` (wielkie litery, tylko A–Z0–9) i `tax_ids_match(a, b) -> bool` (ignoruje 2-literowy prefiks kraju).
  - `conversion_guess(line_name: str | None, from_unit: str) -> dict` → `{"kind": "conversion", "from_unit", "to_unit", "factor": str | None, "confidence"}`.
  - Progi pewności: wcześniejszy szablon 0.95; synonim `max(0.6, 0.9 − 0.02·pozycja)`; detektor GS1 0.7, GTIN 0.6, data/NIP 0.4, liczba 0.3; kandydat nagłówka znaleziony w pozycjach ×0.8.

- [ ] **Step 1: `data/synonyms.yaml`**

```yaml
# Synonimy tagów: dopasowanie po KOŃCOWYCH segmentach ścieżki, bez rozróżniania wielkości liter.
# Kolejność ma znaczenie — wcześniejszy synonim = wyższa pewność.
header:
  number: [FakturaNumer, NumerFaktury, NrFaktury, InvoiceNumber, Fa/P_2, Invoice/ID, invoice/number]
  issue_date: [FakturaDataWystawienia, DataWystawienia, IssueDate, Fa/P_1, invoice/issue_date, InvoiceDate]
  sale_date: [DataSprzedazy, Fa/P_6, TaxPointDate, invoice/sale_date]
  due_date: [FakturaDataPlatnosci, DataPlatnosci, TerminPlatnosci/Termin, TerminPlatnosci, DueDate, PaymentDueDate, invoice/due_date]
  payment_method: [FakturaTypPlatnosci, FormaPlatnosci, PaymentMeansCode, invoice/payment_method]
  currency: [FakturaWaluta, Waluta, KodWaluty, DocumentCurrencyCode, invoice/currency, Currency]
  supplier.name: [DostawcaNazwa, SprzedawcaNazwa, NazwaSprzedawcy, Podmiot1/DaneIdentyfikacyjne/Nazwa, AccountingSupplierParty/Party/PartyName/Name, AccountingSupplierParty/Party/PartyLegalEntity/RegistrationName, seller/name, supplier/name, SellerName, SupplierName]
  supplier.tax_id: [DostawcaNIP, SprzedawcaNIP, NIPSprzedawcy, Podmiot1/DaneIdentyfikacyjne/NIP, AccountingSupplierParty/Party/PartyTaxScheme/CompanyID, seller/vat_number, seller/vat_id, supplier/vat_number, SellerVAT, SupplierVAT]
  supplier.address.street: [DostawcaAdresUlica, SprzedawcaUlica, Podmiot1/Adres/AdresL1, AccountingSupplierParty/Party/PostalAddress/StreetName, seller/address/street]
  supplier.address.postcode: [DostawcaAdresKodPocztowy, SprzedawcaKodPocztowy, AccountingSupplierParty/Party/PostalAddress/PostalZone, seller/address/postcode]
  supplier.address.city: [DostawcaAdresMiejscowosc, SprzedawcaMiejscowosc, Podmiot1/Adres/AdresL2, AccountingSupplierParty/Party/PostalAddress/CityName, seller/address/city]
  supplier.address.country: [DostawcaKraj, Podmiot1/Adres/KodKraju, AccountingSupplierParty/Party/PostalAddress/Country/IdentificationCode, seller/address/country]
  buyer.name: [NabywcaNazwa, NazwaNabywcy, Podmiot2/DaneIdentyfikacyjne/Nazwa, AccountingCustomerParty/Party/PartyName/Name, buyer/name, BuyerName]
  buyer.tax_id: [NabywcaNIP, NIPNabywcy, Podmiot2/DaneIdentyfikacyjne/NIP, AccountingCustomerParty/Party/PartyTaxScheme/CompanyID, buyer/vat_number, buyer/vat_id, BuyerVAT]
  buyer.address.street: [NabywcaAdresUlica, Podmiot2/Adres/AdresL1, AccountingCustomerParty/Party/PostalAddress/StreetName, buyer/address/street]
  buyer.address.postcode: [NabywcaAdresKodPocztowy, AccountingCustomerParty/Party/PostalAddress/PostalZone, buyer/address/postcode]
  buyer.address.city: [NabywcaAdresMiejscowosc, Podmiot2/Adres/AdresL2, AccountingCustomerParty/Party/PostalAddress/CityName, buyer/address/city]
  buyer.address.country: [NabywcaKraj, Podmiot2/Adres/KodKraju, AccountingCustomerParty/Party/PostalAddress/Country/IdentificationCode, buyer/address/country]
  totals.net: [FakturaWartoscNetto, RazemNetto, SumaNetto, Fa/P_13_1, LegalMonetaryTotal/TaxExclusiveAmount, totals/net]
  totals.vat: [FakturaWartoscVat, RazemVAT, SumaVAT, Fa/P_14_1, Invoice/TaxTotal/TaxAmount, totals/vat]
  totals.gross: [FakturaWartoscBrutto, RazemBrutto, SumaBrutto, Fa/P_15, LegalMonetaryTotal/TaxInclusiveAmount, LegalMonetaryTotal/PayableAmount, totals/gross]
  delivery_notes: [FakturaNumeryWZ, NumeryWZ, NumerWZ, Fa/WZ, DespatchDocumentReference/ID, invoice/delivery_notes]
  corrected_invoice_number: [NumerFakturyKorygowanej, NrFaKorygowanej, BillingReference/InvoiceDocumentReference/ID]
lines:
  supplier_code: [TowarKod, KodTowaru, Indeks, Kod, SellersItemIdentification/ID, sku, ProductCode]
  gtin: [TowarKodEan, KodEAN, EAN, GTIN, StandardItemIdentification/ID, ean, gtin]
  name: [TowarNazwa, NazwaTowaru, Nazwa, P_7, Item/Name, description, ProductName]
  qty: [Ilosc, P_8B, InvoicedQuantity, quantity, Quantity]
  unit: [TowarJm, JM, Jm, JednostkaMiary, P_8A, InvoicedQuantity/@unitCode, uom, unit]
  unit_price_net: [CenaNetto, P_9A, Price/PriceAmount, unit_price, UnitPrice]
  net: [WartoscNetto, P_11, LineExtensionAmount, net_amount, NetAmount]
  vat_rate: [StawkaVat, P_12, ClassifiedTaxCategory/Percent, vat_rate, VatRate]
  vat: [WartoscVat, KwotaVat, vat_amount]
  gross: [WartoscBrutto, P_11A, gross_amount]
  batch: [TowarDostawaNumerSerii, NumerSerii, NumerPartii, Partia, LotNumberID, batch]
  expiry_date: [TowarDostawaDataWaznosci, DataWaznosci, BestBeforeDate, ExpiryDate, expiry_date]
# Znane kody jednostek (UN/ECE Rec. 20 i popularne skróty) -> nasz kod jednostki.
# To są TYLKO podpowiedzi — nie są aliasami, operator zatwierdza.
units:
  pcs: szt
  pc: szt
  "szt.": szt
  sztuk: szt
  c62: szt
  h87: szt
  ea: szt
  pce: szt
  kgm: kg
  kilogram: kg
  ltr: l
  litr: l
  mtr: m
  "kart.": karton
  ct: karton
  ctn: karton
  bx: karton
  bg: worek
  sack: worek
  pk: opak
  pa: opak
  "op.": opak
```

- [ ] **Step 2: Testy**

`tests/engine/test_suggest.py`:
```python
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.suggest import (conversion_guess, draft_rules, field_candidates, learned_pairs,
                                load_synonyms, norm_tax_id, product_candidates, suffix_match,
                                supplier_candidates, tax_ids_match, unit_candidates)
from app.engine.template import apply_template
from app.engine.validate import validate_invoice
from app.ingest import read_document

SAMPLES = Path(__file__).resolve().parents[2] / "demo" / "samples"


class Permissive:
    def unit_for_alias(self, alias, supplier_id): return alias.lower()
    def is_base_unit(self, code): return True
    def conversion(self, *a): return None
    def product_for(self, *a): return "X"


def tree(name):
    return read_document((SAMPLES / name).read_bytes(), name)


@pytest.mark.parametrize("name,number,gross,n_lines,first_qty,expected_codes", [
    ("alfa-1.xml", "FA/2026/10/001", "155.50", 3, "4", ["unmapped_field"]),
    ("beta-ksef.xml", "FV/B/1024/2026", "1050.00", 2, "20", []),
    ("gamma-ubl.xml", "GAM-2026-0315", "83.46", 2, "12", []),
    ("delta.csv", "D/77/2026", "383.76", 2, "2", []),
    ("epsilon.json", "E-2026-0042", "45.60", 2, "6", []),
])
def test_draft_rules_read_every_sample(name, number, gross, n_lines, first_qty, expected_codes):
    t = tree(name)
    rules = draft_rules(t, load_synonyms())
    res = apply_template(t, rules, Permissive(), supplier_id=1)
    assert [i.code for i in res.issues] == expected_codes
    inv = res.invoice
    assert inv["number"] == number
    assert inv["totals"]["gross"] == gross
    assert len(inv["lines"]) == n_lines
    assert inv["lines"][0]["qty"] == first_qty
    assert validate_invoice(inv) == []


def test_alfa_draft_uses_gs1_and_ai_prefix():
    rules = draft_rules(tree("alfa-1.xml"), load_synonyms())
    assert rules["lines"]["gtin"]["transforms"] == ["strip_ai_prefix"]
    assert rules["lines"]["batch"] == {"path": "TowarKodEan128", "transforms": [{"gs1": "10"}]}
    assert rules["lines"]["expiry_date"]["transforms"] == [{"gs1": "15"}]
    assert rules["lines"]["vat_rate"]["transforms"] == ["strip_percent"]
    assert "currency" not in rules["header"]


def test_ubl_unit_from_attribute():
    rules = draft_rules(tree("gamma-ubl.xml"), load_synonyms())
    assert rules["lines"]["unit"]["path"] == "InvoicedQuantity/@unitCode"


def test_learned_pairs_take_priority():
    t = tree("alfa-1.xml")
    learned = learned_pairs([{"header": {"currency": {"path": "Document/Faktura/Naglowek/FakturaTypPlatnosci"}}}])
    cands = field_candidates(t, "currency", "Document/Faktura/Pozycje/Pozycja", load_synonyms(), learned)
    assert cands[0].path.endswith("FakturaTypPlatnosci") and cands[0].confidence == 0.95


def test_header_fallback_inside_lines_for_csv():
    cands = field_candidates(tree("delta.csv"), "number", "csv/row", load_synonyms())
    assert cands[0].path == "csv/row/NrFaktury" and cands[0].confidence < 0.9


def test_suffix_match():
    assert suffix_match("Invoice/AccountingSupplierParty/Party/PartyName/Name", "PartyName/Name")
    assert not suffix_match("A/TowarKodEan128", "TowarKodEan")
    assert suffix_match("a/B/c", "b/C")


def test_unit_candidates():
    syn = load_synonyms()
    codes = ["szt", "kg", "l", "m", "karton", "worek", "opak"]
    assert unit_candidates("pcs", codes, syn)[0] == {"kind": "unit", "unit": "szt", "confidence": 0.95,
                                                     "reason": "znany kod jednostki"}
    assert unit_candidates("C62", codes, syn)[0]["unit"] == "szt"
    assert unit_candidates("kart.", codes, syn)[0]["unit"] == "karton"
    assert unit_candidates("kartony", codes, syn)[0]["unit"] == "karton"


def test_product_candidates():
    products = [{"code": "TOW-0003", "name": "Masa marcepanowa 5kg", "gtin": None},
                {"code": "TOW-0001", "name": "Posypka czekoladowa 1 kg", "gtin": "5909999000013"}]
    c = product_candidates({"name": "Masa marcepanowa 5 kg", "gtin": "05909999000037"}, products)
    assert c[0]["code"] == "TOW-0003" and c[0]["confidence"] >= 0.7
    c = product_candidates({"name": "coś innego", "gtin": "05909999000013"}, products)
    assert c[0] == {"kind": "product", "code": "TOW-0001", "name": "Posypka czekoladowa 1 kg",
                    "confidence": 1.0, "reason": "zgodny GTIN"}


def test_supplier_candidates_and_tax_ids():
    assert norm_tax_id(" pl 999-000-00-11 ") == "PL9990000011"
    assert tax_ids_match("PL9990000011", "9990000011")
    assert not tax_ids_match("PL9990000011", "9990000022")
    sups = [{"id": 1, "name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "9990000011"}]
    assert supplier_candidates("X", "PL9990000011", sups)[0]["supplier_id"] == 1
    assert supplier_candidates("Hurtownia Alfa", None, sups)[0]["confidence"] >= 0.7


def test_conversion_guess():
    assert conversion_guess("Mąka pszenna typ 450 25 kg", "worek") == {
        "kind": "conversion", "from_unit": "worek", "to_unit": "kg", "factor": "25", "confidence": 0.7}
    g = conversion_guess("Pudełko na tort 30x30", "karton")
    assert g["to_unit"] == "szt" and g["factor"] is None
    assert conversion_guess("Śmietanka 500 ml", "karton")["factor"] == "0.5"
```

- [ ] **Step 3: FAIL.**

- [ ] **Step 4: Implementacja `app/engine/suggest.py`**

```python
"""Podpowiedzi mapowań — wyłącznie heurystyki (bez LLM)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import yaml
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from .canonical import (DATE, DECIMAL, GTIN, HEADER_FIELDS, LINE_FIELDS, LINE_KEYS, MONEY, PRICE,
                        FieldDef)
from .gs1 import GS1Error, is_valid_gtin, parse_gs1
from .transforms import TransformError, apply_chain
from .tree import SourceTree, relative_path
from .values import parse_date, to_decimal

DEFAULT_SYNONYMS = Path(__file__).resolve().parents[2] / "data" / "synonyms.yaml"
FIELDS_BY_KEY = {f.key: f for f in HEADER_FIELDS + LINE_FIELDS}
MULTI_USE = {"batch", "expiry_date"}
_CACHE: dict[Path, dict] = {}


def load_synonyms(path: Path | None = None) -> dict:
    p = Path(path or DEFAULT_SYNONYMS)
    if p not in _CACHE:
        with p.open(encoding="utf-8") as fh:
            _CACHE[p] = yaml.safe_load(fh) or {}
    return _CACHE[p]


@dataclass
class Candidate:
    path: str
    transforms: list = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    preview: str | None = None

    def to_dict(self) -> dict:
        return {"kind": "path", **asdict(self)}


def suffix_match(path: str, synonym: str) -> bool:
    segs = path.lower().split("/")
    s = synonym.lower().split("/")
    return len(s) <= len(segs) and segs[-len(s):] == s


def _tail(path: str, n: int = 2) -> str:
    return "/".join(path.lower().split("/")[-n:])


def learned_pairs(rule_sets: Iterable[dict]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for rules in rule_sets:
        for key, rule in ((rules or {}).get("header") or {}).items():
            if (rule or {}).get("path"):
                out[("header", _tail(rule["path"]))] = key
        for key, rule in ((rules or {}).get("lines") or {}).items():
            if (rule or {}).get("path"):
                out[("lines", rule["path"].lower())] = key
    return out


def _gs1_ais(value: str) -> dict[str, str]:
    if len(value) < 18 or not value.startswith("01"):
        return {}
    try:
        parsed = parse_gs1(value)
    except GS1Error:
        return {}
    return parsed if len(parsed) >= 2 else {}


def _detect(f: FieldDef, value: str) -> tuple[float, list] | None:
    v = value.strip()
    if f.kind == GTIN:
        if len(v) == 16 and v.startswith("01") and is_valid_gtin(v[2:]):
            return 0.6, ["strip_ai_prefix"]
        if len(v) >= 12 and is_valid_gtin(v):
            return 0.6, []
    if f.key == "batch":
        if "10" in _gs1_ais(v):
            return 0.7, [{"gs1": "10"}]
    if f.key == "expiry_date":
        ais = _gs1_ais(v)
        for ai in ("17", "15"):
            if ai in ais:
                return 0.7, [{"gs1": ai}]
    if f.kind == DATE:
        try:
            parse_date(v)
            return 0.4, []
        except ValueError:
            pass
    if f.key.endswith("tax_id") and re.fullmatch(r"[A-Z]{0,2}\d{8,12}", re.sub(r"[\s-]", "", v.upper())):
        return 0.4, []
    if f.kind in (MONEY, PRICE, DECIMAL):
        try:
            to_decimal(v)
            if re.fullmatch(r"[\d\s.,\-+%£€$]+", v):
                return 0.3, []
        except ValueError:
            pass
    return None


def _infer_transforms(f: FieldDef, value: str) -> list:
    v = (value or "").strip()
    if f.kind == GTIN and len(v) == 16 and v.startswith("01") and is_valid_gtin(v[2:]):
        return ["strip_ai_prefix"]
    if f.key == "vat_rate" and "%" in v:
        return ["strip_percent"]
    return []


def _preview(value: str | None, transforms: list) -> str | None:
    try:
        return apply_chain(value, transforms)
    except TransformError:
        return None


def _score(pool: dict[str, str], f: FieldDef, syns: list[str], learned: dict, scope: str) -> list[Candidate]:
    out = []
    for path, value in pool.items():
        score, reason, transforms = 0.0, "", []
        key = _tail(path) if scope == "header" else path.lower()
        if learned.get((scope, key)) == f.key:
            score, reason = 0.95, "z wcześniejszego szablonu"
        for idx, syn in enumerate(syns):
            if suffix_match(path, syn):
                s = max(0.6, 0.9 - 0.02 * idx)
                if s > score:
                    score, reason = s, f"synonim „{syn}”"
                break
        if score:
            transforms = _infer_transforms(f, value)
        else:
            det = _detect(f, value)
            if det:
                score, transforms = det
                reason = "rozpoznany typ wartości"
        if score:
            out.append(Candidate(path, transforms, round(score, 2), reason, _preview(value, transforms)))
    return out


def field_candidates(tree: SourceTree, field_key: str, line_path: str | None, synonyms: dict,
                     learned: dict | None = None, limit: int = 5) -> list[Candidate]:
    f = FIELDS_BY_KEY[field_key]
    scope = "lines" if field_key in LINE_KEYS else "header"
    learned = learned or {}
    syns = (synonyms.get(scope) or {}).get(field_key) or []
    sample: dict[str, str] = {}
    for p, v in tree.leaf_items():
        sample.setdefault(p, v)
    if scope == "lines":
        if not line_path:
            return []
        pool: dict[str, str] = {}
        for p, v in sample.items():
            rel = relative_path(p, line_path)
            if rel:
                pool.setdefault(rel, v)
        cands = _score(pool, f, syns, learned, scope)
    else:
        inside = lambda p: bool(line_path) and p.startswith(line_path + "/")  # noqa: E731
        cands = _score({p: v for p, v in sample.items() if not inside(p)}, f, syns, learned, scope)
        if not cands and line_path:
            cands = [Candidate(c.path, c.transforms, round(c.confidence * 0.8, 2),
                               c.reason + " (wartość z pierwszej pozycji)", c.preview)
                     for c in _score({p: v for p, v in sample.items() if inside(p)}, f, syns, learned, scope)]
    cands.sort(key=lambda c: -c.confidence)
    return cands[:limit]


def draft_rules(tree: SourceTree, synonyms: dict, learned: dict | None = None,
                threshold: float = 0.5) -> dict:
    line_path = tree.detect_line_group()
    rules = {"line_path": line_path, "header": {"doc_type": {"constant": "invoice"}}, "lines": {},
             "defaults": {}, "line_defaults": {}}
    for fields, section in ((HEADER_FIELDS, "header"), (LINE_FIELDS, "lines")):
        used: set[str] = set()
        for f in fields:
            if f.key == "doc_type":
                continue
            for c in field_candidates(tree, f.key, line_path, synonyms, learned):
                if c.confidence < threshold:
                    break
                if c.path in used and f.key not in MULTI_USE:
                    continue
                rules[section][f.key] = {"path": c.path, "transforms": c.transforms}
                used.add(c.path)
                break
    return rules


def unit_candidates(alias: str, unit_codes: list[str], synonyms: dict, limit: int = 5) -> list[dict]:
    a = (alias or "").strip().lower()
    table = {str(k).lower(): v for k, v in (synonyms.get("units") or {}).items()}
    found: dict[str, tuple[float, str]] = {}
    if a in table and table[a] in unit_codes:
        found[table[a]] = (0.95, "znany kod jednostki")
    base = a.rstrip(".")
    for code in unit_codes:
        if code in found or not base:
            continue
        r = fuzz.ratio(base, code) / 100
        if code.startswith(base) or base.startswith(code):
            r = max(r, 0.8)
        if r >= 0.5:
            found[code] = (round(r * 0.85, 2), "podobna nazwa")
    out = [{"kind": "unit", "unit": c, "confidence": s, "reason": why} for c, (s, why) in found.items()]
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


def product_candidates(line: dict, products: list[dict], limit: int = 5) -> list[dict]:
    gtin = (line.get("gtin") or "").zfill(14) if line.get("gtin") else None
    name = line.get("name") or ""
    out = []
    for p in products:
        if gtin and p.get("gtin") and p["gtin"].zfill(14) == gtin:
            out.append({"kind": "product", "code": p["code"], "name": p["name"], "confidence": 1.0,
                        "reason": "zgodny GTIN"})
            continue
        r = fuzz.token_set_ratio(name, p.get("name") or "", processor=default_process)
        if name and r >= 50:
            out.append({"kind": "product", "code": p["code"], "name": p["name"],
                        "confidence": round(r / 100 * 0.9, 2), "reason": "podobna nazwa"})
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


def norm_tax_id(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def tax_ids_match(a: str | None, b: str | None) -> bool:
    x, y = norm_tax_id(a), norm_tax_id(b)
    if not x or not y:
        return False
    strip = lambda s: s[2:] if len(s) > 2 and s[:2].isalpha() else s  # noqa: E731
    return x == y or strip(x) == strip(y)


def supplier_candidates(name: str | None, tax_id: str | None, suppliers: list[dict],
                        limit: int = 5) -> list[dict]:
    out = []
    for s in suppliers:
        if tax_id and tax_ids_match(tax_id, s.get("tax_id")):
            out.append({"kind": "use_supplier", "supplier_id": s["id"], "name": s["name"],
                        "confidence": 1.0, "reason": "zgodny NIP/VAT"})
            continue
        if name:
            r = fuzz.token_set_ratio(name, s.get("name") or "", processor=default_process)
            if r >= 70:
                out.append({"kind": "use_supplier", "supplier_id": s["id"], "name": s["name"],
                            "confidence": round(r / 100 * 0.9, 2), "reason": "podobna nazwa"})
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


_QTY_IN_NAME = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|szt)\b", re.IGNORECASE)


def conversion_guess(line_name: str | None, from_unit: str) -> dict:
    guess = {"kind": "conversion", "from_unit": from_unit, "to_unit": "szt", "factor": None, "confidence": 0.3}
    m = None
    for m in _QTY_IN_NAME.finditer(line_name or ""):
        pass
    if m:
        qty = to_decimal(m.group(1))
        unit = m.group(2).lower()
        if unit == "g":
            qty, unit = qty / 1000, "kg"
        elif unit == "ml":
            qty, unit = qty / 1000, "l"
        guess.update(to_unit=unit, factor=format(qty.normalize(), "f"), confidence=0.7)
    return guess
```

Uwaga: `conversion_guess` bierze **ostatnie** dopasowanie „liczba + jednostka” w nazwie (np. „typ 450 25 kg” → 25 kg). Wzorzec wymaga jednostki tuż za liczbą, więc „450” nie pasuje.

- [ ] **Step 5: PASS:** `pytest tests/engine -q`. Jeśli któraś próbka w `test_draft_rules_read_every_sample` daje inne problemy niż oczekiwane, wypisz `rules` (`print(json.dumps(rules, indent=1))`) i popraw **synonimy w YAML**, nie testy. Testy opisują wymagane zachowanie.

- [ ] **Step 6: Commit**
```bash
git add data/synonyms.yaml app/engine/suggest.py tests/engine/test_suggest.py
git commit -m "feat(engine): słownik synonimów i heurystyczne podpowiedzi mapowań

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 10: Modele, storage, DbLookups, usługi szablonów/kluczy/audytu, seed, migracja

**Files:**
- Create: `app/models.py`, `app/services/__init__.py` (pusty), `app/services/storage.py`, `app/services/lookups_db.py`, `app/services/templates.py`, `app/services/apikeys.py`, `app/services/audit.py`, `app/services/seed.py`
- Modify: `app/__init__.py` (import modeli, rejestracja komend CLI `seed`, `reset-demo`, user_loader)
- Create (generowane): `migrations/`
- Test: `tests/test_models_services.py`

**Interfaces:**
- Consumes: `db` (Task 1), `MemoryLookups`-zgodny protokół `Lookups` (Task 6), `norm_alias` (Task 6), `norm_tax_id` (Task 9).
- Produces:
  - Modele: `Supplier(id, name, tax_id, notes, created_at)`, `Template(id, supplier_id, name, fingerprint, paths: list, active_version_id, created_at)` z property `active_version -> TemplateVersion | None` i relacją `versions`, `TemplateVersion(id, template_id, version, rules: dict, author, comment, created_at)`, `Unit(id, code, name, is_base)`, `UnitAlias(id, alias, alias_norm, unit_id, supplier_id)`, `UnitConversion(id, supplier_id, product_id, from_unit_id, to_unit_id, factor: Decimal)`, `Product(id, code, name, gtin, unit_id)`, `ProductMapping(id, supplier_id, supplier_code, supplier_gtin, product_id)`, `Document(id, source, filename, sha256, fmt, supplier_id, template_id, template_version_id, status, doc_type, number, issue_date, result, issues, overrides, draft_rules, error, corrects_document_id, api_key_id, created_at, updated_at)`, `ApiKey(id, name, prefix, key_hash, active, webhook_url, webhook_secret, last_used_at, created_at)`, `User(id, email, password_hash, role)` + `set_password`/`check_password`, `AuditLog(id, user, action, entity, entity_id, payload, created_at)`.
  - Stałe statusów: `STATUS_RECEIVED="received"`, `STATUS_APPROVED="approved"`, `STATUS_NEEDS_REVIEW="needs_review"`, `STATUS_DUPLICATE="duplicate"`, `STATUS_REJECTED="rejected"`, `STATUS_LABELS: dict[str,str]` (PL).
  - `Storage(base_dir)`: `save(data: bytes) -> str` (sha256), `load(sha: str) -> bytes`; `get_storage() -> Storage` (z `current_app.config["STORAGE_DIR"]`).
  - `DbLookups()` implementujący `Lookups` + `unit_codes() -> list[str]`, `products_brief() -> list[dict]`, `suppliers_brief() -> list[dict]`.
  - `templates.py`: `new_version(template, rules, author, comment) -> TemplateVersion`, `create_template(supplier, tree_paths: list[str], fingerprint: str, fmt: str, rules: dict, author: str) -> Template`, `active_rule_sets() -> list[dict]`.
  - `apikeys.py`: `create_key(name: str, plaintext: str | None = None) -> tuple[ApiKey, str]`, `verify_key(plaintext: str) -> ApiKey | None`, `hash_key(plaintext) -> str`.
  - `audit.py`: `audit(action: str, entity: str, entity_id: int | None, payload: dict | None = None, user: str | None = None) -> None` (bez commita).
  - `seed.py`: `BASE_UNITS`, `seed_base() -> None` (jednostki, admin z configu, klucz demo), `seed_demo() -> None` (kartoteka towarów demo), `reset_demo() -> None` (czyści dane i woła oba seedy). Komendy CLI: `flask seed`, `flask reset-demo`.

- [ ] **Step 1: Testy**

`tests/test_models_services.py`:
```python
from decimal import Decimal

from app.extensions import db
from app.models import (ApiKey, AuditLog, Product, ProductMapping, Supplier, Template, Unit, UnitAlias,
                        UnitConversion, User)
from app.services.apikeys import create_key, verify_key
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.seed import reset_demo, seed_base, seed_demo
from app.services.storage import get_storage
from app.services.templates import active_rule_sets, create_template, new_version


def test_storage_roundtrip(app):
    st = get_storage()
    sha = st.save(b"<a/>")
    assert len(sha) == 64 and st.load(sha) == b"<a/>"
    assert st.save(b"<a/>") == sha


def test_seed_base_idempotent(app):
    seed_base()
    seed_base()
    assert Unit.query.filter_by(code="szt").one().is_base
    assert not Unit.query.filter_by(code="karton").one().is_base
    assert User.query.count() == 1 and User.query.one().check_password("haslo123")
    assert verify_key("xp_test_demo_key") is not None


def test_db_lookups(app):
    seed_base()
    seed_demo()
    s = Supplier(name="Alfa", tax_id="PL9990000011")
    db.session.add(s)
    db.session.flush()
    szt = Unit.query.filter_by(code="szt").one()
    karton = Unit.query.filter_by(code="karton").one()
    db.session.add(UnitAlias(alias="pcs", unit_id=szt.id, supplier_id=s.id))
    db.session.add(UnitConversion(supplier_id=s.id, from_unit_id=karton.id, to_unit_id=szt.id, factor=Decimal("12")))
    p = Product.query.filter_by(code="TOW-0003").one()
    db.session.add(ProductMapping(supplier_id=s.id, supplier_code="A-300", product_id=p.id))
    db.session.commit()
    lk = DbLookups()
    assert lk.unit_for_alias("PCS", s.id) == "szt"
    assert lk.unit_for_alias("pcs", None) is None
    assert lk.unit_for_alias("Kg", None) == "kg"
    assert lk.is_base_unit("szt") and not lk.is_base_unit("karton")
    assert lk.conversion(s.id, None, "karton") == ("szt", Decimal("12"))
    assert lk.conversion(None, None, "karton") is None
    assert lk.product_for(s.id, "A-300", None) == "TOW-0003"
    assert lk.product_for(None, None, "05909999000013") == "TOW-0001"
    assert "karton" in lk.unit_codes()
    assert {"code": "TOW-0001", "name": "Posypka czekoladowa 1 kg", "gtin": "5909999000013"} in lk.products_brief()


def test_templates_versions(app):
    s = Supplier(name="Alfa", tax_id="PL1")
    db.session.add(s)
    db.session.flush()
    t = create_template(s, ["A/B"], "abc", "xml", {"line_path": "A"}, "admin")
    assert t.active_version.version == 1
    v2 = new_version(t, {"line_path": "B"}, "admin", "zmiana")
    db.session.commit()
    assert v2.version == 2 and t.active_version.rules == {"line_path": "B"}
    assert active_rule_sets() == [{"line_path": "B"}]


def test_api_keys_and_audit(app):
    key, plain = create_key("ERP")
    db.session.commit()
    assert plain.startswith("xp_") and key.prefix == plain[:10]
    assert verify_key(plain).id == key.id
    assert verify_key("xp_nope") is None
    key.active = False
    db.session.commit()
    assert verify_key(plain) is None
    audit("test", "api_key", key.id, {"a": 1}, user="admin")
    db.session.commit()
    assert AuditLog.query.one().payload == {"a": 1}


def test_reset_demo_clears_data(app):
    seed_base()
    db.session.add(Supplier(name="X"))
    db.session.commit()
    reset_demo()
    assert Supplier.query.count() == 0
    assert Product.query.filter_by(code="TOW-0001").count() == 1
    assert ApiKey.query.count() == 1
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: `app/models.py`**

```python
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

STATUS_RECEIVED = "received"
STATUS_APPROVED = "approved"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_DUPLICATE = "duplicate"
STATUS_REJECTED = "rejected"
STATUS_LABELS = {
    STATUS_RECEIVED: "Przyjęta",
    STATUS_APPROVED: "Zatwierdzona",
    STATUS_NEEDS_REVIEW: "Do wyjaśnienia",
    STATUS_DUPLICATE: "Duplikat",
    STATUS_REJECTED: "Odrzucona",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    tax_id = db.Column(db.String(64), index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)


class Template(db.Model):
    __tablename__ = "templates"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), index=True)
    name = db.Column(db.String(255), nullable=False)
    fingerprint = db.Column(db.String(32), index=True)
    paths = db.Column(db.JSON, default=list)
    active_version_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utcnow)
    supplier = db.relationship("Supplier", backref="templates")
    versions = db.relationship("TemplateVersion", backref="template", order_by="TemplateVersion.version",
                               cascade="all, delete-orphan")

    @property
    def active_version(self):
        if self.active_version_id is None:
            return None
        return db.session.get(TemplateVersion, self.active_version_id)


class TemplateVersion(db.Model):
    __tablename__ = "template_versions"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    rules = db.Column(db.JSON, nullable=False)
    author = db.Column(db.String(255))
    comment = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=utcnow)


class Unit(db.Model):
    __tablename__ = "units"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_base = db.Column(db.Boolean, default=True, nullable=False)


class UnitAlias(db.Model):
    __tablename__ = "unit_aliases"
    __table_args__ = (db.UniqueConstraint("alias_norm", "supplier_id", name="uq_alias_supplier"),)
    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(64), nullable=False)
    alias_norm = db.Column(db.String(64), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    unit = db.relationship("Unit")
    supplier = db.relationship("Supplier")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.alias_norm = (self.alias or "").strip().lower()


class UnitConversion(db.Model):
    __tablename__ = "unit_conversions"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    from_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    to_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    factor = db.Column(db.Numeric(18, 6), nullable=False)
    supplier = db.relationship("Supplier")
    product = db.relationship("Product")
    from_unit = db.relationship("Unit", foreign_keys=[from_unit_id])
    to_unit = db.relationship("Unit", foreign_keys=[to_unit_id])


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    gtin = db.Column(db.String(14), index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"))
    unit = db.relationship("Unit")


class ProductMapping(db.Model):
    __tablename__ = "product_mappings"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_code = db.Column(db.String(64))
    supplier_gtin = db.Column(db.String(14))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    supplier = db.relationship("Supplier")
    product = db.relationship("Product")


class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(16), nullable=False, default="upload")
    filename = db.Column(db.String(255))
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    fmt = db.Column(db.String(8))
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"))
    template_version_id = db.Column(db.Integer, db.ForeignKey("template_versions.id"))
    status = db.Column(db.String(16), nullable=False, default=STATUS_RECEIVED, index=True)
    doc_type = db.Column(db.String(16))
    number = db.Column(db.String(128), index=True)
    issue_date = db.Column(db.String(10))
    result = db.Column(db.JSON)
    issues = db.Column(db.JSON, default=list)
    overrides = db.Column(db.JSON, default=dict)
    draft_rules = db.Column(db.JSON)
    error = db.Column(db.Text)
    corrects_document_id = db.Column(db.Integer, db.ForeignKey("documents.id"))
    api_key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    supplier = db.relationship("Supplier")
    template = db.relationship("Template")
    template_version = db.relationship("TemplateVersion")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class ApiKey(db.Model):
    __tablename__ = "api_keys"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    prefix = db.Column(db.String(12), nullable=False)
    key_hash = db.Column(db.String(64), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    webhook_url = db.Column(db.String(500))
    webhook_secret = db.Column(db.String(128))
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="admin")

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(255))
    action = db.Column(db.String(64), nullable=False)
    entity = db.Column(db.String(64), nullable=False)
    entity_id = db.Column(db.Integer)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
```

Uwaga: `UnitAlias.__init__` liczy `alias_norm`. Przy **edycji** aliasu w CRUD (Task 15) trzeba też ustawić `alias_norm`.

- [ ] **Step 4: Usługi**

`app/services/storage.py`:
```python
import hashlib
from pathlib import Path

from flask import current_app


class Storage:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir) / "raw"
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.base / sha
        if not path.exists():
            path.write_bytes(data)
        return sha

    def load(self, sha: str) -> bytes:
        if not sha.isalnum():
            raise ValueError("Niepoprawny identyfikator pliku.")
        return (self.base / sha).read_bytes()


def get_storage() -> Storage:
    return Storage(current_app.config["STORAGE_DIR"])
```

`app/services/lookups_db.py`:
```python
from decimal import Decimal

from app.engine.lookups import norm_alias
from app.extensions import db
from app.models import Product, ProductMapping, Supplier, Unit, UnitAlias, UnitConversion


class DbLookups:
    """Implementacja protokołu Lookups na bazie. Cache na czas życia obiektu (jedno przetworzenie)."""

    def __init__(self):
        self._units = {u.code: u for u in Unit.query.all()}
        self._units_by_id = {u.id: u for u in self._units.values()}

    def unit_codes(self) -> list[str]:
        return sorted(self._units)

    def unit_for_alias(self, alias, supplier_id):
        a = norm_alias(alias)
        if a in self._units:
            return a
        q = UnitAlias.query.filter_by(alias_norm=a)
        row = q.filter_by(supplier_id=supplier_id).first() if supplier_id else None
        row = row or q.filter(UnitAlias.supplier_id.is_(None)).first()
        return self._units_by_id[row.unit_id].code if row else None

    def is_base_unit(self, code):
        u = self._units.get(code)
        return True if u is None else bool(u.is_base)

    def conversion(self, supplier_id, product_code, from_unit):
        u = self._units.get(from_unit)
        if u is None:
            return None
        product = Product.query.filter_by(code=product_code).first() if product_code else None
        pid = product.id if product else None
        for sid, prid in ((supplier_id, pid), (supplier_id, None), (None, pid), (None, None)):
            q = UnitConversion.query.filter_by(from_unit_id=u.id)
            q = q.filter(UnitConversion.supplier_id.is_(None)) if sid is None else q.filter_by(supplier_id=sid)
            q = q.filter(UnitConversion.product_id.is_(None)) if prid is None else q.filter_by(product_id=prid)
            row = q.first()
            if row:
                return self._units_by_id[row.to_unit_id].code, Decimal(row.factor)
        return None

    def product_for(self, supplier_id, supplier_code, gtin):
        if supplier_id:
            q = ProductMapping.query.filter_by(supplier_id=supplier_id)
            row = q.filter_by(supplier_code=supplier_code).first() if supplier_code else None
            if row is None and gtin:
                row = q.filter_by(supplier_gtin=gtin.zfill(14)).first()
            if row:
                return db.session.get(Product, row.product_id).code
        if gtin:
            g14 = gtin.zfill(14)
            for p in Product.query.filter(Product.gtin.isnot(None)).all():
                if p.gtin.zfill(14) == g14:
                    return p.code
        return None

    def products_brief(self) -> list[dict]:
        return [{"code": p.code, "name": p.name, "gtin": p.gtin} for p in Product.query.order_by(Product.code)]

    def suppliers_brief(self) -> list[dict]:
        return [{"id": s.id, "name": s.name, "tax_id": s.tax_id} for s in Supplier.query.order_by(Supplier.name)]
```
`app/services/templates.py`:
```python
from app.extensions import db
from app.models import Template, TemplateVersion


def new_version(template: Template, rules: dict, author: str | None, comment: str | None) -> TemplateVersion:
    last = max((v.version for v in template.versions), default=0)
    tv = TemplateVersion(version=last + 1, rules=dict(rules), author=author, comment=comment)
    template.versions.append(tv)  # przez relację, żeby kolekcja w sesji była aktualna
    db.session.flush()
    template.active_version_id = tv.id
    return tv


def create_template(supplier, tree_paths: list[str], fingerprint: str, fmt: str, rules: dict,
                    author: str | None) -> Template:
    name = f"{supplier.name} — {fmt.upper()}" if supplier else f"Format {fingerprint}"
    t = Template(supplier_id=supplier.id if supplier else None, name=name, fingerprint=fingerprint,
                 paths=sorted(tree_paths))
    db.session.add(t)
    db.session.flush()
    new_version(t, rules, author, "Pierwsza wersja (z negocjacji)")
    return t


def active_rule_sets() -> list[dict]:
    out = []
    for t in Template.query.order_by(Template.id):
        v = t.active_version
        if v:
            out.append(v.rules)
    return out
```

`app/services/apikeys.py`:
```python
import hashlib
import secrets

from app.extensions import db
from app.models import ApiKey, utcnow


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_key(name: str, plaintext: str | None = None) -> tuple[ApiKey, str]:
    plaintext = plaintext or "xp_" + secrets.token_urlsafe(32)
    key = ApiKey(name=name, prefix=plaintext[:10], key_hash=hash_key(plaintext), active=True)
    db.session.add(key)
    db.session.flush()
    return key, plaintext


def verify_key(plaintext: str | None) -> ApiKey | None:
    if not plaintext:
        return None
    key = ApiKey.query.filter_by(key_hash=hash_key(plaintext), active=True).first()
    if key:
        key.last_used_at = utcnow()
    return key
```

`app/services/audit.py`:
```python
from flask import has_request_context
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def audit(action: str, entity: str, entity_id: int | None, payload: dict | None = None,
          user: str | None = None) -> None:
    if user is None and has_request_context() and getattr(current_user, "is_authenticated", False):
        user = current_user.email
    db.session.add(AuditLog(user=user or "system", action=action, entity=entity, entity_id=entity_id,
                            payload=payload or {}))
```

`app/services/seed.py`:
```python
from flask import current_app

from app.extensions import db
from app.models import (ApiKey, AuditLog, Document, Product, ProductMapping, Supplier, Template,
                        TemplateVersion, Unit, UnitAlias, UnitConversion, User)
from app.services.apikeys import create_key, hash_key

BASE_UNITS = [
    ("szt", "sztuka", True), ("kg", "kilogram", True), ("l", "litr", True), ("m", "metr", True),
    ("karton", "karton", False), ("worek", "worek", False), ("opak", "opakowanie", False),
]
GLOBAL_ALIASES = [("szt.", "szt"), ("sztuk", "szt"), ("kilogram", "kg"), ("litr", "l")]
DEMO_PRODUCTS = [
    ("TOW-0001", "Posypka czekoladowa 1 kg", "5909999000013", "szt"),
    ("TOW-0002", "Mak niebieski 500 g", "5909999000020", "szt"),
    ("TOW-0003", "Masa marcepanowa 5kg", None, "szt"),
    ("TOW-0004", "Mąka pszenna typ 450", "5909999000044", "kg"),
    ("TOW-0005", "Mąka żytnia typ 750", None, "kg"),
    ("TOW-0006", "Pudełko na tort 30x30 cm", "5909999000068", "szt"),
    ("TOW-0007", "Podkład pod tort 28cm", None, "szt"),
    ("TOW-0008", "Masło extra 82% 1kg", "5909999000082", "szt"),
    ("TOW-0009", "Śmietanka 30% 1l", "5909999000099", "szt"),
    ("TOW-0010", "Wanilia burbon (laski)", None, "szt"),
    ("TOW-0011", "Aromat rumowy 100ml", "4009999000028", "szt"),
]


def seed_base() -> None:
    units = {u.code: u for u in Unit.query.all()}
    for code, name, is_base in BASE_UNITS:
        if code not in units:
            units[code] = Unit(code=code, name=name, is_base=is_base)
            db.session.add(units[code])
    db.session.flush()
    for alias, code in GLOBAL_ALIASES:
        if not UnitAlias.query.filter_by(alias_norm=alias, supplier_id=None).first():
            db.session.add(UnitAlias(alias=alias, unit_id=units[code].id, supplier_id=None))
    cfg = current_app.config
    admin_email = (cfg.get("ADMIN_EMAIL") or "").strip().lower()
    if cfg.get("ADMIN_PASSWORD") and admin_email and not User.query.filter_by(email=admin_email).first():
        u = User(email=admin_email, role="admin")
        u.set_password(cfg["ADMIN_PASSWORD"])
        db.session.add(u)
    demo_key = cfg.get("DEMO_API_KEY")
    if cfg.get("DEMO_MODE") and demo_key and not ApiKey.query.filter_by(key_hash=hash_key(demo_key)).first():
        create_key("Klucz demo", demo_key)
    db.session.commit()


def seed_demo() -> None:
    units = {u.code: u for u in Unit.query.all()}
    for code, name, gtin, unit in DEMO_PRODUCTS:
        if not Product.query.filter_by(code=code).first():
            db.session.add(Product(code=code, name=name, gtin=gtin, unit_id=units[unit].id))
    db.session.commit()


def reset_demo() -> None:
    db.session.query(Document).update({Document.template_version_id: None, Document.template_id: None,
                                       Document.corrects_document_id: None})
    for model in (Document, ProductMapping, UnitConversion, TemplateVersion, Template, Product, AuditLog):
        db.session.query(model).delete()
    db.session.query(UnitAlias).filter(UnitAlias.supplier_id.isnot(None)).delete()
    db.session.query(Supplier).delete()
    db.session.commit()
    seed_base()
    seed_demo()
```
Uwaga: `TOW-0004`/`TOW-0001`/… mają GTIN, więc pozycje dopasują się automatycznie. `TOW-0003`, `TOW-0005`, `TOW-0007`, `TOW-0010` nie mają GTIN-u: demo pokaże na nich podpowiedź po nazwie.

- [ ] **Step 5: Podłącz modele i CLI w `app/__init__.py`**

Dodaj na końcu `create_app` przed `return app`:
```python
    from . import models  # noqa: F401  (rejestracja modeli dla Alembic)
    from .services.seed import reset_demo, seed_base, seed_demo

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @app.cli.command("seed")
    def seed_cmd():
        """Jednostki, konto admin, klucz demo (+ kartoteka demo w DEMO_MODE)."""
        seed_base()
        if app.config["DEMO_MODE"]:
            seed_demo()
        print("Seed OK")

    @app.cli.command("reset-demo")
    def reset_demo_cmd():
        """Czyści dane i przywraca stan demo."""
        reset_demo()
        print("Demo zresetowane")
```

- [ ] **Step 6: PASS:** `pytest tests/test_models_services.py -q`

- [ ] **Step 7: Migracja początkowa**

```bash
export FLASK_APP=app:create_app DATABASE_URL=sqlite:///migr-tmp.db
flask db init
flask db migrate -m "schemat początkowy"
rm -f migr-tmp.db instance/migr-tmp.db
```
Przejrzyj `migrations/versions/*_schemat_początkowy.py`: wszystkie tabele obecne, kolumny JSON jako `sa.JSON()`. Sprawdzenie na MariaDB nastąpi w Task 18.

- [ ] **Step 8: Commit**
```bash
git add app migrations tests/test_models_services.py
pytest tests/test_no_private_data.py -q
git commit -m "feat(db): modele, storage, DbLookups, wersje szablonów, klucze API, seed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 11: Pipeline — ingest, identyfikacja dostawcy, duplikaty, podpowiedzi

**Files:**
- Create: `app/services/pipeline.py`
- Modify: `tests/conftest.py` (fixture `seeded`, helper `sample_bytes`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `read_document`, `ReaderError` (Task 3), `jaccard` (Task 3), `apply_template` (Task 7), `validate_invoice` (Task 8), `Issue`, `BLOCKING`, `has_blocking` (Task 6), `FIELDS_BY_KEY`, `field_candidates`, `draft_rules`, `learned_pairs`, `load_synonyms`, `suffix_match`, `tax_ids_match`, `unit_candidates`, `product_candidates`, `supplier_candidates`, `conversion_guess` (Task 9), modele i usługi z Task 10.
- Produces:
  - `FINGERPRINT_MIN = 0.6`
  - `DocumentTooLarge(ValueError)`
  - `ingest(data: bytes, filename: str | None, source: str = "upload", api_key_id: int | None = None) -> Document` (commit)
  - `process(doc: Document) -> Document` (bez commita)
  - `load_tree(doc) -> SourceTree`
  - `best_template_for(supplier_id: int | None, paths: set[str]) -> Template | None`
  - `identify(tree, doc, synonyms) -> Identification(supplier, template, clone_candidate, extracted_tax_id)`
  - `current_rules(doc) -> dict` (deepcopy reguł aktywnych: wersja szablonu albo `draft_rules`)
  - `next_product_code() -> str`
  - Struktury podpowiedzi w `issue["suggestions"]` (używa ich UI i negocjacja):
    - `{"kind":"path", path, transforms, confidence, reason, preview}`
    - `{"kind":"default", value, confidence, reason}`
    - `{"kind":"line_path", path, confidence, reason}`
    - `{"kind":"create_supplier", name, tax_id, confidence, reason}`
    - `{"kind":"use_supplier", supplier_id, name, confidence, reason}`
    - `{"kind":"clone_template", template_id, name, confidence, reason}` (informacyjnie)
    - `{"kind":"unit", unit, confidence, reason}`
    - `{"kind":"product", code, name, confidence, reason}`
    - `{"kind":"create_product", code, name, unit, confidence, reason}`
    - `{"kind":"conversion", from_unit, to_unit, factor, confidence}`

- [ ] **Step 1: Fixture'y**

Dopisz do `tests/conftest.py`:
```python
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


@pytest.fixture
def seeded(app):
    from app.services.seed import seed_base, seed_demo
    seed_base()
    seed_demo()
    return app
```

- [ ] **Step 2: Testy**

`tests/test_pipeline.py`:
```python
from app.extensions import db
from app.models import Supplier
from app.services.pipeline import ingest, load_tree
from app.services.templates import create_template
from tests.conftest import sample_bytes


def issue(doc, code):
    return next(i for i in doc.issues if i["code"] == code)


def test_alfa_first_time_needs_review(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    assert d.status == "needs_review" and d.fmt == "xml"
    codes = [i["code"] for i in d.issues]
    assert codes[0] == "unknown_supplier"
    assert {"unmapped_field", "unknown_unit", "unmapped_product"} <= set(codes)
    sup = issue(d, "unknown_supplier")["suggestions"][0]
    assert sup == {"kind": "create_supplier", "name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "PL9990000011",
                   "confidence": 0.9, "reason": "dane odczytane z faktury"}
    assert issue(d, "unknown_unit")["suggestions"][0]["unit"] == "szt"
    prod = issue(d, "unmapped_product")
    assert prod["line_no"] == 3 and prod["suggestions"][0]["code"] == "TOW-0003"
    cur = issue(d, "unmapped_field")
    assert cur["field"] == "currency"
    assert {"kind": "default", "value": "PLN", "confidence": 0.5, "reason": "typowa wartość"} in cur["suggestions"]
    assert d.result["lines"][0]["product_index"] == "TOW-0001"
    assert d.draft_rules["line_path"] == "Document/Faktura/Pozycje/Pozycja"


def test_unreadable_file_rejected(seeded):
    d = ingest(b"<a><b></a>", "zly.xml")
    assert d.status == "rejected"
    assert d.issues[0]["code"] == "unreadable" and "XML" in d.issues[0]["message"]


def test_duplicate_same_file(seeded):
    ingest(sample_bytes("alfa-1.xml"), "a.xml")
    d2 = ingest(sample_bytes("alfa-1.xml"), "a-kopia.xml")
    assert d2.status == "duplicate" and d2.issues[0]["code"] == "duplicate"


def test_duplicate_same_supplier_number(seeded):
    db.session.add(Supplier(name="Hurtownia Alfa", tax_id="PL9990000011"))
    db.session.commit()
    d1 = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    assert d1.supplier_id is not None
    d2 = ingest(sample_bytes("alfa-1.xml") + b"\n<!-- inna kopia -->\n", "b.xml")
    assert d2.status == "duplicate"


def test_same_format_new_supplier_not_misattributed(seeded):
    s = Supplier(name="Hurtownia Alfa", tax_id="PL9990000011")
    db.session.add(s)
    db.session.flush()
    d1 = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    tree = load_tree(d1)
    tpl = create_template(s, tree.leaf_paths(), tree.fingerprint(), "xml", d1.draft_rules, "admin")
    db.session.commit()
    omega = (sample_bytes("alfa-2.xml")
             .replace(b"PL9990000011", b"PL9990000088")
             .replace(b"Hurtownia Alfa Sp. z o.o.", b"Hurtownia Omega"))
    d2 = ingest(omega, "omega.xml")
    assert d2.supplier_id is None
    assert d2.issues[0]["code"] == "unknown_supplier"
    kinds = {x["kind"]: x for x in d2.issues[0]["suggestions"]}
    assert kinds["create_supplier"]["name"] == "Hurtownia Omega"
    assert kinds["clone_template"]["template_id"] == tpl.id
    assert d2.draft_rules == tpl.active_version.rules


def test_known_supplier_template_is_used(seeded):
    s = Supplier(name="Hurtownia Alfa", tax_id="9990000011")
    db.session.add(s)
    db.session.flush()
    d1 = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    tree = load_tree(d1)
    rules = {**d1.draft_rules, "defaults": {"currency": "GBP"}}
    tpl = create_template(s, tree.leaf_paths(), tree.fingerprint(), "xml", rules, "admin")
    db.session.commit()
    d2 = ingest(sample_bytes("alfa-2.xml"), "b.xml")
    assert d2.template_id == tpl.id and d2.template_version_id == tpl.active_version_id
    assert d2.result["currency"] == "GBP"
    assert [i["code"] for i in d2.issues] == ["unknown_unit"]
```

- [ ] **Step 3: FAIL.**

- [ ] **Step 4: Implementacja `app/services/pipeline.py`**

```python
"""Przetwarzanie dokumentu: odczyt → identyfikacja → szablon → walidacja → status → podpowiedzi."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from flask import current_app

from app.engine.canonical import get_path
from app.engine.issues import BLOCKING, Issue, has_blocking
from app.engine.suggest import (FIELDS_BY_KEY, conversion_guess, draft_rules, field_candidates, learned_pairs,
                                load_synonyms, product_candidates, suffix_match, supplier_candidates,
                                tax_ids_match, unit_candidates)
from app.engine.template import apply_template
from app.engine.tree import SourceTree, jaccard
from app.engine.validate import validate_invoice
from app.extensions import db
from app.ingest import ReaderError, read_document
from app.models import (STATUS_APPROVED, STATUS_DUPLICATE, STATUS_NEEDS_REVIEW, STATUS_RECEIVED,
                        STATUS_REJECTED, Document, Product, Supplier, Template)
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.storage import get_storage
from app.services.templates import active_rule_sets

FINGERPRINT_MIN = 0.6
DEFAULT_VALUES = {"currency": ["PLN", "GBP", "EUR"], "payment_method": ["przelew", "gotówka", "karta"]}


class DocumentTooLarge(ValueError):
    pass


@dataclass
class Identification:
    supplier: Supplier | None = None
    template: Template | None = None
    clone_candidate: Template | None = None
    extracted_tax_id: str | None = None


def load_tree(doc: Document) -> SourceTree:
    return read_document(get_storage().load(doc.sha256), doc.filename)


def best_template_for(supplier_id: int | None, paths: set[str]) -> Template | None:
    q = Template.query
    q = q.filter_by(supplier_id=supplier_id) if supplier_id else q
    best, score = None, 0.0
    for t in q.all():
        j = jaccard(paths, set(t.paths or []))
        if j > score:
            best, score = t, j
    return best if score >= FINGERPRINT_MIN else None


def _tax_paths(tree: SourceTree, synonyms: dict) -> list[str]:
    paths = []
    for rules in active_rule_sets():
        p = (((rules.get("header") or {}).get("supplier.tax_id")) or {}).get("path")
        if p:
            paths.append(p)
    syns = synonyms["header"]["supplier.tax_id"]
    paths += [p for p in tree.leaf_paths() if any(suffix_match(p, s) for s in syns)]
    return paths


def identify(tree: SourceTree, doc: Document, synonyms: dict) -> Identification:
    ident = Identification()
    if doc.supplier_id:
        ident.supplier = db.session.get(Supplier, doc.supplier_id)
    else:
        suppliers = Supplier.query.filter(Supplier.tax_id.isnot(None)).all()
        for p in _tax_paths(tree, synonyms):
            val = tree.first(p)
            if not val:
                continue
            ident.extracted_tax_id = ident.extracted_tax_id or val
            ident.supplier = next((s for s in suppliers if tax_ids_match(val, s.tax_id)), None)
            if ident.supplier:
                break
    paths = tree.path_set()
    if ident.supplier:
        ident.template = best_template_for(ident.supplier.id, paths)
    else:
        ident.clone_candidate = best_template_for(None, paths)
    return ident


def current_rules(doc: Document) -> dict:
    if doc.template_id:
        tpl = db.session.get(Template, doc.template_id)
        if tpl and tpl.active_version:
            return copy.deepcopy(tpl.active_version.rules)
    return copy.deepcopy(doc.draft_rules or {})


def next_product_code() -> str:
    n = Product.query.count() + 1
    while Product.query.filter_by(code=f"TOW-{n:04d}").first():
        n += 1
    return f"TOW-{n:04d}"


def _find_duplicate(doc: Document, invoice: dict) -> Document | None:
    q = Document.query.filter(Document.id != doc.id,
                              Document.status.in_([STATUS_APPROVED, STATUS_NEEDS_REVIEW]))
    same = q.filter(Document.sha256 == doc.sha256).order_by(Document.id).first()
    if same:
        return same
    if doc.supplier_id and invoice.get("number"):
        return q.filter(Document.supplier_id == doc.supplier_id,
                        Document.number == invoice["number"]).order_by(Document.id).first()
    return None


def _enrich(issues: list[Issue], tree: SourceTree, rules: dict, inv: dict, synonyms: dict,
            ident: Identification, lookups: DbLookups) -> None:
    learned = learned_pairs(active_rule_sets())
    line_path = rules.get("line_path")
    products = None
    for issue in issues:
        code = issue.code
        if code == "unknown_supplier":
            name, tax = get_path(inv, "supplier.name"), get_path(inv, "supplier.tax_id") or ident.extracted_tax_id
            sug = []
            if name or tax:
                sug.append({"kind": "create_supplier", "name": name or tax, "tax_id": tax, "confidence": 0.9,
                            "reason": "dane odczytane z faktury"})
            sug += supplier_candidates(name, tax, lookups.suppliers_brief())
            if ident.clone_candidate:
                sug.append({"kind": "clone_template", "template_id": ident.clone_candidate.id,
                            "name": ident.clone_candidate.name, "confidence": 0.8,
                            "reason": "zgodna struktura pliku — reguły zostaną skopiowane"})
            issue.suggestions = sug
        elif code in ("unmapped_field", "transform_error", "invalid_value") and issue.field:
            if issue.field == "line_path":
                issue.suggestions = [{"kind": "line_path", "path": p, "confidence": 0.5,
                                      "reason": "element z elementami podrzędnymi"} for p in tree.group_paths()[:15]]
            elif issue.field in FIELDS_BY_KEY:
                cands = [c.to_dict() for c in field_candidates(tree, issue.field, line_path, synonyms, learned)]
                issue.suggestions = cands + [{"kind": "default", "value": v, "confidence": 0.5,
                                              "reason": "typowa wartość"} for v in DEFAULT_VALUES.get(issue.field, [])]
        elif code == "unknown_unit":
            issue.suggestions = unit_candidates(issue.source_value or "", lookups.unit_codes(), synonyms)
        elif code == "unmapped_product" and issue.line_no:
            line = inv["lines"][issue.line_no - 1]
            products = products if products is not None else lookups.products_brief()
            issue.suggestions = product_candidates(line, products) + [{
                "kind": "create_product", "code": next_product_code(), "name": line.get("name"),
                "unit": line.get("unit"), "confidence": 0.3, "reason": "nowy towar w kartotece"}]
        elif code == "missing_conversion" and issue.line_no:
            line = inv["lines"][issue.line_no - 1]
            issue.suggestions = [conversion_guess(line.get("name"), issue.source_value or "")]


def process(doc: Document) -> Document:
    synonyms = load_synonyms()
    try:
        tree = load_tree(doc)
    except ReaderError as exc:
        doc.status, doc.error, doc.result = STATUS_REJECTED, str(exc), None
        doc.issues = [Issue("unreadable", BLOCKING, str(exc)).to_dict()]
        return doc
    doc.fmt, doc.error = tree.fmt, None
    ident = identify(tree, doc, synonyms)
    version = ident.template.active_version if ident.template else None
    if version:
        rules = version.rules
        doc.template_id, doc.template_version_id, doc.draft_rules = ident.template.id, version.id, None
    else:
        doc.template_id = doc.template_version_id = None
        if not doc.draft_rules:
            base = ident.clone_candidate.active_version if ident.clone_candidate else None
            doc.draft_rules = (copy.deepcopy(base.rules) if base
                               else draft_rules(tree, synonyms, learned_pairs(active_rule_sets())))
        rules = doc.draft_rules
    if ident.supplier:
        doc.supplier_id = ident.supplier.id
    lookups = DbLookups()
    result = apply_template(tree, rules, lookups, doc.supplier_id, doc.overrides or {})
    inv = result.invoice
    issues = list(result.issues) + validate_invoice(inv)
    if ident.supplier is None:
        issues.insert(0, Issue("unknown_supplier", BLOCKING,
                               "Nie rozpoznano dostawcy — utwórz nowego z danych faktury albo wskaż istniejącego.",
                               field="supplier",
                               source_value=" / ".join(x for x in (get_path(inv, "supplier.name"),
                                                                   get_path(inv, "supplier.tax_id")) if x) or None))
    dup = None if (doc.overrides or {}).get("allow_duplicate") else _find_duplicate(doc, inv)
    if dup:
        issues.insert(0, Issue("duplicate", BLOCKING,
                               f"Ta faktura była już przetworzona (dokument #{dup.id}).", source_value=str(dup.id)))
    _enrich(issues, tree, rules, inv, synonyms, ident, lookups)
    doc.result = inv
    doc.issues = [i.to_dict() for i in issues]
    doc.number, doc.issue_date, doc.doc_type = inv.get("number"), inv.get("issue_date"), inv.get("doc_type")
    doc.status = STATUS_DUPLICATE if dup else (STATUS_NEEDS_REVIEW if has_blocking(issues) else STATUS_APPROVED)
    return doc


def ingest(data: bytes, filename: str | None, source: str = "upload", api_key_id: int | None = None) -> Document:
    limit = current_app.config["MAX_DOCUMENT_BYTES"]
    if len(data) > limit:
        raise DocumentTooLarge(f"Plik przekracza limit {limit // (1024 * 1024)} MB.")
    sha = get_storage().save(data)
    doc = Document(source=source, filename=(filename or "dokument")[:255], sha256=sha, status=STATUS_RECEIVED,
                   overrides={}, issues=[], api_key_id=api_key_id)
    db.session.add(doc)
    db.session.flush()
    process(doc)
    audit("ingest", "document", doc.id, {"status": doc.status, "source": source, "filename": doc.filename})
    db.session.commit()
    return doc
```

- [ ] **Step 5: PASS:** `pytest tests/test_pipeline.py -q`

W `test_known_supplier_template_is_used` pozostaje tylko `unknown_unit`: `pcs` nie ma jeszcze aliasu. Pozycje 1–2 alfa-2 dopasują się po GTIN.

- [ ] **Step 6: Commit**
```bash
git add app/services/pipeline.py tests/conftest.py tests/test_pipeline.py
pytest tests/test_no_private_data.py -q
git commit -m "feat(pipeline): ingest, identyfikacja dostawcy, duplikaty, podpowiedzi do problemów

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---

### Task 12: Negocjacja i test akceptacyjny „uczenia”

**Files:**
- Create: `app/services/negotiation.py`
- Test: `tests/test_negotiation.py`, `tests/test_learning.py`

**Interfaces:**
- Consumes: `process`, `load_tree`, `current_rules`, `best_template_for` (Task 11), `create_template`, `new_version` (Task 10), `audit` (Task 10), `relative_path` (Task 3), `FIELD_LABELS`, `LINE_KEYS` (Task 6), `FIELDS_BY_KEY` (Task 9), `to_decimal` (Task 5), `norm_alias` (Task 6).
- Produces: `NegotiationError(ValueError)`; `ACTIONS: dict[str, Callable]`; `resolve(doc: Document, action: str, data: dict, remember: bool = True, user: str | None = None) -> Document` (commit). Akcje i ich `data`:

| akcja | data | remember=True | remember=False |
|---|---|---|---|
| `create_supplier` | `name`, `tax_id?` | zawsze: nowy dostawca + szablon v1 z `draft_rules` | — |
| `use_supplier` | `supplier_id` | zawsze: przypisanie; szablon v1, jeśli dostawca nie ma pasującego | — |
| `map_field` | `field`, `path?`+`transforms?` albo `value?` | reguła/wartość domyślna → nowa wersja szablonu (lub `draft_rules`) | `value` → `overrides.fields` (tylko pola nagłówka) |
| `map_unit` | `alias`, `unit` | `UnitAlias` dla dostawcy | `overrides.units` |
| `add_conversion` | `from_unit`, `to_unit`, `factor`, `scope` (`supplier`/`product`), `line_no?` | zawsze: `UnitConversion` | — |
| `map_product` | `line_no`, `product_code` | `ProductMapping` (kod + GTIN dostawcy) | `overrides.products` |
| `create_product` | `line_no`, `code`, `name`, `unit` | `Product` + `ProductMapping` | `Product` + `overrides.products` |
| `allow_duplicate` | — | `overrides.allow_duplicate = True` | jw. |
| `reject` | — | status `rejected` (bez przetwarzania) | jw. |

  Akcje zapamiętujące dane per dostawca (`map_unit`, `add_conversion`, `map_product`, `create_product`) przy `remember=True` wymagają rozpoznanego dostawcy. W przeciwnym razie zgłaszają `NegotiationError("Najpierw rozpoznaj dostawcę — to pierwszy problem na liście.")`.

- [ ] **Step 1: Testy jednostkowe akcji**

`tests/test_negotiation.py`:
```python
import pytest

from app.models import Product, ProductMapping, Supplier, UnitAlias
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def codes(doc):
    return [i["code"] for i in doc.issues]


def test_create_supplier_creates_template(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "PL9990000011"}, True, "admin")
    assert d.supplier_id and d.template_id and d.draft_rules is None
    assert "unknown_supplier" not in codes(d)
    assert Supplier.query.one().tax_id == "PL9990000011"


def test_remember_requires_supplier(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    with pytest.raises(NegotiationError, match="rozpoznaj dostawcę"):
        resolve(d, "map_unit", {"alias": "pcs", "unit": "szt"}, True, "admin")


def test_one_off_unit_override_does_not_create_alias(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "map_unit", {"alias": "pcs", "unit": "szt"}, False, "admin")
    assert "unknown_unit" not in codes(d)
    assert UnitAlias.query.filter_by(alias_norm="pcs").count() == 0


def test_map_field_default_creates_new_version(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    resolve(d, "map_field", {"field": "currency", "value": "GBP"}, True, "admin")
    assert d.template.active_version.version == 2
    assert d.template.active_version.rules["defaults"]["currency"] == "GBP"
    assert d.result["currency"] == "GBP"


def test_map_field_line_path_absolute_converted_to_relative(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "map_field", {"field": "batch", "path": "Document/Faktura/Pozycje/Pozycja/TowarKod"}, True, "admin")
    assert d.draft_rules["lines"]["batch"] == {"path": "TowarKod", "transforms": []}


def test_map_field_one_off_rejected_for_line_fields(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    with pytest.raises(NegotiationError):
        resolve(d, "map_field", {"field": "qty", "value": "1"}, False, "admin")


def test_create_product_and_mapping(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    resolve(d, "create_product", {"line_no": 3, "code": "TOW-0999", "name": "Masa marcepanowa 5 kg", "unit": "szt"},
            True, "admin")
    assert Product.query.filter_by(code="TOW-0999").one().gtin == "05909999000037"
    assert ProductMapping.query.filter_by(supplier_code="A-300").one().product.code == "TOW-0999"
    assert "unmapped_product" not in codes(d)


def test_reject_and_allow_duplicate(seeded):
    ingest(sample_bytes("alfa-1.xml"), "a.xml")
    d2 = ingest(sample_bytes("alfa-1.xml"), "b.xml")
    assert d2.status == "duplicate"
    resolve(d2, "allow_duplicate", {}, True, "admin")
    assert "duplicate" not in codes(d2)
    resolve(d2, "reject", {}, True, "admin")
    assert d2.status == "rejected"


def test_unknown_action(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    with pytest.raises(NegotiationError):
        resolve(d, "hack", {}, True, "admin")
```

- [ ] **Step 2: Test akceptacyjny uczenia (wszystkie formaty)**

`tests/test_learning.py`:
```python
"""Kryterium sukcesu specu: pierwsza faktura → negocjacja, kolejna tego dostawcy → automatycznie."""
import pytest

from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def resolve_with_top_suggestions(doc, fallback_factor="12", max_steps=25):
    """Symuluje operatora, który zawsze wybiera pierwszą podpowiedź i „zapamiętaj”."""
    for _ in range(max_steps):
        blocking = [i for i in doc.issues if i["severity"] == "blocking"]
        if not blocking:
            return doc
        i = blocking[0]
        sug = i["suggestions"]
        code = i["code"]
        if code == "unknown_supplier":
            s = next(x for x in sug if x["kind"] == "create_supplier")
            resolve(doc, "create_supplier", {"name": s["name"], "tax_id": s["tax_id"]}, True, "test")
        elif code in ("unmapped_field", "transform_error", "invalid_value"):
            s = sug[0]
            data = ({"field": i["field"], "path": s["path"], "transforms": s.get("transforms", [])}
                    if s["kind"] in ("path", "line_path") else {"field": i["field"], "value": s["value"]})
            resolve(doc, "map_field", data, True, "test")
        elif code == "unknown_unit":
            resolve(doc, "map_unit", {"alias": i["source_value"], "unit": sug[0]["unit"]}, True, "test")
        elif code == "missing_conversion":
            g = sug[0]
            resolve(doc, "add_conversion", {"from_unit": g["from_unit"], "to_unit": g["to_unit"],
                                            "factor": g["factor"] or fallback_factor, "scope": "supplier"},
                    True, "test")
        elif code == "unmapped_product":
            s = sug[0]
            if s["kind"] == "product":
                resolve(doc, "map_product", {"line_no": i["line_no"], "product_code": s["code"]}, True, "test")
            else:
                resolve(doc, "create_product", {"line_no": i["line_no"], "code": s["code"], "name": s["name"],
                                                "unit": s["unit"] or "szt"}, True, "test")
        else:
            pytest.fail(f"Nieobsłużony problem: {i}")
    pytest.fail(f"Nie udało się rozwiązać problemów: {doc.issues}")


@pytest.mark.parametrize("name,second", [
    ("alfa-1.xml", None),
    ("beta-ksef.xml", (b"FV/B/1024/2026", b"FV/B/1025/2026")),
    ("gamma-ubl.xml", (b"GAM-2026-0315", b"GAM-2026-0316")),
    ("delta.csv", (b"D/77/2026", b"D/78/2026")),
    ("epsilon.json", (b"E-2026-0042", b"E-2026-0043")),
])
def test_first_invoice_negotiated_next_one_automatic(seeded, name, second):
    first = ingest(sample_bytes(name), name)
    assert first.status == "needs_review"
    resolve_with_top_suggestions(first)
    assert first.status == "approved", first.issues

    data = sample_bytes("alfa-2.xml") if second is None else sample_bytes(name).replace(*second)
    nxt = ingest(data, "kolejna-" + name)
    assert nxt.status == "approved", nxt.issues
    assert nxt.supplier_id == first.supplier_id
    assert nxt.template_id == first.template_id
    assert not [i for i in nxt.issues if i["severity"] == "blocking"]


def test_learning_alfa_details(seeded):
    d1 = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve_with_top_suggestions(d1)
    d2 = ingest(sample_bytes("alfa-2.xml"), "alfa-2.xml")
    l1 = d2.result["lines"][0]
    assert (l1["product_index"], l1["unit"], l1["unit_source"], l1["batch"], l1["expiry_date"]) == \
        ("TOW-0001", "szt", "pcs", "L2607", "2027-07-15")
    assert d2.result["currency"] == "PLN"


def test_conversions_applied(seeded):
    beta = ingest(sample_bytes("beta-ksef.xml"), "b.xml")
    resolve_with_top_suggestions(beta)
    l1 = beta.result["lines"][0]
    assert (l1["qty"], l1["unit"], l1["unit_price_net"], l1["conversion_factor"]) == ("500", "kg", "1.60", "25")
    delta = ingest(sample_bytes("delta.csv"), "d.csv")
    resolve_with_top_suggestions(delta)
    l1 = delta.result["lines"][0]
    assert (l1["qty"], l1["unit"], l1["unit_price_net"]) == ("24", "szt", "8.00")
```

- [ ] **Step 3: FAIL.**

- [ ] **Step 4: Implementacja `app/services/negotiation.py`**

```python
"""Akcje rozwiązywania problemów („negocjacja”) — jednorazowo albo z zapamiętaniem."""
from __future__ import annotations

import copy
from decimal import Decimal

from app.engine.canonical import FIELD_LABELS, LINE_KEYS
from app.engine.lookups import norm_alias
from app.engine.suggest import FIELDS_BY_KEY
from app.engine.tree import relative_path
from app.engine.values import normalize_gtin, to_decimal
from app.extensions import db
from app.models import (STATUS_REJECTED, Document, Product, ProductMapping, Supplier, Template, Unit,
                        UnitAlias, UnitConversion)
from app.services.audit import audit
from app.services.pipeline import best_template_for, current_rules, load_tree, process
from app.services.templates import create_template, new_version

NEED_SUPPLIER = "Najpierw rozpoznaj dostawcę — to pierwszy problem na liście."


class NegotiationError(ValueError):
    pass


def _set_override(doc: Document, section: str | None, key: str, value) -> None:
    ov = copy.deepcopy(doc.overrides or {})
    if section is None:
        ov[key] = value
    else:
        ov.setdefault(section, {})[key] = value
    doc.overrides = ov


def _save_rules(doc: Document, rules: dict, user: str | None, comment: str) -> None:
    if doc.template_id:
        new_version(db.session.get(Template, doc.template_id), rules, user, comment)
    else:
        doc.draft_rules = rules


def _require_supplier(doc: Document) -> None:
    if not doc.supplier_id:
        raise NegotiationError(NEED_SUPPLIER)


def _unit(code: str) -> Unit:
    u = Unit.query.filter_by(code=(code or "").strip().lower()).first()
    if not u:
        raise NegotiationError(f"Nieznana jednostka „{code}” — dodaj ją w Słownikach.")
    return u


def _line(doc: Document, line_no) -> dict:
    try:
        return (doc.result or {})["lines"][int(line_no) - 1]
    except (KeyError, IndexError, TypeError, ValueError):
        raise NegotiationError(f"Brak pozycji nr {line_no}.") from None


def _attach_supplier(doc: Document, supplier: Supplier, user: str | None) -> None:
    doc.supplier_id = supplier.id
    tree = load_tree(doc)
    if best_template_for(supplier.id, tree.path_set()) is None:
        rules = doc.draft_rules or current_rules(doc)
        tpl = create_template(supplier, tree.leaf_paths(), tree.fingerprint(), tree.fmt, rules, user)
        doc.template_id = tpl.id
        doc.draft_rules = None


def a_create_supplier(doc, data, remember, user):
    name = (data.get("name") or "").strip()
    if not name:
        raise NegotiationError("Podaj nazwę dostawcy.")
    s = Supplier(name=name, tax_id=(data.get("tax_id") or "").strip() or None)
    db.session.add(s)
    db.session.flush()
    _attach_supplier(doc, s, user)


def a_use_supplier(doc, data, remember, user):
    s = db.session.get(Supplier, int(data.get("supplier_id") or 0))
    if not s:
        raise NegotiationError("Nie znaleziono dostawcy.")
    inv_tax = ((doc.result or {}).get("supplier") or {}).get("tax_id")
    if not s.tax_id and inv_tax:
        s.tax_id = inv_tax
    _attach_supplier(doc, s, user)


def a_map_field(doc, data, remember, user):
    fld = data.get("field")
    if fld != "line_path" and fld not in FIELDS_BY_KEY:
        raise NegotiationError(f"Nieznane pole „{fld}”.")
    if not remember:
        if fld == "line_path" or fld in LINE_KEYS:
            raise NegotiationError("Dla pól pozycji wybierz „zapamiętaj w szablonie”.")
        if data.get("value") in (None, ""):
            raise NegotiationError("Podaj wartość.")
        _set_override(doc, "fields", fld, data["value"])
        return
    rules = current_rules(doc)
    if fld == "line_path":
        if not data.get("path"):
            raise NegotiationError("Wskaż element z pozycjami.")
        rules["line_path"] = data["path"]
    else:
        section = "lines" if fld in LINE_KEYS else "header"
        if data.get("path"):
            path = data["path"]
            if section == "lines" and rules.get("line_path"):
                path = relative_path(path, rules["line_path"]) or path
            rules.setdefault(section, {})[fld] = {"path": path, "transforms": data.get("transforms") or []}
        elif data.get("value") not in (None, ""):
            rules.setdefault("line_defaults" if section == "lines" else "defaults", {})[fld] = data["value"]
        else:
            raise NegotiationError("Wskaż ścieżkę w pliku albo wartość domyślną.")
    _save_rules(doc, rules, user, f"Mapowanie pola: {FIELD_LABELS.get(fld, fld)}")


def a_map_unit(doc, data, remember, user):
    alias = (data.get("alias") or "").strip()
    unit = _unit(data.get("unit"))
    if not alias:
        raise NegotiationError("Brak jednostki z faktury.")
    if not remember:
        _set_override(doc, "units", alias, unit.code)
        return
    _require_supplier(doc)
    row = UnitAlias.query.filter_by(alias_norm=norm_alias(alias), supplier_id=doc.supplier_id).first()
    if row:
        row.unit_id = unit.id
    else:
        db.session.add(UnitAlias(alias=alias, unit_id=unit.id, supplier_id=doc.supplier_id))


def a_add_conversion(doc, data, remember, user):
    _require_supplier(doc)
    src, dst = _unit(data.get("from_unit")), _unit(data.get("to_unit"))
    try:
        factor = to_decimal(data.get("factor"))
    except ValueError as exc:
        raise NegotiationError(f"Przelicznik: {exc}") from None
    if factor <= 0:
        raise NegotiationError("Przelicznik musi być większy od zera.")
    product_id = None
    if data.get("scope") == "product":
        code = _line(doc, data.get("line_no")).get("product_index")
        product = Product.query.filter_by(code=code).first() if code else None
        if not product:
            raise NegotiationError("Przelicznik dla towaru wymaga najpierw przypisania towaru do pozycji.")
        product_id = product.id
    db.session.add(UnitConversion(supplier_id=doc.supplier_id, product_id=product_id, from_unit_id=src.id,
                                  to_unit_id=dst.id, factor=factor))


def _map_line_to_product(doc, line_no, product: Product, remember: bool) -> None:
    if not remember:
        _set_override(doc, "products", str(int(line_no)), product.code)
        return
    _require_supplier(doc)
    line = _line(doc, line_no)
    code, gtin = line.get("supplier_code"), line.get("gtin")
    q = ProductMapping.query.filter_by(supplier_id=doc.supplier_id)
    row = q.filter_by(supplier_code=code).first() if code else q.filter_by(supplier_gtin=gtin).first()
    if row:
        row.product_id = product.id
    else:
        db.session.add(ProductMapping(supplier_id=doc.supplier_id, supplier_code=code, supplier_gtin=gtin,
                                      product_id=product.id))


def a_map_product(doc, data, remember, user):
    product = Product.query.filter_by(code=data.get("product_code")).first()
    if not product:
        raise NegotiationError("Nie znaleziono towaru w kartotece.")
    _map_line_to_product(doc, data.get("line_no"), product, remember)


def a_create_product(doc, data, remember, user):
    code, name = (data.get("code") or "").strip(), (data.get("name") or "").strip()
    if not code or not name:
        raise NegotiationError("Podaj indeks i nazwę towaru.")
    if Product.query.filter_by(code=code).first():
        raise NegotiationError(f"Indeks „{code}” już istnieje.")
    if remember:
        _require_supplier(doc)
    line = _line(doc, data.get("line_no"))
    gtin = None
    if line.get("gtin"):
        try:
            gtin = normalize_gtin(line["gtin"])
        except ValueError:
            gtin = None
    product = Product(code=code, name=name, gtin=gtin, unit_id=_unit(data.get("unit") or "szt").id)
    db.session.add(product)
    db.session.flush()
    _map_line_to_product(doc, data.get("line_no"), product, remember)


def a_allow_duplicate(doc, data, remember, user):
    _set_override(doc, None, "allow_duplicate", True)


def a_reject(doc, data, remember, user):
    doc.status = STATUS_REJECTED


ACTIONS = {
    "create_supplier": a_create_supplier, "use_supplier": a_use_supplier, "map_field": a_map_field,
    "map_unit": a_map_unit, "add_conversion": a_add_conversion, "map_product": a_map_product,
    "create_product": a_create_product, "allow_duplicate": a_allow_duplicate, "reject": a_reject,
}


def resolve(doc: Document, action: str, data: dict, remember: bool = True, user: str | None = None) -> Document:
    handler = ACTIONS.get(action)
    if handler is None:
        raise NegotiationError(f"Nieznana akcja „{action}”.")
    try:
        handler(doc, data or {}, remember, user)
        db.session.flush()
        audit(f"resolve:{action}", "document", doc.id, {"data": data or {}, "remember": remember}, user)
        if action != "reject":
            process(doc)
        db.session.commit()
    except NegotiationError:
        db.session.rollback()
        raise
    return doc
```

Uwaga do `test_learning_alfa_details`: domyślną walutą z pierwszej podpowiedzi jest `PLN`, bo to pierwsza wartość w `DEFAULT_VALUES["currency"]`. W pliku alfa-2 GS1 ma `15270715`, stąd `2027-07-15`.

- [ ] **Step 5: PASS:** `pytest tests/test_negotiation.py tests/test_learning.py -q`

Diagnostyka przy porażce `test_first_invoice_negotiated_next_one_automatic`: wypisz `first.issues` i `first.template.active_version.rules`. Najczęstsze przyczyny to brak synonimu w YAML (popraw YAML) albo zła kolejność podpowiedzi (popraw progi w `suggest.py`). **Nie** osłabiaj asercji testu.

- [ ] **Step 6: Commit**
```bash
git add app/services/negotiation.py tests/test_negotiation.py tests/test_learning.py
pytest -q && pytest tests/test_no_private_data.py -q
git commit -m "feat(negocjacja): akcje rozwiązywania problemów + test uczenia na 5 formatach

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 13: REST API v1 + OpenAPI + Swagger UI

**Files:**
- Create: `app/api/__init__.py`, `app/api/routes.py`, `app/static/openapi.yaml`, `app/templates/api_docs.html`
- Modify: `app/__init__.py` (rejestracja blueprintu, `csrf.exempt`)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `ingest`, `process`, `DocumentTooLarge` (Task 11), `verify_key` (Task 10), modele.
- Produces: blueprint `api` pod `/api/v1`; `doc_to_json(doc: Document, full: bool = True) -> dict` (używany też przez panel do eksportu JSON); trasa `GET /api/docs` (Swagger UI, publiczna). Błędy mają postać `{"error": {"code": str, "message": str}}`. Kody: `unauthorized` 401, `empty_body` 400, `too_large` 413, `not_found` 404, `bad_request` 400.

- [ ] **Step 1: Testy**

`tests/test_api.py`:
```python
import io

from tests.conftest import sample_bytes

KEY = {"X-API-Key": "xp_test_demo_key"}


def test_requires_key(seeded, client):
    r = client.get("/api/v1/documents")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/documents", headers={"X-API-Key": "zly"}).status_code == 401


def test_upload_multipart_and_get(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY,
                    data={"file": (io.BytesIO(sample_bytes("epsilon.json")), "epsilon.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "needs_review" and body["format"] == "json"
    assert body["invoice"]["number"] == "E-2026-0042"
    assert body["issues"][0]["code"] == "unknown_supplier"
    r2 = client.get(f"/api/v1/documents/{body['id']}", headers=KEY)
    assert r2.status_code == 200 and r2.get_json()["id"] == body["id"]


def test_upload_raw_body(seeded, client):
    r = client.post("/api/v1/documents", headers={**KEY, "X-Filename": "delta.csv", "Content-Type": "text/csv"},
                    data=sample_bytes("delta.csv"))
    assert r.status_code == 201 and r.get_json()["format"] == "csv"


def test_api_empty_body_400(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY, data=b"")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "empty_body"


def test_unreadable_returns_201_rejected(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a><b></a>")
    assert r.status_code == 201 and r.get_json()["status"] == "rejected"


def test_too_large(seeded, app, client):
    app.config["MAX_DOCUMENT_BYTES"] = 10
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a>" + b"x" * 50 + b"</a>")
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "too_large"


def test_list_filter_and_reprocess(seeded, client):
    client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml"))
    r = client.get("/api/v1/documents?status=needs_review", headers=KEY)
    items = r.get_json()["items"]
    assert len(items) == 1 and "invoice" not in items[0]
    r = client.post(f"/api/v1/documents/{items[0]['id']}/reprocess", headers=KEY)
    assert r.status_code == 200 and r.get_json()["status"] == "needs_review"
    assert client.get("/api/v1/documents?status=zly", headers=KEY).status_code == 400
    assert client.get("/api/v1/documents/9999", headers=KEY).status_code == 404


def test_suppliers_and_docs_page(seeded, client):
    assert client.get("/api/v1/suppliers", headers=KEY).get_json() == {"items": []}
    assert client.get("/api/docs").status_code == 200
    assert client.get("/static/openapi.yaml").status_code == 200
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implementacja**

`app/api/__init__.py`:
```python
from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api/v1")

from . import routes  # noqa: E402,F401
```

`app/api/routes.py`:
```python
from datetime import datetime
from functools import wraps

from flask import current_app, g, jsonify, request

from app.extensions import db
from app.models import STATUS_LABELS, Document, Supplier
from app.services.apikeys import verify_key
from app.services.pipeline import DocumentTooLarge, ingest, process

from . import bp


def api_error(code: str, message: str, status: int):
    return jsonify(error={"code": code, "message": message}), status


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = verify_key(request.headers.get("X-API-Key"))
        if key is None:
            return api_error("unauthorized", "Brak lub nieprawidłowy klucz API (nagłówek X-API-Key).", 401)
        g.api_key = key
        db.session.commit()
        return fn(*args, **kwargs)
    return wrapper


def doc_to_json(doc: Document, full: bool = True) -> dict:
    out = {
        "id": doc.id, "status": doc.status, "status_label": doc.status_label, "format": doc.fmt,
        "filename": doc.filename, "number": doc.number, "issue_date": doc.issue_date, "doc_type": doc.doc_type,
        "supplier": {"id": doc.supplier.id, "name": doc.supplier.name} if doc.supplier else None,
        "template_version": doc.template_version.version if doc.template_version else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "issues_count": len(doc.issues or []),
    }
    if full:
        out["invoice"] = doc.result
        out["issues"] = doc.issues or []
    return out


@bp.post("/documents")
@require_api_key
def create_document():
    if "file" in request.files:
        f = request.files["file"]
        data, filename = f.read(), f.filename
    else:
        data, filename = request.get_data(), request.headers.get("X-Filename", "dokument")
    if not data or not data.strip():
        return api_error("empty_body", "Pusty plik — wyślij fakturę jako multipart 'file' lub surowe body.", 400)
    try:
        doc = ingest(data, filename, source="api", api_key_id=g.api_key.id)
    except DocumentTooLarge as exc:
        return api_error("too_large", str(exc), 413)
    return jsonify(doc_to_json(doc)), 201


@bp.get("/documents")
@require_api_key
def list_documents():
    q = Document.query.order_by(Document.id.desc())
    status = request.args.get("status")
    if status:
        if status not in STATUS_LABELS:
            return api_error("bad_request", f"Nieznany status „{status}”.", 400)
        q = q.filter_by(status=status)
    since = request.args.get("since")
    if since:
        try:
            q = q.filter(Document.created_at >= datetime.fromisoformat(since))
        except ValueError:
            return api_error("bad_request", "Parametr since musi być datą ISO 8601.", 400)
    limit = min(int(request.args.get("limit", 100)), 500)
    return jsonify(items=[doc_to_json(d, full=False) for d in q.limit(limit)])


def _get_doc(doc_id: int):
    return db.session.get(Document, doc_id)


@bp.get("/documents/<int:doc_id>")
@require_api_key
def get_document(doc_id):
    doc = _get_doc(doc_id)
    if not doc:
        return api_error("not_found", "Nie znaleziono dokumentu.", 404)
    return jsonify(doc_to_json(doc))


@bp.post("/documents/<int:doc_id>/reprocess")
@require_api_key
def reprocess_document(doc_id):
    doc = _get_doc(doc_id)
    if not doc:
        return api_error("not_found", "Nie znaleziono dokumentu.", 404)
    process(doc)
    db.session.commit()
    return jsonify(doc_to_json(doc))


@bp.get("/suppliers")
@require_api_key
def list_suppliers():
    return jsonify(items=[{"id": s.id, "name": s.name, "tax_id": s.tax_id}
                          for s in Supplier.query.order_by(Supplier.name)])


@bp.errorhandler(413)
def too_large(_):
    limit = current_app.config["MAX_DOCUMENT_BYTES"] // (1024 * 1024)
    return api_error("too_large", f"Plik przekracza limit {limit} MB.", 413)
```

`app/templates/api_docs.html`:
```html
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8"><title>API · XML Parser</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='vendor/swagger-ui.css') }}">
</head>
<body>
  <div id="swagger"></div>
  <script src="{{ url_for('static', filename='vendor/swagger-ui-bundle.js') }}"></script>
  <script>
    SwaggerUIBundle({ url: "{{ url_for('static', filename='openapi.yaml') }}", dom_id: "#swagger" });
  </script>
</body>
</html>
```

`app/static/openapi.yaml`:
```yaml
openapi: 3.0.3
info:
  title: XML Parser faktur — API
  version: "1"
  description: |
    Wysyłasz fakturę (XML / JSON / CSV), dostajesz znormalizowany JSON.
    Status `needs_review` oznacza, że operator musi rozwiązać problemy w panelu,
    a `approved` — że faktura została odczytana automatycznie.
servers: [{ url: /api/v1 }]
security: [{ ApiKey: [] }]
components:
  securitySchemes:
    ApiKey: { type: apiKey, in: header, name: X-API-Key }
  schemas:
    Error:
      type: object
      properties:
        error:
          type: object
          properties: { code: { type: string }, message: { type: string } }
    Issue:
      type: object
      properties:
        code: { type: string, example: unknown_unit }
        severity: { type: string, enum: [blocking, warning] }
        message: { type: string }
        field: { type: string, nullable: true }
        line_no: { type: integer, nullable: true }
        source_value: { type: string, nullable: true }
        suggestions: { type: array, items: { type: object } }
    Document:
      type: object
      properties:
        id: { type: integer }
        status: { type: string, enum: [received, approved, needs_review, duplicate, rejected] }
        status_label: { type: string }
        format: { type: string, enum: [xml, json, csv], nullable: true }
        number: { type: string, nullable: true }
        supplier: { type: object, nullable: true }
        template_version: { type: integer, nullable: true }
        invoice: { type: object, description: Dokument kanoniczny (kwoty jako stringi) }
        issues: { type: array, items: { $ref: "#/components/schemas/Issue" } }
paths:
  /documents:
    post:
      summary: Wyślij fakturę
      requestBody:
        content:
          multipart/form-data:
            schema: { type: object, properties: { file: { type: string, format: binary } } }
          application/xml: { schema: { type: string } }
          application/json: { schema: { type: object } }
          text/csv: { schema: { type: string } }
      responses:
        "201": { description: Przyjęto, content: { application/json: { schema: { $ref: "#/components/schemas/Document" } } } }
        "400": { description: Pusty plik, content: { application/json: { schema: { $ref: "#/components/schemas/Error" } } } }
        "401": { description: Brak klucza API }
        "413": { description: Plik za duży }
    get:
      summary: Lista dokumentów
      parameters:
        - { name: status, in: query, schema: { type: string } }
        - { name: since, in: query, schema: { type: string, format: date-time } }
        - { name: limit, in: query, schema: { type: integer, default: 100, maximum: 500 } }
      responses: { "200": { description: OK } }
  /documents/{id}:
    get:
      summary: Szczegóły dokumentu
      parameters: [{ name: id, in: path, required: true, schema: { type: integer } }]
      responses:
        "200": { description: OK, content: { application/json: { schema: { $ref: "#/components/schemas/Document" } } } }
        "404": { description: Nie znaleziono }
  /documents/{id}/reprocess:
    post:
      summary: Przetwórz ponownie aktywną wersją szablonu
      parameters: [{ name: id, in: path, required: true, schema: { type: integer } }]
      responses: { "200": { description: OK } }
  /suppliers:
    get:
      summary: Lista dostawców
      responses: { "200": { description: OK } }
```

W `app/__init__.py` (przed `return app`):
```python
    from flask import render_template
    from .api import bp as api_bp
    csrf.exempt(api_bp)
    app.register_blueprint(api_bp)

    @app.get("/api/docs")
    def api_docs():
        return render_template("api_docs.html")
```

- [ ] **Step 4: PASS:** `pytest tests/test_api.py -q`. Jeśli `test_too_large` zwraca 413 z HTML (limit `MAX_CONTENT_LENGTH` werkzeuga), zostaw obsługę w `ingest` jako główną. Test zmienia tylko `MAX_DOCUMENT_BYTES`, więc trafi w `DocumentTooLarge`.

- [ ] **Step 5: Commit**
```bash
git add app/api app/static/openapi.yaml app/templates/api_docs.html app/__init__.py tests/test_api.py
pytest tests/test_no_private_data.py -q
git commit -m "feat(api): REST API v1 z kluczami, OpenAPI i Swagger UI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 14: Panel — logowanie, nawigacja, pulpit, upload, kolejka, dokument z kreatorem negocjacji

**Files:**
- Create: `app/web/__init__.py`, `app/web/auth.py`, `app/web/documents.py`
- Create: `app/templates/_nav.html`, `login.html`, `dashboard.html`, `upload.html`, `documents.html`, `document.html`, `_issues.html`
- Modify: `app/templates/base.html` (blok `nav` → `{% include "_nav.html" %}`), `app/__init__.py` (`register_web(app)`)
- Test: `tests/conftest.py` (fixture `auth_client`), `tests/test_web_documents.py`

**Interfaces:**
- Consumes: `ingest`, `process`, `load_tree`, `DocumentTooLarge` (Task 11), `resolve`, `NegotiationError` (Task 12), `doc_to_json` (Task 13), `FIELD_LABELS`, `LINE_FIELDS`, `HEADER_FIELDS` (Task 6), `DbLookups` (Task 10), `STATUS_LABELS`.
- Produces: `register_web(app)`; blueprinty `auth` (`/login`, `/logout`) i `docs` (`/` , `/pulpit`, `/wgraj`, `/kolejka`, `/dokumenty`, `/dokumenty/<id>`, `POST /dokumenty/<id>/rozwiaz`, `POST /dokumenty/<id>/ponownie`, `GET /dokumenty/<id>/plik`, `GET /dokumenty/<id>/json`); `form_to_action(doc, form) -> tuple[str, dict, bool]`. Wszystkie widoki panelu wymagają `login_required`. `/` przekierowuje do `demo.index` w `DEMO_MODE` (blueprint `demo` powstaje w Task 17; do tego czasu na `/pulpit`).

- [ ] **Step 1: Fixture i testy**

Dopisz do `tests/conftest.py`:
```python
@pytest.fixture
def auth_client(seeded, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    return client
```

`tests/test_web_documents.py`:
```python
import io

from app.models import Document
from tests.conftest import sample_bytes


def upload(client, name):
    return client.post("/wgraj", data={"file": (io.BytesIO(sample_bytes(name)), name)},
                       content_type="multipart/form-data", follow_redirects=True)


def test_login_required(seeded, client):
    r = client.get("/pulpit")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_bad_login(seeded, client):
    r = client.post("/login", data={"email": "admin@example.com", "password": "zle"}, follow_redirects=True)
    assert "Nieprawidłowy e-mail lub hasło" in r.get_data(as_text=True)


def test_dashboard_has_footer_and_version(auth_client):
    from app.version import __version__
    html = auth_client.get("/pulpit").get_data(as_text=True)
    assert "Project &amp; Development: Tomasz" in html and f"v{__version__}" in html
    assert "https://github.com/AmigoUK/xml-parser" in html


def test_upload_shows_issues_and_tree(auth_client):
    r = upload(auth_client, "alfa-1.xml")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Do wyjaśnienia" in html and "Nie rozpoznano dostawcy" in html
    assert "TowarKodEan128" in html          # drzewo źródła
    assert "Hurtownia Alfa Sp. z o.o." in html  # podpowiedź utworzenia dostawcy


def test_full_negotiation_through_forms(auth_client):
    upload(auth_client, "alfa-1.xml")
    doc = Document.query.one()
    url = f"/dokumenty/{doc.id}/rozwiaz"
    auth_client.post(url, data={"action": "create_supplier", "name": "Hurtownia Alfa Sp. z o.o.",
                                "tax_id": "PL9990000011"})
    idx = next(i for i, x in enumerate(Document.query.one().issues) if x["field"] == "currency")
    auth_client.post(url, data={"action": "map_field", "issue": idx, "choice": "value", "value": "PLN",
                                "remember": "1"})
    auth_client.post(url, data={"action": "map_unit", "alias": "pcs", "unit": "szt", "remember": "1"})
    r = auth_client.post(url, data={"action": "map_product", "line_no": "3", "product_code": "TOW-0003",
                                    "remember": "1"}, follow_redirects=True)
    assert "Zatwierdzona" in r.get_data(as_text=True)
    assert Document.query.one().status == "approved"


def test_negotiation_error_is_flashed(auth_client):
    upload(auth_client, "alfa-1.xml")
    doc = Document.query.one()
    r = auth_client.post(f"/dokumenty/{doc.id}/rozwiaz", data={"action": "map_unit", "alias": "pcs",
                                                                "unit": "szt", "remember": "1"},
                         follow_redirects=True)
    assert "Najpierw rozpoznaj dostawcę" in r.get_data(as_text=True)


def test_queue_json_and_raw(auth_client):
    upload(auth_client, "gamma-ubl.xml")
    doc = Document.query.one()
    assert "GAM-2026-0315" in auth_client.get("/kolejka").get_data(as_text=True)
    assert auth_client.get(f"/dokumenty/{doc.id}/json").get_json()["invoice"]["currency"] == "EUR"
    assert auth_client.get(f"/dokumenty/{doc.id}/plik").data == sample_bytes("gamma-ubl.xml")


def test_upload_empty_file(auth_client):
    r = auth_client.post("/wgraj", data={"file": (io.BytesIO(b""), "x.xml")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "Wybierz niepusty plik" in r.get_data(as_text=True)
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Blueprinty**

`app/web/__init__.py`:
```python
def register_web(app):
    from .auth import bp as auth_bp
    from .documents import bp as docs_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(docs_bp)
    for name in ("catalog", "templates_views", "apikeys", "history", "demo"):
        try:
            module = __import__(f"app.web.{name}", fromlist=["bp"])
        except ModuleNotFoundError:
            continue  # moduły dochodzą w kolejnych zadaniach (15–17)
        app.register_blueprint(module.bp)
```

`app/web/auth.py`:
```python
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from app.models import User

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=(request.form.get("email") or "").strip().lower()).first()
        if user and user.check_password(request.form.get("password") or ""):
            login_user(user)
            nxt = request.args.get("next")
            return redirect(nxt if nxt and nxt.startswith("/") and not nxt.startswith("//")
                            else url_for("docs.dashboard"))
        flash("Nieprawidłowy e-mail lub hasło.", "error")
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
```

`app/web/documents.py`:
```python
from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from app.engine.canonical import FIELD_LABELS, HEADER_FIELDS, LINE_FIELDS
from app.extensions import db
from app.ingest import ReaderError
from app.models import STATUS_LABELS, STATUS_NEEDS_REVIEW, Document, Product, Supplier, Unit
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import DocumentTooLarge, ingest, load_tree, process
from app.services.storage import get_storage

bp = Blueprint("docs", __name__)

ALWAYS_REMEMBER = {"create_supplier", "use_supplier", "add_conversion", "allow_duplicate", "reject"}
FORM_FIELDS = ("name", "tax_id", "supplier_id", "alias", "unit", "from_unit", "to_unit", "factor", "scope",
               "line_no", "product_code", "code")


def form_to_action(doc: Document, form) -> tuple[str, dict, bool]:
    action = form.get("action", "")
    remember = action in ALWAYS_REMEMBER or form.get("remember") == "1"
    if action == "map_field":
        issue = (doc.issues or [])[int(form.get("issue", 0))]
        fld, choice = issue["field"], form.get("choice", "")
        if choice.startswith("s"):
            s = issue["suggestions"][int(choice[1:])]
            data = ({"field": fld, "path": s["path"], "transforms": s.get("transforms") or []}
                    if s["kind"] in ("path", "line_path") else {"field": fld, "value": s["value"]})
        elif choice == "manual_path":
            data = {"field": fld, "path": form.get("manual_path")}
        else:
            data = {"field": fld, "value": form.get("value")}
        return action, data, remember
    return action, {k: form.get(k) for k in FORM_FIELDS if form.get(k) not in (None, "")}, remember


def _get(doc_id: int) -> Document:
    doc = db.session.get(Document, doc_id)
    if not doc:
        abort(404)
    return doc


@bp.get("/")
def index():
    if current_app.config["DEMO_MODE"] and "demo" in current_app.blueprints:
        return redirect(url_for("demo.index"))
    return redirect(url_for("docs.dashboard"))


@bp.get("/pulpit")
@login_required
def dashboard():
    counts = {s: Document.query.filter_by(status=s).count() for s in STATUS_LABELS}
    recent = Document.query.order_by(Document.id.desc()).limit(10).all()
    return render_template("dashboard.html", counts=counts, docs=recent, labels=STATUS_LABELS)


@bp.route("/wgraj", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        data = f.read() if f else b""
        if not data.strip():
            flash("Wybierz niepusty plik faktury (XML, JSON lub CSV).", "error")
            return redirect(url_for("docs.upload"))
        try:
            doc = ingest(data, f.filename, source="upload")
        except DocumentTooLarge as exc:
            flash(str(exc), "error")
            return redirect(url_for("docs.upload"))
        return redirect(url_for("docs.detail", doc_id=doc.id))
    return render_template("upload.html")


@bp.get("/kolejka")
@login_required
def queue():
    docs = Document.query.filter_by(status=STATUS_NEEDS_REVIEW).order_by(Document.id).all()
    return render_template("documents.html", docs=docs, title="Kolejka do wyjaśnienia", queue=True)


@bp.get("/dokumenty")
@login_required
def documents():
    q = Document.query.order_by(Document.id.desc())
    status = request.args.get("status")
    if status in STATUS_LABELS:
        q = q.filter_by(status=status)
    return render_template("documents.html", docs=q.limit(200).all(), title="Dokumenty", queue=False,
                           labels=STATUS_LABELS, current=status)


@bp.get("/dokumenty/<int:doc_id>")
@login_required
def detail(doc_id):
    doc = _get(doc_id)
    try:
        rows = load_tree(doc).display_rows()
    except (ReaderError, OSError):
        rows = []
    return render_template(
        "document.html", doc=doc, rows=rows, field_labels=FIELD_LABELS,
        header_fields=HEADER_FIELDS, line_fields=LINE_FIELDS,
        leaf_paths=[r["path"] for r in rows if r["value"]],
        units=Unit.query.order_by(Unit.code).all(),
        products=Product.query.order_by(Product.code).all(),
        suppliers=Supplier.query.order_by(Supplier.name).all())


@bp.post("/dokumenty/<int:doc_id>/rozwiaz")
@login_required
def resolve_issue(doc_id):
    doc = _get(doc_id)
    try:
        action, data, remember = form_to_action(doc, request.form)
        resolve(doc, action, data, remember, current_user.email)
        flash("Zapisano. Dokument przetworzono ponownie.", "success")
    except (NegotiationError, ValueError, IndexError, KeyError) as exc:
        flash(str(exc) or "Nie udało się zastosować zmiany.", "error")
    return redirect(url_for("docs.detail", doc_id=doc_id))


@bp.post("/dokumenty/<int:doc_id>/ponownie")
@login_required
def reprocess(doc_id):
    doc = _get(doc_id)
    process(doc)
    db.session.commit()
    flash("Przetworzono ponownie aktywną wersją szablonu.", "success")
    return redirect(url_for("docs.detail", doc_id=doc_id))


@bp.get("/dokumenty/<int:doc_id>/plik")
@login_required
def raw(doc_id):
    doc = _get(doc_id)
    mime = {"xml": "application/xml", "json": "application/json", "csv": "text/csv"}.get(doc.fmt,
                                                                                          "application/octet-stream")
    return Response(get_storage().load(doc.sha256), mimetype=mime,
                    headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'})


@bp.get("/dokumenty/<int:doc_id>/json")
@login_required
def as_json(doc_id):
    from app.api.routes import doc_to_json
    return jsonify(doc_to_json(_get(doc_id)))
```

- [ ] **Step 4: Szablony**

`app/templates/_nav.html`:
```html
<nav class="navbar navbar-expand-lg bg-dark navbar-dark">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('docs.index') }}">XML Parser faktur</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
    <div class="collapse navbar-collapse" id="nav">
      <ul class="navbar-nav me-auto">
        {% if DEMO_MODE %}<li class="nav-item"><a class="nav-link" href="{{ url_for('docs.index') }}">O demo</a></li>{% endif %}
        {% if current_user.is_authenticated %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('docs.dashboard') }}">Pulpit</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('docs.upload') }}">Wgraj fakturę</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('docs.queue') }}">Kolejka</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('docs.documents') }}">Dokumenty</a></li>
        {% if 'catalog' in nav_blueprints %}
        <li class="nav-item dropdown">
          <a class="nav-link dropdown-toggle" href="#" data-bs-toggle="dropdown">Dane</a>
          <ul class="dropdown-menu">
            <li><a class="dropdown-item" href="{{ url_for('catalog.list_suppliers') }}">Dostawcy</a></li>
            <li><a class="dropdown-item" href="{{ url_for('catalog.list_products') }}">Kartoteka towarów</a></li>
            <li><a class="dropdown-item" href="{{ url_for('catalog.list_mappings') }}">Mapowania towarów</a></li>
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item" href="{{ url_for('catalog.list_units') }}">Jednostki</a></li>
            <li><a class="dropdown-item" href="{{ url_for('catalog.list_aliases') }}">Aliasy jednostek</a></li>
            <li><a class="dropdown-item" href="{{ url_for('catalog.list_conversions') }}">Przeliczniki</a></li>
          </ul>
        </li>
        {% endif %}
        {% if 'templates_views' in nav_blueprints %}<li class="nav-item"><a class="nav-link" href="{{ url_for('templates_views.index') }}">Szablony</a></li>{% endif %}
        {% if 'apikeys' in nav_blueprints %}<li class="nav-item"><a class="nav-link" href="{{ url_for('apikeys.index') }}">Klucze API</a></li>{% endif %}
        {% if 'history' in nav_blueprints %}<li class="nav-item"><a class="nav-link" href="{{ url_for('history.index') }}">Historia</a></li>{% endif %}
        {% endif %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('api_docs') }}">API</a></li>
      </ul>
      {% if current_user.is_authenticated %}
      <form method="post" action="{{ url_for('auth.logout') }}" class="d-flex">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <span class="navbar-text me-2 small">{{ current_user.email }}</span>
        <button class="btn btn-sm btn-outline-light">Wyloguj</button>
      </form>
      {% else %}
      <a class="btn btn-sm btn-outline-light" href="{{ url_for('auth.login') }}">Zaloguj</a>
      {% endif %}
    </div>
  </div>
</nav>
```
W `app/__init__.py` dodaj do `inject_globals` klucz `"nav_blueprints": set(app.blueprints)` i wywołaj `register_web(app)` (import `from .web import register_web`) przed `return app`. W `base.html` zamień `{% block nav %}{% endblock %}` na `{% include "_nav.html" %}`.

`app/templates/login.html`:
```html
{% extends "base.html" %}
{% block title %}Logowanie{% endblock %}
{% block content %}
<div class="row justify-content-center"><div class="col-md-5">
  <h1 class="h4 mb-3">Logowanie</h1>
  {% if DEMO_MODE %}<div class="alert alert-info small">Tryb demo — dane logowania znajdziesz na stronie <a href="{{ url_for('docs.index') }}">O demo</a>.</div>{% endif %}
  <form method="post" class="card card-body">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <label class="form-label">E-mail <input class="form-control" type="email" name="email" required autofocus></label>
    <label class="form-label">Hasło <input class="form-control" type="password" name="password" required></label>
    <button class="btn btn-primary">Zaloguj</button>
  </form>
</div></div>
{% endblock %}
```

`app/templates/dashboard.html`:
```html
{% extends "base.html" %}
{% block title %}Pulpit{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Pulpit</h1>
<div class="row g-3 mb-4">
  {% for status, label in labels.items() %}
  <div class="col-6 col-md">
    <a class="card card-body text-decoration-none" href="{{ url_for('docs.documents', status=status) }}">
      <div class="small text-muted">{{ label }}</div><div class="fs-3">{{ counts[status] }}</div>
    </a>
  </div>
  {% endfor %}
</div>
<div class="d-flex justify-content-between align-items-center mb-2">
  <h2 class="h6 m-0">Ostatnie dokumenty</h2>
  <a class="btn btn-sm btn-primary" href="{{ url_for('docs.upload') }}">Wgraj fakturę</a>
</div>
{% include "_doc_table.html" %}
{% endblock %}
```
`app/templates/_doc_table.html`:
```html
<table class="table table-sm table-hover bg-white">
  <thead><tr><th>#</th><th>Plik</th><th>Format</th><th>Dostawca</th><th>Numer</th><th>Status</th><th>Problemy</th><th>Utworzono</th></tr></thead>
  <tbody>
  {% for d in docs %}
    <tr>
      <td><a href="{{ url_for('docs.detail', doc_id=d.id) }}">{{ d.id }}</a></td>
      <td>{{ d.filename }}</td><td>{{ (d.fmt or '—')|upper }}</td>
      <td>{{ d.supplier.name if d.supplier else '—' }}</td><td>{{ d.number or '—' }}</td>
      <td><span class="badge text-bg-{{ {'approved':'success','needs_review':'warning','duplicate':'secondary','rejected':'danger'}.get(d.status,'light') }}">{{ d.status_label }}</span></td>
      <td>{{ (d.issues or [])|length }}</td><td class="small">{{ d.created_at.strftime('%Y-%m-%d %H:%M') if d.created_at }}</td>
    </tr>
  {% else %}
    <tr><td colspan="8" class="text-muted">Brak dokumentów.</td></tr>
  {% endfor %}
  </tbody>
</table>
```

`app/templates/upload.html`:
```html
{% extends "base.html" %}
{% block title %}Wgraj fakturę{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Wgraj fakturę</h1>
<form method="post" enctype="multipart/form-data" class="card card-body"
      x-data="{ name: '' }" @dragover.prevent @drop.prevent="$refs.f.files = $event.dataTransfer.files; name = $refs.f.files[0]?.name">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <div class="border border-2 border-dashed rounded p-5 text-center mb-3 bg-light">
    <p class="mb-2">Przeciągnij tutaj plik XML, JSON lub CSV albo wybierz go z dysku.</p>
    <input class="form-control" type="file" name="file" x-ref="f" accept=".xml,.json,.csv,.txt" @change="name = $event.target.files[0]?.name">
    <p class="small text-muted mt-2" x-text="name"></p>
  </div>
  <button class="btn btn-primary">Przetwórz</button>
</form>
{% endblock %}
```

`app/templates/documents.html`:
```html
{% extends "base.html" %}
{% block title %}{{ title }}{% endblock %}
{% block content %}
<h1 class="h4 mb-3">{{ title }}</h1>
{% if not queue %}
<div class="btn-group btn-group-sm mb-3">
  <a class="btn btn-outline-secondary {% if not current %}active{% endif %}" href="{{ url_for('docs.documents') }}">Wszystkie</a>
  {% for s, l in labels.items() %}<a class="btn btn-outline-secondary {% if current == s %}active{% endif %}" href="{{ url_for('docs.documents', status=s) }}">{{ l }}</a>{% endfor %}
</div>
{% endif %}
{% include "_doc_table.html" %}
{% endblock %}
```

`app/templates/_issues.html` (makra kreatora — każdy problem to karta z własnym formularzem):
```html
{% macro form_open(doc, action) -%}
<form method="post" action="{{ url_for('docs.resolve_issue', doc_id=doc.id) }}" class="mt-2">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <input type="hidden" name="action" value="{{ action }}">
{%- endmacro %}

{% macro remember(default=True) -%}
<div class="form-check form-switch my-2">
  <input class="form-check-input" type="checkbox" name="remember" value="1" {% if default %}checked{% endif %}>
  <label class="form-check-label small">Zapamiętaj w szablonie / słowniku dostawcy (inaczej — tylko ta faktura)</label>
</div>
{%- endmacro %}

{% macro pct(c) %}<span class="conf">{{ (c * 100)|round|int }}%</span>{% endmacro %}

{% macro issue_card(doc, idx, i, ctx) %}
<div class="card mb-3 issue-{{ i.severity }}">
  <div class="card-body">
    <div class="d-flex justify-content-between">
      <strong>{{ i.message }}</strong>
      <span class="badge text-bg-{{ 'danger' if i.severity == 'blocking' else 'warning' }}">{{ 'blokuje' if i.severity == 'blocking' else 'ostrzeżenie' }}</span>
    </div>
    {% if i.source_path %}<div class="small text-muted">Źródło: <code>{{ i.source_path }}</code>{% if i.source_value %} = „{{ i.source_value }}”{% endif %}</div>{% endif %}

    {% if i.code == 'unknown_supplier' %}
      {% set create = (i.suggestions | selectattr('kind', 'equalto', 'create_supplier') | first) %}
      {% for s in i.suggestions if s.kind == 'clone_template' %}<div class="alert alert-info small my-2">Struktura pliku pasuje do szablonu „{{ s.name }}” — jego reguły zostaną użyte dla nowego dostawcy.</div>{% endfor %}
      <div class="row g-3">
        <div class="col-md-6">
          {{ form_open(doc, 'create_supplier') }}
            <div class="small fw-semibold">Utwórz nowego dostawcę</div>
            <input class="form-control form-control-sm my-1" name="name" placeholder="Nazwa" value="{{ create.name if create else '' }}" required>
            <input class="form-control form-control-sm my-1" name="tax_id" placeholder="NIP / VAT" value="{{ create.tax_id if create and create.tax_id else '' }}">
            <button class="btn btn-sm btn-primary">Utwórz i zapamiętaj</button>
          </form>
        </div>
        <div class="col-md-6">
          {{ form_open(doc, 'use_supplier') }}
            <div class="small fw-semibold">…albo wskaż istniejącego</div>
            <select class="form-select form-select-sm my-1" name="supplier_id" required>
              {% for s in i.suggestions if s.kind == 'use_supplier' %}<option value="{{ s.supplier_id }}">★ {{ s.name }} ({{ (s.confidence*100)|round|int }}%)</option>{% endfor %}
              {% for s in ctx.suppliers %}<option value="{{ s.id }}">{{ s.name }}{% if s.tax_id %} — {{ s.tax_id }}{% endif %}</option>{% endfor %}
            </select>
            <button class="btn btn-sm btn-outline-primary" {% if not ctx.suppliers %}disabled{% endif %}>Przypisz</button>
          </form>
        </div>
      </div>

    {% elif i.code in ('unmapped_field', 'transform_error', 'invalid_value') and i.field %}
      {{ form_open(doc, 'map_field') }}
        <input type="hidden" name="issue" value="{{ idx }}">
        <div class="small fw-semibold">Pole: {{ ctx.field_labels.get(i.field, i.field) }}{% if i.line_no %} (pozycje){% endif %}</div>
        {% for s in i.suggestions %}
          <div class="form-check">
            <input class="form-check-input" type="radio" name="choice" value="s{{ loop.index0 }}" id="c{{ idx }}-{{ loop.index0 }}" {% if loop.first %}checked{% endif %}>
            <label class="form-check-label small" for="c{{ idx }}-{{ loop.index0 }}">
              {% if s.kind in ('path', 'line_path') %}<code>{{ s.path }}</code>{% if s.transforms %} → {{ s.transforms|tojson }}{% endif %}{% if s.preview %} = „{{ s.preview }}”{% endif %}
              {% else %}wartość domyślna: <strong>{{ s.value }}</strong>{% endif %}
              {{ pct(s.confidence) }} <span class="text-muted">· {{ s.reason }}</span>
            </label>
          </div>
        {% endfor %}
        <div class="form-check d-flex gap-2 align-items-center">
          <input class="form-check-input" type="radio" name="choice" value="manual_path" {% if not i.suggestions %}checked{% endif %}>
          <select class="form-select form-select-sm" name="manual_path">
            {% for p in ctx.leaf_paths %}<option>{{ p }}</option>{% endfor %}
          </select>
        </div>
        {% if not i.line_no and i.field != 'line_path' %}
        <div class="form-check d-flex gap-2 align-items-center">
          <input class="form-check-input" type="radio" name="choice" value="value">
          <input class="form-control form-control-sm" name="value" placeholder="stała wartość (np. PLN)">
        </div>
        {% endif %}
        {{ remember() }}
        <button class="btn btn-sm btn-primary">Zastosuj</button>
        <a class="btn btn-sm btn-link" href="{{ url_for('templates_views.editor_for_document', doc_id=doc.id) if 'templates_views' in nav_blueprints else '#' }}">Otwórz edytor mapowań</a>
      </form>

    {% elif i.code == 'unknown_unit' %}
      {{ form_open(doc, 'map_unit') }}
        <input type="hidden" name="alias" value="{{ i.source_value }}">
        <div class="d-flex gap-2 align-items-center">
          <span class="small">„{{ i.source_value }}” to u nas:</span>
          <select class="form-select form-select-sm w-auto" name="unit">
            {% for s in i.suggestions %}<option value="{{ s.unit }}">★ {{ s.unit }} ({{ (s.confidence*100)|round|int }}% · {{ s.reason }})</option>{% endfor %}
            {% for u in ctx.units %}<option value="{{ u.code }}">{{ u.code }} — {{ u.name }}</option>{% endfor %}
          </select>
        </div>
        {{ remember() }}
        <button class="btn btn-sm btn-primary">Zastosuj</button>
      </form>

    {% elif i.code == 'missing_conversion' %}
      {% set g = i.suggestions[0] if i.suggestions else {} %}
      {{ form_open(doc, 'add_conversion') }}
        <input type="hidden" name="from_unit" value="{{ i.source_value }}">
        <input type="hidden" name="line_no" value="{{ i.line_no }}">
        <div class="d-flex gap-2 align-items-center flex-wrap small">
          1 {{ i.source_value }} =
          <input class="form-control form-control-sm w-auto" name="factor" value="{{ g.factor or '' }}" placeholder="np. 12" required>
          <select class="form-select form-select-sm w-auto" name="to_unit">
            {% for u in ctx.units if u.is_base %}<option value="{{ u.code }}" {% if u.code == g.to_unit %}selected{% endif %}>{{ u.code }}</option>{% endfor %}
          </select>
          <select class="form-select form-select-sm w-auto" name="scope">
            <option value="supplier">dla wszystkich towarów dostawcy</option>
            <option value="product">tylko dla tego towaru</option>
          </select>
        </div>
        <button class="btn btn-sm btn-primary mt-2">Zapisz przelicznik</button>
      </form>

    {% elif i.code == 'unmapped_product' %}
      {% set create = (i.suggestions | selectattr('kind', 'equalto', 'create_product') | first) %}
      <div class="row g-3">
        <div class="col-md-6">
          {{ form_open(doc, 'map_product') }}
            <input type="hidden" name="line_no" value="{{ i.line_no }}">
            <select class="form-select form-select-sm" name="product_code">
              {% for s in i.suggestions if s.kind == 'product' %}<option value="{{ s.code }}">★ {{ s.code }} — {{ s.name }} ({{ (s.confidence*100)|round|int }}%)</option>{% endfor %}
              {% for p in ctx.products %}<option value="{{ p.code }}">{{ p.code }} — {{ p.name }}</option>{% endfor %}
            </select>
            {{ remember() }}
            <button class="btn btn-sm btn-primary">Przypisz towar</button>
          </form>
        </div>
        <div class="col-md-6">
          {{ form_open(doc, 'create_product') }}
            <input type="hidden" name="line_no" value="{{ i.line_no }}">
            <div class="small fw-semibold">…albo dodaj nowy towar do kartoteki</div>
            <input class="form-control form-control-sm my-1" name="code" value="{{ create.code if create else '' }}" required>
            <input class="form-control form-control-sm my-1" name="name" value="{{ create.name if create else '' }}" required>
            <select class="form-select form-select-sm my-1" name="unit">{% for u in ctx.units %}<option {% if create and u.code == create.unit %}selected{% endif %}>{{ u.code }}</option>{% endfor %}</select>
            {{ remember() }}
            <button class="btn btn-sm btn-outline-primary">Dodaj i przypisz</button>
          </form>
        </div>
      </div>

    {% elif i.code == 'duplicate' %}
      <div class="d-flex gap-2">
        {{ form_open(doc, 'allow_duplicate') }}<button class="btn btn-sm btn-outline-warning">To nie duplikat — przetwórz</button></form>
        {{ form_open(doc, 'reject') }}<button class="btn btn-sm btn-outline-danger">Odrzuć</button></form>
      </div>
    {% endif %}
  </div>
</div>
{% endmacro %}
```

`app/templates/document.html`:
```html
{% extends "base.html" %}
{% from "_issues.html" import issue_card with context %}
{% block title %}Dokument #{{ doc.id }}{% endblock %}
{% block content %}
<div class="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-2">
  <div>
    <h1 class="h4 m-0">Dokument #{{ doc.id }} <span class="badge text-bg-{{ {'approved':'success','needs_review':'warning','duplicate':'secondary','rejected':'danger'}.get(doc.status,'light') }}">{{ doc.status_label }}</span></h1>
    <div class="small text-muted">{{ doc.filename }} · {{ (doc.fmt or '?')|upper }} · dostawca: {{ doc.supplier.name if doc.supplier else 'nierozpoznany' }}
      {% if doc.template_version %} · szablon „{{ doc.template.name }}” v{{ doc.template_version.version }}{% elif doc.draft_rules %} · reguły robocze (szablon powstanie po rozpoznaniu dostawcy){% endif %}</div>
  </div>
  <div class="d-flex gap-2">
    <form method="post" action="{{ url_for('docs.reprocess', doc_id=doc.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-secondary">Przetwórz ponownie</button></form>
    <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('docs.as_json', doc_id=doc.id) }}">JSON</a>
    <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('docs.raw', doc_id=doc.id) }}">Plik źródłowy</a>
  </div>
</div>

{% set ctx = {'field_labels': field_labels, 'leaf_paths': leaf_paths, 'units': units, 'products': products, 'suppliers': suppliers} %}
{% if doc.issues %}
<h2 class="h6">Problemy ({{ doc.issues|length }}) — rozwiąż je po kolei, od góry</h2>
{% for i in doc.issues %}{{ issue_card(doc, loop.index0, i, ctx) }}{% endfor %}
{% else %}
<div class="alert alert-success">Faktura odczytana bez problemów.</div>
{% endif %}

<div class="row g-3">
  <div class="col-lg-5">
    <h2 class="h6">Plik źródłowy</h2>
    <div class="card card-body p-2" style="max-height: 70vh; overflow: auto">
      {% for r in rows %}<div class="tree-row" style="padding-left: {{ r.depth * 12 }}px" title="{{ r.path }}">{{ r.name }}{% if r.value %}: <span class="val">{{ r.value }}</span>{% endif %}</div>{% endfor %}
    </div>
  </div>
  <div class="col-lg-7">
    <h2 class="h6">Wynik (format kanoniczny)</h2>
    {% if doc.result %}
    <table class="table table-sm bg-white small">
      {% for f in header_fields %}{% set parts = f.key.split('.') %}{% set ns = namespace(v=doc.result) %}{% for p in parts %}{% set ns.v = ns.v[p] if ns.v is mapping and p in ns.v else none %}{% endfor %}
      <tr><th class="w-50">{{ f.label }}</th><td>{% if ns.v is iterable and ns.v is not string %}{{ ns.v|join(', ') }}{% else %}{{ ns.v if ns.v is not none else '—' }}{% endif %}</td></tr>{% endfor %}
    </table>
    <div class="table-responsive">
    <table class="table table-sm bg-white small">
      <thead><tr><th>#</th><th>Indeks</th>{% for f in line_fields %}<th>{{ f.label }}</th>{% endfor %}<th>JM źródłowa</th><th>Przelicznik</th></tr></thead>
      <tbody>{% for l in doc.result.lines %}<tr><td>{{ l.line_no }}</td><td>{{ l.product_index or '—' }}</td>{% for f in line_fields %}<td>{{ l[f.key] if l[f.key] is not none else '—' }}</td>{% endfor %}<td>{{ l.unit_source or '—' }}</td><td>{{ l.conversion_factor }}</td></tr>{% endfor %}</tbody>
    </table>
    </div>
    {% endif %}
  </div>
</div>
{% endblock %}
```

Uwaga: link do edytora w `_issues.html` zadziała po Task 16. Do tego czasu `nav_blueprints` nie zawiera `templates_views`, więc renderuje się `#`.

- [ ] **Step 5: PASS:** `pytest tests/test_web_documents.py -q`, potem całość: `pytest -q`.

- [ ] **Step 6: Commit**
```bash
git add app/web app/templates app/__init__.py app/services/seed.py tests
pytest tests/test_no_private_data.py -q
git commit -m "feat(panel): logowanie, pulpit, upload, kolejka i kreator negocjacji

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 15: CRUD danych (dostawcy, towary, mapowania, jednostki, aliasy, przeliczniki), import CSV, klucze API, historia

**Files:**
- Create: `app/web/crud.py`, `app/web/catalog.py`, `app/web/apikeys.py`, `app/web/history.py`
- Create: `app/templates/crud_list.html`, `crud_form.html`, `products_import.html`, `apikeys.html`, `history.html`
- Test: `tests/test_web_catalog.py`

**Interfaces:**
- Consumes: modele (Task 10), `create_key` (Task 10), `audit` (Task 10), `normalize_gtin` (Task 5), `norm_alias` (Task 6).
- Produces:
  - `CrudField(name, label, type="text", required=False, choices=None)` (typy: `text`, `number`, `checkbox`, `select`, `textarea`), `CrudSpec(key, model, title, url, fields, columns, order_by, before_save=None, delete_blocker=None)`, `register_crud(bp, spec)`. Endpointy: `catalog.list_<key>`, `catalog.new_<key>`, `catalog.edit_<key>`, `catalog.delete_<key>`.
  - Klucze: `suppliers` (`/dostawcy`), `products` (`/towary`), `mappings` (`/mapowania-towarow`), `units` (`/jednostki`), `aliases` (`/aliasy-jednostek`), `conversions` (`/przeliczniki`).
  - `catalog.import_products` (`GET|POST /towary/import`) — CSV z kolumnami `indeks;nazwa;gtin;jednostka` (akceptowane też `code/name/ean/jm/unit`); upsert po indeksie.
  - Blueprint `apikeys` (`/klucze-api`: lista, `POST /klucze-api/nowy`, `POST /klucze-api/<id>/przelacz`, `POST /klucze-api/<id>/nazwa`, `POST /klucze-api/<id>/usun`), blueprint `history` (`/historia`).

- [ ] **Step 1: Testy**

`tests/test_web_catalog.py`:
```python
import io

from app.extensions import db
from app.models import ApiKey, AuditLog, Product, Supplier, Unit, UnitAlias


def test_supplier_crud(auth_client):
    r = auth_client.post("/dostawcy/nowy", data={"name": "Testowy", "tax_id": "PL1", "notes": ""},
                         follow_redirects=True)
    assert "Testowy" in r.get_data(as_text=True)
    s = Supplier.query.one()
    auth_client.post(f"/dostawcy/{s.id}/edycja", data={"name": "Testowy 2", "tax_id": "PL1", "notes": "x"})
    assert Supplier.query.one().name == "Testowy 2"
    html = auth_client.get("/dostawcy").get_data(as_text=True)
    assert "Edytuj" in html and "Usuń" in html
    auth_client.post(f"/dostawcy/{s.id}/usun")
    assert Supplier.query.count() == 0


def test_alias_edit_updates_norm(auth_client):
    szt = Unit.query.filter_by(code="szt").one()
    auth_client.post("/aliasy-jednostek/nowy", data={"alias": "PCS", "unit_id": szt.id, "supplier_id": ""})
    a = UnitAlias.query.filter_by(alias="PCS").one()
    assert a.alias_norm == "pcs" and a.supplier_id is None
    auth_client.post(f"/aliasy-jednostek/{a.id}/edycja", data={"alias": "Pc", "unit_id": szt.id, "supplier_id": ""})
    assert db.session.get(UnitAlias, a.id).alias_norm == "pc"


def test_delete_blocked_when_in_use(auth_client):
    szt = Unit.query.filter_by(code="szt").one()
    r = auth_client.post(f"/jednostki/{szt.id}/usun", follow_redirects=True)
    assert "Nie można usunąć" in r.get_data(as_text=True)
    assert Unit.query.filter_by(code="szt").count() == 1


def test_product_validation_and_import(auth_client):
    r = auth_client.post("/towary/nowy", data={"code": "X-1", "name": "Zły GTIN", "gtin": "123", "unit_id": ""},
                         follow_redirects=True)
    assert "Niepoprawny GTIN" in r.get_data(as_text=True)
    csv_data = "indeks;nazwa;gtin;jednostka\nTOW-0001;Posypka (zmiana);5909999000013;szt\nNOWY-1;Cukier puder;;kg\nZLY;Zły;111;szt\n"
    r = auth_client.post("/towary/import", data={"file": (io.BytesIO(csv_data.encode()), "t.csv")},
                         content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Dodano: 1" in html and "Zaktualizowano: 1" in html and "Błędy: 1" in html
    assert Product.query.filter_by(code="TOW-0001").one().name == "Posypka (zmiana)"
    assert Product.query.filter_by(code="NOWY-1").one().unit.code == "kg"


def test_api_keys_page(auth_client):
    r = auth_client.post("/klucze-api/nowy", data={"name": "ERP"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    key = ApiKey.query.filter_by(name="ERP").one()
    assert "xp_" in html and "Skopiuj teraz" in html
    auth_client.post(f"/klucze-api/{key.id}/przelacz")
    assert db.session.get(ApiKey, key.id).active is False
    auth_client.post(f"/klucze-api/{key.id}/nazwa", data={"name": "ERP 2"})
    assert db.session.get(ApiKey, key.id).name == "ERP 2"
    auth_client.post(f"/klucze-api/{key.id}/usun")
    assert ApiKey.query.filter_by(name="ERP 2").count() == 0


def test_history_lists_audit(auth_client):
    auth_client.post("/dostawcy/nowy", data={"name": "Audytowany", "tax_id": "", "notes": ""})
    assert AuditLog.query.filter_by(action="create", entity="suppliers").count() == 1
    assert "Audytowany" in auth_client.get("/historia").get_data(as_text=True)
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: `app/web/crud.py`**

```python
"""Ogólny CRUD dla prostych tabel słownikowych (lista + formularz + edycja + usuwanie)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.engine.values import to_decimal
from app.extensions import db
from app.services.audit import audit


@dataclass
class CrudField:
    name: str
    label: str
    type: str = "text"
    required: bool = False
    choices: Callable[[], list[tuple[Any, str]]] | None = None


@dataclass
class CrudSpec:
    key: str
    model: type
    title: str
    url: str
    fields: list[CrudField]
    columns: list[tuple[str, Callable[[Any], Any]]]
    order_by: Callable[[], Any]
    before_save: Callable[[Any], None] | None = None      # rzuca ValueError z komunikatem PL
    delete_blocker: Callable[[Any], str | None] | None = None
    extra_actions: list[tuple[str, str]] = field(default_factory=list)  # (etykieta, endpoint)


def _parse(f: CrudField, raw: str | None):
    raw = (raw or "").strip()
    if f.type == "checkbox":
        return raw in ("1", "on", "true")
    if raw == "":
        if f.required:
            raise ValueError(f"Pole „{f.label}” jest wymagane.")
        return None
    if f.type == "number":
        return to_decimal(raw)
    if f.type == "select":
        return int(raw) if raw.isdigit() else raw
    return raw


def _snapshot(obj, spec: CrudSpec) -> dict:
    out = {}
    for f in spec.fields:
        v = getattr(obj, f.name)
        out[f.name] = str(v) if isinstance(v, Decimal) else v
    return out


def register_crud(bp, spec: CrudSpec) -> None:
    def list_view():
        rows = spec.model.query.order_by(spec.order_by()).all()
        return render_template("crud_list.html", spec=spec, rows=rows)

    def form_view(obj_id: int | None = None):
        obj = db.session.get(spec.model, obj_id) if obj_id else spec.model()
        if obj is None:
            flash("Nie znaleziono rekordu.", "error")
            return redirect(url_for(f"catalog.list_{spec.key}"))
        if request.method == "POST":
            try:
                for f in spec.fields:
                    setattr(obj, f.name, _parse(f, request.form.get(f.name)))
                if spec.before_save:
                    spec.before_save(obj)
                if obj_id is None:
                    db.session.add(obj)
                db.session.flush()
                audit("update" if obj_id else "create", spec.key, obj.id, _snapshot(obj, spec))
                db.session.commit()
                flash("Zapisano.", "success")
                return redirect(url_for(f"catalog.list_{spec.key}"))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
            except Exception:  # noqa: BLE001 — np. naruszenie unikalności
                db.session.rollback()
                flash("Nie udało się zapisać — sprawdź, czy wartość nie jest zduplikowana.", "error")
        return render_template("crud_form.html", spec=spec, obj=obj, is_new=obj_id is None)

    def delete_view(obj_id: int):
        obj = db.session.get(spec.model, obj_id)
        if obj is not None:
            reason = spec.delete_blocker(obj) if spec.delete_blocker else None
            if reason:
                flash(f"Nie można usunąć: {reason}", "error")
            else:
                audit("delete", spec.key, obj.id, _snapshot(obj, spec))
                db.session.delete(obj)
                db.session.commit()
                flash("Usunięto.", "success")
        return redirect(url_for(f"catalog.list_{spec.key}"))

    bp.add_url_rule(spec.url, f"list_{spec.key}", login_required(list_view))
    bp.add_url_rule(f"{spec.url}/nowy", f"new_{spec.key}", login_required(form_view), methods=["GET", "POST"])
    bp.add_url_rule(f"{spec.url}/<int:obj_id>/edycja", f"edit_{spec.key}", login_required(form_view),
                    methods=["GET", "POST"])
    bp.add_url_rule(f"{spec.url}/<int:obj_id>/usun", f"delete_{spec.key}", login_required(delete_view),
                    methods=["POST"])
```

- [ ] **Step 4: `app/web/catalog.py`**

```python
import csv
import io

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.engine.lookups import norm_alias
from app.engine.values import normalize_gtin
from app.extensions import db
from app.models import Document, Product, ProductMapping, Supplier, Template, Unit, UnitAlias, UnitConversion
from app.services.audit import audit

from .crud import CrudField, CrudSpec, register_crud

bp = Blueprint("catalog", __name__)


def unit_choices():
    return [(u.id, f"{u.code} — {u.name}") for u in Unit.query.order_by(Unit.code)]


def supplier_choices():
    return [("", "— wszyscy dostawcy (globalnie) —")] + [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name)]


def product_choices():
    return [("", "— wszystkie towary —")] + [(p.id, f"{p.code} — {p.name}") for p in Product.query.order_by(Product.code)]


def _product_before_save(p: Product):
    if p.gtin:
        normalize_gtin(p.gtin)  # tylko walidacja; DbLookups porównuje po zfill(14)


def _alias_before_save(a: UnitAlias):
    a.alias_norm = norm_alias(a.alias)


def _unit_before_save(u: Unit):
    u.code = (u.code or "").strip().lower()


def _conversion_before_save(c: UnitConversion):
    if c.factor is None or c.factor <= 0:
        raise ValueError("Przelicznik musi być większy od zera.")


def _mapping_before_save(m: ProductMapping):
    if not m.supplier_code and not m.supplier_gtin:
        raise ValueError("Podaj kod lub GTIN towaru u dostawcy.")
    if m.supplier_gtin:
        m.supplier_gtin = normalize_gtin(m.supplier_gtin)


def _supplier_blocker(s):
    if Document.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma przypisane dokumenty."
    if Template.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma szablony."
    return None


def _unit_blocker(u):
    used = (UnitAlias.query.filter_by(unit_id=u.id).count() + Product.query.filter_by(unit_id=u.id).count()
            + UnitConversion.query.filter((UnitConversion.from_unit_id == u.id) | (UnitConversion.to_unit_id == u.id)).count())
    return "jednostka jest używana (aliasy, towary lub przeliczniki)." if used else None


def _product_blocker(p):
    return "towar ma mapowania dostawców." if ProductMapping.query.filter_by(product_id=p.id).count() else None


SPECS = [
    CrudSpec("suppliers", Supplier, "Dostawcy", "/dostawcy",
             [CrudField("name", "Nazwa", required=True), CrudField("tax_id", "NIP / VAT"),
              CrudField("notes", "Notatki", "textarea")],
             [("Nazwa", lambda s: s.name), ("NIP / VAT", lambda s: s.tax_id or "—"),
              ("Szablony", lambda s: len(s.templates))],
             lambda: Supplier.name, delete_blocker=_supplier_blocker),
    CrudSpec("products", Product, "Kartoteka towarów", "/towary",
             [CrudField("code", "Indeks", required=True), CrudField("name", "Nazwa", required=True),
              CrudField("gtin", "GTIN / EAN"),
              CrudField("unit_id", "Jednostka", "select", choices=lambda: [("", "—")] + unit_choices())],
             [("Indeks", lambda p: p.code), ("Nazwa", lambda p: p.name), ("GTIN", lambda p: p.gtin or "—"),
              ("JM", lambda p: p.unit.code if p.unit else "—")],
             lambda: Product.code, before_save=_product_before_save, delete_blocker=_product_blocker,
             extra_actions=[("Import CSV", "catalog.import_products")]),
    CrudSpec("mappings", ProductMapping, "Mapowania towarów dostawców", "/mapowania-towarow",
             [CrudField("supplier_id", "Dostawca", "select", True,
                        lambda: [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name)]),
              CrudField("supplier_code", "Kod u dostawcy"), CrudField("supplier_gtin", "GTIN u dostawcy"),
              CrudField("product_id", "Nasz towar", "select", True,
                        lambda: [(p.id, f"{p.code} — {p.name}") for p in Product.query.order_by(Product.code)])],
             [("Dostawca", lambda m: m.supplier.name), ("Kod", lambda m: m.supplier_code or "—"),
              ("GTIN", lambda m: m.supplier_gtin or "—"), ("Nasz towar", lambda m: f"{m.product.code} — {m.product.name}")],
             lambda: ProductMapping.id, before_save=_mapping_before_save),
    CrudSpec("units", Unit, "Jednostki miary", "/jednostki",
             [CrudField("code", "Kod", required=True), CrudField("name", "Nazwa", required=True),
              CrudField("is_base", "Jednostka bazowa (bez przelicznika)", "checkbox")],
             [("Kod", lambda u: u.code), ("Nazwa", lambda u: u.name), ("Bazowa", lambda u: "tak" if u.is_base else "nie")],
             lambda: Unit.code, before_save=_unit_before_save, delete_blocker=_unit_blocker),
    CrudSpec("aliases", UnitAlias, "Aliasy jednostek", "/aliasy-jednostek",
             [CrudField("alias", "Jednostka w pliku dostawcy", required=True),
              CrudField("unit_id", "Nasza jednostka", "select", True, unit_choices),
              CrudField("supplier_id", "Dostawca", "select", choices=supplier_choices)],
             [("Alias", lambda a: a.alias), ("Jednostka", lambda a: a.unit.code),
              ("Dostawca", lambda a: a.supplier.name if a.supplier else "wszyscy")],
             lambda: UnitAlias.alias_norm, before_save=_alias_before_save),
    CrudSpec("conversions", UnitConversion, "Przeliczniki jednostek", "/przeliczniki",
             [CrudField("from_unit_id", "Z jednostki", "select", True, unit_choices),
              CrudField("factor", "Współczynnik (1 z = X do)", "number", True),
              CrudField("to_unit_id", "Na jednostkę", "select", True, unit_choices),
              CrudField("supplier_id", "Dostawca", "select", choices=supplier_choices),
              CrudField("product_id", "Towar", "select", choices=product_choices)],
             [("Przelicznik", lambda c: f"1 {c.from_unit.code} = {c.factor.normalize()} {c.to_unit.code}"),
              ("Dostawca", lambda c: c.supplier.name if c.supplier else "wszyscy"),
              ("Towar", lambda c: c.product.code if c.product else "wszystkie")],
             lambda: UnitConversion.id, before_save=_conversion_before_save),
]
for _spec in SPECS:
    register_crud(bp, _spec)

COLS = {"code": ("indeks", "code", "kod"), "name": ("nazwa", "name"), "gtin": ("gtin", "ean"),
        "unit": ("jednostka", "jm", "unit")}


@bp.route("/towary/import", methods=["GET", "POST"])
@login_required
def import_products():
    report = None
    if request.method == "POST":
        f = request.files.get("file")
        raw = f.read() if f else b""
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1250", errors="replace")
        try:
            delim = csv.Sniffer().sniff(text[:2048], delimiters=";,\t").delimiter
        except csv.Error:
            delim = ";"
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        heads = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        col = {k: next((heads[a] for a in aliases if a in heads), None) for k, aliases in COLS.items()}
        units = {u.code: u for u in Unit.query.all()}
        report = {"added": 0, "updated": 0, "errors": []}
        if not col["code"] or not col["name"]:
            report["errors"].append("Brak kolumn „indeks” i „nazwa” w nagłówku.")
        else:
            for n, row in enumerate(reader, start=2):
                code, name = (row.get(col["code"]) or "").strip(), (row.get(col["name"]) or "").strip()
                if not code or not name:
                    continue
                gtin = (row.get(col["gtin"]) or "").strip() if col["gtin"] else ""
                if gtin:
                    try:
                        normalize_gtin(gtin)
                    except ValueError as exc:
                        report["errors"].append(f"Wiersz {n}: {exc}")
                        continue
                unit = units.get(((row.get(col["unit"]) or "").strip().lower()) if col["unit"] else "")
                p = Product.query.filter_by(code=code).first()
                if p:
                    p.name, p.gtin = name, gtin or p.gtin
                    p.unit_id = unit.id if unit else p.unit_id
                    report["updated"] += 1
                else:
                    db.session.add(Product(code=code, name=name, gtin=gtin or None, unit_id=unit.id if unit else None))
                    report["added"] += 1
            audit("import", "products", None, {k: v for k, v in report.items() if k != "errors"})
            db.session.commit()
        flash(f"Dodano: {report['added']} · Zaktualizowano: {report['updated']} · Błędy: {len(report['errors'])}",
              "info")
    return render_template("products_import.html", report=report)
```

`app/web/apikeys.py`:
```python
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import ApiKey, Document
from app.services.apikeys import create_key
from app.services.audit import audit

bp = Blueprint("apikeys", __name__, url_prefix="/klucze-api")


@bp.get("")
@login_required
def index():
    return render_template("apikeys.html", keys=ApiKey.query.order_by(ApiKey.id).all(), new_key=None)


@bp.post("/nowy")
@login_required
def create():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Podaj nazwę klucza (np. nazwa systemu).", "error")
        return redirect(url_for("apikeys.index"))
    key, plain = create_key(name)
    audit("create", "api_key", key.id, {"name": name, "prefix": key.prefix})
    db.session.commit()
    return render_template("apikeys.html", keys=ApiKey.query.order_by(ApiKey.id).all(), new_key=plain)


@bp.post("/<int:key_id>/przelacz")
@login_required
def toggle(key_id):
    key = db.session.get(ApiKey, key_id)
    if key:
        key.active = not key.active
        audit("toggle", "api_key", key.id, {"active": key.active})
        db.session.commit()
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/nazwa")
@login_required
def rename(key_id):
    key = db.session.get(ApiKey, key_id)
    name = (request.form.get("name") or "").strip()
    if key and name:
        key.name = name
        audit("update", "api_key", key.id, {"name": name})
        db.session.commit()
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/usun")
@login_required
def delete(key_id):
    key = db.session.get(ApiKey, key_id)
    if key:
        Document.query.filter_by(api_key_id=key.id).update({Document.api_key_id: None})
        audit("delete", "api_key", key.id, {"name": key.name})
        db.session.delete(key)
        db.session.commit()
    return redirect(url_for("apikeys.index"))
```

`app/web/history.py`:
```python
from flask import Blueprint, render_template
from flask_login import login_required

from app.models import AuditLog

bp = Blueprint("history", __name__, url_prefix="/historia")


@bp.get("")
@login_required
def index():
    return render_template("history.html", rows=AuditLog.query.order_by(AuditLog.id.desc()).limit(300).all())
```

- [ ] **Step 5: Szablony**

`app/templates/crud_list.html`:
```html
{% extends "base.html" %}
{% block title %}{{ spec.title }}{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4 m-0">{{ spec.title }}</h1>
  <div class="d-flex gap-2">
    {% for label, endpoint in spec.extra_actions %}<a class="btn btn-sm btn-outline-secondary" href="{{ url_for(endpoint) }}">{{ label }}</a>{% endfor %}
    <a class="btn btn-sm btn-primary" href="{{ url_for('catalog.new_' ~ spec.key) }}">Dodaj</a>
  </div>
</div>
<table class="table table-sm table-hover bg-white">
  <thead><tr>{% for label, _ in spec.columns %}<th>{{ label }}</th>{% endfor %}<th class="text-end">Akcje</th></tr></thead>
  <tbody>
  {% for row in rows %}
    <tr>
      {% for _, getter in spec.columns %}<td>{{ getter(row) }}</td>{% endfor %}
      <td class="text-end text-nowrap">
        <a class="btn btn-sm btn-outline-primary" href="{{ url_for('catalog.edit_' ~ spec.key, obj_id=row.id) }}">Edytuj</a>
        <form method="post" action="{{ url_for('catalog.delete_' ~ spec.key, obj_id=row.id) }}" class="d-inline" onsubmit="return confirm('Usunąć?')">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <button class="btn btn-sm btn-outline-danger">Usuń</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="{{ spec.columns|length + 1 }}" class="text-muted">Brak rekordów.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```
Uwaga: test „Usuń” w liście CRUD sprawdza tylko obecność przycisku. `confirm()` to akceptowalny natywny dialog w panelu (nie w automatyzacji przeglądarki).

`app/templates/crud_form.html`:
```html
{% extends "base.html" %}
{% block title %}{{ spec.title }}{% endblock %}
{% block content %}
<h1 class="h4 mb-3">{{ spec.title }} — {{ 'nowy rekord' if is_new else 'edycja' }}</h1>
<form method="post" class="card card-body" style="max-width: 640px">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  {% for f in spec.fields %}
    {% set val = obj|attr(f.name) %}
    <div class="mb-2">
      {% if f.type == 'checkbox' %}
        <div class="form-check"><input class="form-check-input" type="checkbox" name="{{ f.name }}" value="1" id="f-{{ f.name }}" {% if val %}checked{% endif %}><label class="form-check-label" for="f-{{ f.name }}">{{ f.label }}</label></div>
      {% else %}
        <label class="form-label small mb-0" for="f-{{ f.name }}">{{ f.label }}{% if f.required %} *{% endif %}</label>
        {% if f.type == 'select' %}
          <select class="form-select form-select-sm" name="{{ f.name }}" id="f-{{ f.name }}" {% if f.required %}required{% endif %}>
            {% for value, label in f.choices() %}<option value="{{ value }}" {% if value == val %}selected{% endif %}>{{ label }}</option>{% endfor %}
          </select>
        {% elif f.type == 'textarea' %}
          <textarea class="form-control form-control-sm" name="{{ f.name }}" id="f-{{ f.name }}" rows="3">{{ val or '' }}</textarea>
        {% else %}
          <input class="form-control form-control-sm" name="{{ f.name }}" id="f-{{ f.name }}" value="{{ val if val is not none else '' }}" {% if f.required %}required{% endif %}>
        {% endif %}
      {% endif %}
    </div>
  {% endfor %}
  <div class="d-flex gap-2"><button class="btn btn-primary btn-sm">Zapisz</button>
    <a class="btn btn-link btn-sm" href="{{ url_for('catalog.list_' ~ spec.key) }}">Anuluj</a></div>
</form>
{% endblock %}
```
Pusta opcja dla pól niewymaganych pochodzi z `choices()` (np. `supplier_choices` zaczyna się od `("", "— wszyscy dostawcy (globalnie) —")`).

`app/templates/products_import.html`:
```html
{% extends "base.html" %}
{% block title %}Import towarów{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Import kartoteki towarów (CSV)</h1>
<p class="small text-muted">Nagłówek: <code>indeks;nazwa;gtin;jednostka</code> (separator <code>;</code> lub <code>,</code>, UTF-8 lub Windows-1250). Istniejące indeksy są aktualizowane.</p>
<form method="post" enctype="multipart/form-data" class="card card-body mb-3" style="max-width: 640px">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <input class="form-control mb-2" type="file" name="file" accept=".csv,.txt" required>
  <button class="btn btn-primary btn-sm">Importuj</button>
</form>
{% if report and report.errors %}<div class="alert alert-warning small"><strong>Błędy:</strong><ul class="mb-0">{% for e in report.errors %}<li>{{ e }}</li>{% endfor %}</ul></div>{% endif %}
<a href="{{ url_for('catalog.list_products') }}">← Kartoteka towarów</a>
{% endblock %}
```

`app/templates/apikeys.html`:
```html
{% extends "base.html" %}
{% block title %}Klucze API{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Klucze API</h1>
{% if new_key %}
<div class="alert alert-success"><strong>Nowy klucz — Skopiuj teraz, nie pokażemy go ponownie:</strong><br><code class="user-select-all">{{ new_key }}</code></div>
{% endif %}
<form method="post" action="{{ url_for('apikeys.create') }}" class="d-flex gap-2 mb-3" style="max-width: 520px">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <input class="form-control form-control-sm" name="name" placeholder="Nazwa (np. ERP, magazyn)" required>
  <button class="btn btn-primary btn-sm text-nowrap">Utwórz klucz</button>
</form>
<table class="table table-sm bg-white">
  <thead><tr><th>Nazwa</th><th>Prefiks</th><th>Aktywny</th><th>Ostatnio użyty</th><th class="text-end">Akcje</th></tr></thead>
  <tbody>{% for k in keys %}
  <tr>
    <td><form method="post" action="{{ url_for('apikeys.rename', key_id=k.id) }}" class="d-flex gap-1"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input class="form-control form-control-sm" name="name" value="{{ k.name }}"><button class="btn btn-sm btn-outline-primary">Edytuj</button></form></td>
    <td><code>{{ k.prefix }}…</code></td><td>{{ 'tak' if k.active else 'nie' }}</td>
    <td class="small">{{ k.last_used_at.strftime('%Y-%m-%d %H:%M') if k.last_used_at else '—' }}</td>
    <td class="text-end text-nowrap">
      <form method="post" action="{{ url_for('apikeys.toggle', key_id=k.id) }}" class="d-inline"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-secondary">{{ 'Wyłącz' if k.active else 'Włącz' }}</button></form>
      <form method="post" action="{{ url_for('apikeys.delete', key_id=k.id) }}" class="d-inline" onsubmit="return confirm('Usunąć klucz?')"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-danger">Usuń</button></form>
    </td>
  </tr>{% endfor %}</tbody>
</table>
{% endblock %}
```

`app/templates/history.html`:
```html
{% extends "base.html" %}
{% block title %}Historia{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Historia zmian</h1>
<table class="table table-sm bg-white small">
  <thead><tr><th>Kiedy</th><th>Kto</th><th>Akcja</th><th>Obiekt</th><th>Szczegóły</th></tr></thead>
  <tbody>{% for r in rows %}
    <tr><td class="text-nowrap">{{ r.created_at.strftime('%Y-%m-%d %H:%M:%S') }}</td><td>{{ r.user }}</td><td>{{ r.action }}</td>
      <td>{% if r.entity == 'document' and r.entity_id %}<a href="{{ url_for('docs.detail', doc_id=r.entity_id) }}">dokument #{{ r.entity_id }}</a>{% else %}{{ r.entity }}{% if r.entity_id %} #{{ r.entity_id }}{% endif %}{% endif %}</td>
      <td><code class="small">{{ r.payload|tojson }}</code></td></tr>
  {% else %}<tr><td colspan="5" class="text-muted">Brak wpisów.</td></tr>{% endfor %}</tbody>
</table>
{% endblock %}
```
Uwaga: `tojson` escapuje znaki spoza ASCII jako `\uXXXX`. W `test_history_lists_audit` nazwa „Audytowany” jest ASCII, więc test przejdzie.

- [ ] **Step 6: PASS:** `pytest tests/test_web_catalog.py -q && pytest -q`

- [ ] **Step 7: Commit**
```bash
git add app/web app/templates tests/test_web_catalog.py
pytest tests/test_no_private_data.py -q
git commit -m "feat(panel): CRUD słowników i kartoteki, import CSV, klucze API, historia

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 16: Szablony — wersje, diff, przywracanie + pełnoekranowy edytor mapowań

**Files:**
- Create: `app/web/templates_views.py`, `app/templates/templates_list.html`, `app/templates/template_detail.html`, `app/templates/editor.html`, `app/static/editor.js`
- Test: `tests/test_web_templates.py`

**Interfaces:**
- Consumes: `new_version` (Task 10), `load_tree`, `current_rules`, `process` (Task 11), `apply_template` (Task 7), `validate_invoice` (Task 8), `field_candidates`, `load_synonyms`, `learned_pairs` (Task 9), `TRANSFORM_LABELS` (Task 5), `HEADER_FIELDS`, `LINE_FIELDS` (Task 6), `DbLookups`, `audit`.
- Produces: blueprint `templates_views` z prefiksem `/szablony`:
  - `GET ""` → `index`
  - `GET /<tid>` → `detail` (param. `?a=<ver_id>&b=<ver_id>` → diff)
  - `POST /<tid>/przywroc/<vid>` → `restore`
  - `POST /<tid>/usun` → `delete`
  - `GET /<tid>/edytor` → `editor_for_template`
  - `GET /dokument/<doc_id>/edytor` → `editor_for_document`
  - `POST /dokument/<doc_id>/podglad` (JSON `{rules}` → `{invoice, issues}`) → `preview`
  - `POST /dokument/<doc_id>/zapisz` (JSON `{rules, comment}` → `{ok, status, redirect}`) → `save`

  Żądania JSON z edytora wysyłają nagłówek `X-CSRFToken`.

- [ ] **Step 1: Testy**

`tests/test_web_templates.py`:
```python
from app.extensions import db
from app.models import Document, Template
from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def make_doc_with_template():
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    return d


def test_list_detail_and_diff(auth_client):
    d = make_doc_with_template()
    resolve(d, "map_field", {"field": "currency", "value": "PLN"}, True, "admin")
    t = Template.query.one()
    assert "Hurtownia Alfa" in auth_client.get("/szablony").get_data(as_text=True)
    v1, v2 = t.versions
    html = auth_client.get(f"/szablony/{t.id}?a={v1.id}&b={v2.id}").get_data(as_text=True)
    assert "+" in html and "PLN" in html and "v2" in html


def test_restore_creates_new_version(auth_client):
    d = make_doc_with_template()
    resolve(d, "map_field", {"field": "currency", "value": "PLN"}, True, "admin")
    t = Template.query.one()
    v1 = t.versions[0]
    auth_client.post(f"/szablony/{t.id}/przywroc/{v1.id}")
    db.session.refresh(t)
    assert t.active_version.version == 3 and t.active_version.rules == v1.rules
    assert "Przywrócono wersję 1" in t.active_version.comment


def test_editor_renders_full_screen_without_footer(auth_client):
    d = make_doc_with_template()
    html = auth_client.get(f"/szablony/dokument/{d.id}/edytor").get_data(as_text=True)
    assert "Edytor mapowań" in html and "TowarKodEan128" in html
    assert "Project &amp; Development" not in html


def test_preview_and_save(auth_client):
    d = make_doc_with_template()
    rules = Template.query.one().active_version.rules
    rules = {**rules, "defaults": {"currency": "EUR"}}
    r = auth_client.post(f"/szablony/dokument/{d.id}/podglad", json={"rules": rules})
    body = r.get_json()
    assert r.status_code == 200 and body["invoice"]["currency"] == "EUR"
    assert all(i["field"] != "currency" for i in body["issues"])
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": rules, "comment": "Waluta EUR"})
    assert r.get_json()["ok"] is True
    t = Template.query.one()
    assert t.active_version.version == 2 and t.active_version.comment == "Waluta EUR"
    assert db.session.get(Document, d.id).result["currency"] == "EUR"


def test_preview_rejects_bad_rules(auth_client):
    d = make_doc_with_template()
    r = auth_client.post(f"/szablony/dokument/{d.id}/podglad", json={"rules": "nie-słownik"})
    assert r.status_code == 400


def test_delete_blocked_when_documents(auth_client):
    make_doc_with_template()
    t = Template.query.one()
    r = auth_client.post(f"/szablony/{t.id}/usun", follow_redirects=True)
    assert "Nie można usunąć" in r.get_data(as_text=True)
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: `app/web/templates_views.py`**

```python
import difflib
import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.engine.canonical import HEADER_FIELDS, LINE_FIELDS
from app.engine.suggest import field_candidates, learned_pairs, load_synonyms
from app.engine.template import apply_template
from app.engine.transforms import TRANSFORM_LABELS
from app.engine.validate import validate_invoice
from app.extensions import db
from app.ingest import ReaderError
from app.models import Document, Template, TemplateVersion
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.pipeline import current_rules, load_tree, process
from app.services.templates import active_rule_sets, new_version

bp = Blueprint("templates_views", __name__, url_prefix="/szablony")


def _tpl(tid: int) -> Template:
    t = db.session.get(Template, tid)
    if not t:
        abort(404)
    return t


def _doc(doc_id: int) -> Document:
    d = db.session.get(Document, doc_id)
    if not d:
        abort(404)
    return d


@bp.get("")
@login_required
def index():
    rows = []
    for t in Template.query.order_by(Template.id).all():
        rows.append({"t": t, "docs": Document.query.filter_by(template_id=t.id).count(),
                     "active": t.active_version})
    return render_template("templates_list.html", rows=rows)


@bp.get("/<int:tid>")
@login_required
def detail(tid):
    t = _tpl(tid)
    diff = None
    a, b = request.args.get("a", type=int), request.args.get("b", type=int)
    if a and b:
        va, vb = db.session.get(TemplateVersion, a), db.session.get(TemplateVersion, b)
        if va and vb and va.template_id == vb.template_id == t.id:
            dump = lambda v: json.dumps(v.rules, indent=2, ensure_ascii=False, sort_keys=True).splitlines()  # noqa: E731
            diff = {"a": va, "b": vb, "lines": list(difflib.unified_diff(dump(va), dump(vb), f"v{va.version}",
                                                                          f"v{vb.version}", lineterm=""))}
    return render_template("template_detail.html", t=t, diff=diff)


@bp.post("/<int:tid>/przywroc/<int:vid>")
@login_required
def restore(tid, vid):
    t = _tpl(tid)
    v = db.session.get(TemplateVersion, vid)
    if not v or v.template_id != t.id:
        abort(404)
    nv = new_version(t, v.rules, current_user.email, f"Przywrócono wersję {v.version}")
    audit("restore", "template", t.id, {"from_version": v.version, "new_version": nv.version})
    db.session.commit()
    flash(f"Aktywna jest teraz wersja {nv.version} (kopia wersji {v.version}).", "success")
    return redirect(url_for("templates_views.detail", tid=t.id))


@bp.post("/<int:tid>/usun")
@login_required
def delete(tid):
    t = _tpl(tid)
    if Document.query.filter_by(template_id=t.id).count():
        flash("Nie można usunąć: szablon jest użyty w dokumentach.", "error")
        return redirect(url_for("templates_views.detail", tid=t.id))
    audit("delete", "template", t.id, {"name": t.name})
    db.session.delete(t)
    db.session.commit()
    flash("Usunięto szablon.", "success")
    return redirect(url_for("templates_views.index"))


def _render_editor(doc: Document, rules: dict, title: str):
    try:
        tree = load_tree(doc)
    except (ReaderError, OSError):
        flash("Nie można odczytać pliku źródłowego dokumentu.", "error")
        return redirect(url_for("docs.detail", doc_id=doc.id))
    synonyms, learned = load_synonyms(), learned_pairs(active_rule_sets())
    line_path = rules.get("line_path")
    cands = {f.key: [c.to_dict() for c in field_candidates(tree, f.key, line_path, synonyms, learned, limit=3)]
             for f in HEADER_FIELDS + LINE_FIELDS if f.key != "doc_type"}
    config = {
        "docId": doc.id, "rules": rules, "rows": tree.display_rows(), "groups": tree.group_paths(),
        "header": [{"key": f.key, "label": f.label, "required": f.required} for f in HEADER_FIELDS if f.key != "doc_type"],
        "lines": [{"key": f.key, "label": f.label, "required": f.required} for f in LINE_FIELDS],
        "candidates": cands, "transforms": TRANSFORM_LABELS,
        "previewUrl": url_for("templates_views.preview", doc_id=doc.id),
        "saveUrl": url_for("templates_views.save", doc_id=doc.id),
        "backUrl": url_for("docs.detail", doc_id=doc.id),
    }
    return render_template("editor.html", full_screen=True, config=config, title=title, doc=doc)


@bp.get("/<int:tid>/edytor")
@login_required
def editor_for_template(tid):
    t = _tpl(tid)
    doc = Document.query.filter_by(template_id=t.id).order_by(Document.id.desc()).first()
    if not doc:
        flash("Edytor potrzebuje przykładowej faktury — ten szablon nie ma jeszcze dokumentów.", "error")
        return redirect(url_for("templates_views.detail", tid=t.id))
    return _render_editor(doc, current_rules(doc), f"Edytor mapowań — {t.name}")


@bp.get("/dokument/<int:doc_id>/edytor")
@login_required
def editor_for_document(doc_id):
    doc = _doc(doc_id)
    return _render_editor(doc, current_rules(doc), f"Edytor mapowań — dokument #{doc.id}")


def _rules_from_request():
    payload = request.get_json(silent=True) or {}
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        return None, payload
    return rules, payload


@bp.post("/dokument/<int:doc_id>/podglad")
@login_required
def preview(doc_id):
    doc = _doc(doc_id)
    rules, _ = _rules_from_request()
    if rules is None:
        return jsonify(error="Niepoprawne reguły (oczekiwano obiektu JSON)."), 400
    tree = load_tree(doc)
    res = apply_template(tree, rules, DbLookups(), doc.supplier_id, doc.overrides or {})
    issues = res.issues + validate_invoice(res.invoice)
    return jsonify(invoice=res.invoice, issues=[i.to_dict() for i in issues])


@bp.post("/dokument/<int:doc_id>/zapisz")
@login_required
def save(doc_id):
    doc = _doc(doc_id)
    rules, payload = _rules_from_request()
    if rules is None:
        return jsonify(error="Niepoprawne reguły (oczekiwano obiektu JSON)."), 400
    comment = (payload.get("comment") or "Zmiana w edytorze mapowań").strip()[:500]
    if doc.template_id:
        v = new_version(db.session.get(Template, doc.template_id), rules, current_user.email, comment)
        audit("edit", "template", doc.template_id, {"version": v.version, "comment": comment})
    else:
        doc.draft_rules = rules
        audit("edit_draft", "document", doc.id, {"comment": comment})
    process(doc)
    db.session.commit()
    return jsonify(ok=True, status=doc.status, redirect=url_for("docs.detail", doc_id=doc.id))
```

- [ ] **Step 4: Szablony HTML**

`app/templates/templates_list.html`:
```html
{% extends "base.html" %}
{% block title %}Szablony{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Szablony dostawców</h1>
<p class="small text-muted">Szablon powstaje automatycznie przy pierwszej fakturze dostawcy. Każda zmiana tworzy nową wersję.</p>
<table class="table table-sm table-hover bg-white">
  <thead><tr><th>Nazwa</th><th>Dostawca</th><th>Aktywna wersja</th><th>Dokumenty</th><th class="text-end">Akcje</th></tr></thead>
  <tbody>{% for r in rows %}
    <tr><td>{{ r.t.name }}</td><td>{{ r.t.supplier.name if r.t.supplier else '—' }}</td>
      <td>v{{ r.active.version if r.active else '—' }}</td><td>{{ r.docs }}</td>
      <td class="text-end text-nowrap">
        <a class="btn btn-sm btn-outline-primary" href="{{ url_for('templates_views.detail', tid=r.t.id) }}">Wersje</a>
        <a class="btn btn-sm btn-outline-primary" href="{{ url_for('templates_views.editor_for_template', tid=r.t.id) }}">Edytuj</a>
        <form method="post" action="{{ url_for('templates_views.delete', tid=r.t.id) }}" class="d-inline" onsubmit="return confirm('Usunąć szablon?')"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-danger">Usuń</button></form>
      </td></tr>
  {% else %}<tr><td colspan="5" class="text-muted">Brak szablonów — wgraj pierwszą fakturę.</td></tr>{% endfor %}</tbody>
</table>
{% endblock %}
```

`app/templates/template_detail.html`:
```html
{% extends "base.html" %}
{% block title %}{{ t.name }}{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4 m-0">{{ t.name }}</h1>
  <a class="btn btn-sm btn-primary" href="{{ url_for('templates_views.editor_for_template', tid=t.id) }}">Otwórz edytor</a>
</div>
<form method="get" class="d-flex gap-2 align-items-center mb-3 small">
  Porównaj
  <select name="a" class="form-select form-select-sm w-auto">{% for v in t.versions %}<option value="{{ v.id }}" {% if diff and diff.a.id == v.id %}selected{% endif %}>v{{ v.version }}</option>{% endfor %}</select>
  z
  <select name="b" class="form-select form-select-sm w-auto">{% for v in t.versions|reverse %}<option value="{{ v.id }}" {% if diff and diff.b.id == v.id %}selected{% endif %}>v{{ v.version }}</option>{% endfor %}</select>
  <button class="btn btn-sm btn-outline-secondary">Pokaż różnice</button>
</form>
{% if diff %}
<pre class="bg-white border p-2 small">{% for l in diff.lines %}<span class="{{ 'text-success' if l.startswith('+') else ('text-danger' if l.startswith('-') else '') }}">{{ l }}</span>
{% endfor %}</pre>
{% endif %}
<table class="table table-sm bg-white">
  <thead><tr><th>Wersja</th><th>Autor</th><th>Komentarz</th><th>Utworzono</th><th></th></tr></thead>
  <tbody>{% for v in t.versions|reverse %}
    <tr><td>v{{ v.version }}{% if v.id == t.active_version_id %} <span class="badge text-bg-success">aktywna</span>{% endif %}</td>
      <td>{{ v.author or '—' }}</td><td>{{ v.comment or '' }}</td><td class="small">{{ v.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
      <td class="text-end">{% if v.id != t.active_version_id %}<form method="post" action="{{ url_for('templates_views.restore', tid=t.id, vid=v.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-secondary">Przywróć</button></form>{% endif %}</td></tr>
  {% endfor %}</tbody>
</table>
{% endblock %}
```

`app/templates/editor.html` (pełny ekran — `full_screen=True`, bez navbara i stopki):
```html
{% extends "base.html" %}
{% block title %}Edytor mapowań{% endblock %}
{% block content %}
<div x-data='editor({{ config|tojson }})' class="d-flex flex-column h-100">
  <div class="d-flex align-items-center gap-2 p-2 border-bottom bg-white">
    <a class="btn btn-sm btn-link" :href="cfg.backUrl">← Wróć</a>
    <strong class="me-auto">{{ title }}</strong>
    <input class="form-control form-control-sm w-auto" x-model="comment" placeholder="Komentarz do wersji">
    <button class="btn btn-sm btn-outline-secondary" @click="runPreview()">Podgląd</button>
    <button class="btn btn-sm btn-primary" @click="save()" :disabled="saving">Zapisz nową wersję</button>
  </div>
  <div class="row g-0 flex-grow-1" style="min-height:0">
    <div class="col-3 border-end overflow-auto p-2 bg-white">
      <div class="small text-muted mb-1">1. Kliknij element w pliku</div>
      <template x-for="r in cfg.rows" :key="r.path + r.depth">
        <div class="tree-row" :style="`padding-left:${r.depth*12}px; cursor:pointer`"
             :class="{'bg-primary-subtle': selected === r.path, 'fw-semibold': cfg.groups.includes(r.path)}"
             @click="selected = r.path" :title="r.path">
          <span x-text="r.name"></span><template x-if="r.value"><span>: <span class="val" x-text="r.value"></span></span></template>
        </div>
      </template>
    </div>
    <div class="col-5 border-end overflow-auto p-2">
      <div class="small text-muted mb-1">2. Kliknij „←” przy polu, aby przypisać zaznaczony element</div>
      <div class="card card-body p-2 mb-2">
        <div class="small fw-semibold">Element z pozycjami faktury</div>
        <div class="d-flex gap-2 align-items-center"><code class="small" x-text="rules.line_path || '— brak —'"></code>
          <button class="btn btn-sm btn-outline-primary ms-auto" @click="setLinePath()" :disabled="!selected || !cfg.groups.includes(selected)">← ustaw</button></div>
      </div>
      <p class="text-danger small" x-show="error" x-text="error"></p>
      <template x-for="section in ['header', 'lines']" :key="section">
        <div>
          <h2 class="h6 mt-3" x-text="section === 'header' ? 'Nagłówek' : 'Pozycje (ścieżki względne)'"></h2>
          <template x-for="f in cfg[section]" :key="f.key">
            <div class="border rounded p-2 mb-2 bg-white">
              <div class="d-flex align-items-center gap-2">
                <span class="small fw-semibold" x-text="f.label + (f.required ? ' *' : '')"></span>
                <button class="btn btn-sm btn-outline-primary ms-auto py-0" @click="assign(section, f.key)" :disabled="!selected">←</button>
                <button class="btn btn-sm btn-outline-secondary py-0" @click="clear(section, f.key)">×</button>
              </div>
              <code class="small d-block" x-text="ruleOf(section, f.key)?.path || ruleOf(section, f.key)?.constant || ''"></code>
              <input class="form-control form-control-sm mt-1" placeholder='transformacje JSON, np. ["strip_percent"]'
                     :value="JSON.stringify(ruleOf(section, f.key)?.transforms || [])"
                     @change="setTransforms(section, f.key, $event.target.value)" x-show="ruleOf(section, f.key)">
              <input class="form-control form-control-sm mt-1" placeholder="wartość domyślna (gdy brak w pliku)"
                     :value="defaultOf(section, f.key)" @change="setDefault(section, f.key, $event.target.value)">
              <div class="mt-1 d-flex flex-wrap gap-1">
                <template x-for="c in (cfg.candidates[f.key] || [])">
                  <button class="btn btn-sm btn-light border py-0 small" @click="applyCandidate(section, f.key, c)"
                          :title="c.reason" x-text="`${c.path.split('/').slice(-2).join('/')} · ${Math.round(c.confidence*100)}%`"></button>
                </template>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>
    <div class="col-4 overflow-auto p-2">
      <div class="small text-muted mb-1">3. Podgląd wyniku</div>
      <template x-if="preview">
        <div>
          <div class="small mb-2" x-text="preview.issues.length ? `Problemy: ${preview.issues.length}` : 'Brak problemów ✓'"></div>
          <template x-for="i in preview.issues"><div class="small border-start border-3 ps-2 mb-1" :class="i.severity === 'blocking' ? 'border-danger' : 'border-warning'" x-text="i.message"></div></template>
          <pre class="small bg-white border p-2" x-text="JSON.stringify(preview.invoice, null, 1)"></pre>
        </div>
      </template>
      <div class="small text-muted mt-3"><strong>Dostępne transformacje:</strong>
        <ul class="ps-3"><template x-for="[k, v] in Object.entries(cfg.transforms)"><li><code x-text="k"></code> — <span x-text="v"></span></li></template></ul></div>
    </div>
  </div>
</div>
{% endblock %}
{% block scripts %}<script src="{{ url_for('static', filename='editor.js') }}"></script>{% endblock %}
```
Kolejność skryptów jest poprawna: `editor.js` (zwykły skrypt w bloku `scripts`) wykonuje się przed Alpine.js, który ma `defer` i startuje po sparsowaniu dokumentu. Funkcja `editor` istnieje więc już przy inicjalizacji `x-data`.

`app/static/editor.js`:
```javascript
function editor(cfg) {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  return {
    cfg,
    rules: JSON.parse(JSON.stringify(cfg.rules || {})),
    selected: null,
    preview: null,
    comment: '',
    saving: false,
    error: '',
    init() {
      for (const k of ['header', 'lines', 'defaults', 'line_defaults']) this.rules[k] = this.rules[k] || {};
      this.runPreview();
    },
    ruleOf(section, key) { return this.rules[section][key] || null; },
    defaultOf(section, key) {
      return (this.rules[section === 'lines' ? 'line_defaults' : 'defaults'][key]) ?? '';
    },
    relative(path) {
      const base = (this.rules.line_path || '') + '/';
      return path.startsWith(base) ? path.slice(base.length) : null;
    },
    assign(section, key) {
      this.error = '';
      let path = this.selected;
      if (section === 'lines') {
        path = this.relative(this.selected);
        if (!path) { this.error = 'Pole pozycji musi wskazywać element wewnątrz elementu z pozycjami.'; return; }
      }
      const old = this.rules[section][key] || {};
      this.rules[section][key] = { path, transforms: old.transforms || [] };
      this.runPreview();
    },
    applyCandidate(section, key, c) {
      this.rules[section][key] = { path: c.path, transforms: c.transforms || [] };
      this.runPreview();
    },
    clear(section, key) { delete this.rules[section][key]; this.runPreview(); },
    setLinePath() { this.rules.line_path = this.selected; this.runPreview(); },
    setTransforms(section, key, text) {
      this.error = '';
      try {
        const t = JSON.parse(text || '[]');
        if (!Array.isArray(t)) throw new Error();
        this.rules[section][key].transforms = t;
        this.runPreview();
      } catch (e) { this.error = 'Transformacje muszą być listą JSON, np. ["trim", {"gs1": "10"}].'; }
    },
    setDefault(section, key, value) {
      const bucket = this.rules[section === 'lines' ? 'line_defaults' : 'defaults'];
      if (value === '') delete bucket[key]; else bucket[key] = value;
      this.runPreview();
    },
    async post(url, body) {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                                   body: JSON.stringify(body) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Błąd serwera');
      return data;
    },
    async runPreview() {
      try { this.preview = await this.post(cfg.previewUrl, { rules: this.rules }); this.error = ''; }
      catch (e) { this.error = e.message; }
    },
    async save() {
      this.saving = true;
      try {
        const res = await this.post(cfg.saveUrl, { rules: this.rules, comment: this.comment });
        window.location = res.redirect;
      } catch (e) { this.error = e.message; } finally { this.saving = false; }
    },
  };
}
```

- [ ] **Step 5: PASS:** `pytest tests/test_web_templates.py -q && pytest -q`

- [ ] **Step 6: Commit**
```bash
git add app/web/templates_views.py app/templates app/static/editor.js tests/test_web_templates.py
pytest tests/test_no_private_data.py -q
git commit -m "feat(szablony): wersje, diff, przywracanie i pełnoekranowy edytor mapowań

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---
### Task 17: Strona „O demo” — opis działania, wczytywanie próbek, reset

**Files:**
- Create: `app/web/demo.py`, `app/templates/demo.html`
- Test: `tests/test_web_demo.py`

**Interfaces:**
- Consumes: `ingest` (Task 11), `reset_demo` (Task 10), `audit`.
- Produces: blueprint `demo`: `GET /demo` → `demo.index` (publiczny), `POST /demo/wczytaj/<name>` → `demo.load_sample` (login), `POST /demo/reset` → `demo.reset` (login). `DEMO_SAMPLES: list[dict]` (`file`, `title`, `format`, `shows`). Gdy `DEMO_MODE=0`, wszystkie trasy demo zwracają 404.

- [ ] **Step 1: Testy**

`tests/test_web_demo.py`:
```python
from app.models import Document


def test_root_redirects_to_demo(seeded, client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/demo")


def test_demo_page_public_and_descriptive(seeded, client):
    html = client.get("/demo").get_data(as_text=True)
    assert "Jak to działa" in html and "alfa-1.xml" in html
    assert "xp_test_demo_key" in html            # przykład curl z kluczem demo
    assert "admin@example.com" in html           # dane logowania demo
    assert "Project &amp; Development" in html   # stopka


def test_load_sample_requires_login(seeded, client):
    r = client.post("/demo/wczytaj/alfa-1.xml")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_load_sample_and_reset(auth_client):
    r = auth_client.post("/demo/wczytaj/alfa-1.xml")
    assert r.status_code == 302 and "/dokumenty/" in r.headers["Location"]
    assert Document.query.one().source == "demo"
    auth_client.post("/demo/reset")
    assert Document.query.count() == 0


def test_unknown_sample_404(auth_client):
    assert auth_client.post("/demo/wczytaj/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert auth_client.post("/demo/wczytaj/nieznany.xml").status_code == 404


def test_demo_disabled(seeded, app, client):
    app.config["DEMO_MODE"] = False
    assert client.get("/demo").status_code == 404
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: `app/web/demo.py`**

```python
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.audit import audit
from app.services.pipeline import ingest
from app.services.seed import reset_demo

bp = Blueprint("demo", __name__, url_prefix="/demo")
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "demo" / "samples"

DEMO_SAMPLES = [
    {"file": "alfa-1.xml", "title": "Hurtownia Alfa — pierwsza faktura", "format": "XML (własny, PL)",
     "shows": "nowy dostawca, brak waluty, jednostka „pcs”, EAN z prefiksem AI 01, partia i data z kodu GS1-128"},
    {"file": "alfa-2.xml", "title": "Hurtownia Alfa — kolejna faktura", "format": "XML (własny, PL)",
     "shows": "po nauczeniu na pierwszej fakturze przechodzi automatycznie"},
    {"file": "beta-ksef.xml", "title": "Młyn Beta", "format": "KSeF FA(3)-podobny",
     "shows": "jednostka „worek” i przelicznik na kg odczytany z nazwy towaru"},
    {"file": "gamma-ubl.xml", "title": "Gamma Aromen", "format": "UBL 2.1",
     "shows": "kody jednostek UN/ECE (C62, H87) w atrybucie unitCode"},
    {"file": "delta.csv", "title": "Opakowania Delta", "format": "CSV",
     "shows": "przecinek dziesiętny, data DD.MM.RRRR, „kart.” → szt (×12)"},
    {"file": "epsilon.json", "title": "Epsilon Dairy", "format": "JSON",
     "shows": "jednostka „EA”, towary dopasowane po GTIN"},
]
_ALLOWED = {s["file"] for s in DEMO_SAMPLES}


@bp.before_request
def only_in_demo_mode():
    if not current_app.config.get("DEMO_MODE"):
        abort(404)


@bp.get("")
def index():
    return render_template("demo.html", samples=DEMO_SAMPLES, api_base=request.host_url.rstrip("/"),
                           demo_key=current_app.config.get("DEMO_API_KEY"),
                           admin_email=current_app.config.get("ADMIN_EMAIL"),
                           admin_password=current_app.config.get("ADMIN_PASSWORD"))


@bp.post("/wczytaj/<path:name>")
@login_required
def load_sample(name):
    if name not in _ALLOWED:
        abort(404)
    doc = ingest((SAMPLES_DIR / name).read_bytes(), name, source="demo")
    return redirect(url_for("docs.detail", doc_id=doc.id))


@bp.post("/reset")
@login_required
def reset():
    reset_demo()
    audit("reset", "demo", None, {})
    from app.extensions import db
    db.session.commit()
    flash("Dane demo wyczyszczone — kartoteka towarów i jednostki przywrócone.", "success")
    return redirect(url_for("demo.index"))
```

- [ ] **Step 4: `app/templates/demo.html`**

```html
{% extends "base.html" %}
{% block title %}O demo{% endblock %}
{% block content %}
<div class="row g-4">
  <div class="col-lg-7">
    <h1 class="h3">Parser faktur, który uczy się od operatora</h1>
    <p class="lead">Każdy dostawca przysyła faktury w innym formacie. Zamiast pisać integrację dla każdego z nich,
      system czyta <strong>dowolny plik strukturalny</strong> (XML, JSON, CSV). Przy <strong>pierwszej</strong>
      fakturze nowego dostawcy pyta o to, czego nie rozumie, i zapamiętuje odpowiedzi jako
      <strong>szablon dostawcy</strong>. Kolejne faktury czyta już sam.</p>

    <h2 class="h5 mt-4">Jak to działa</h2>
    <ol class="list-group list-group-numbered mb-3">
      <li class="list-group-item"><strong>Odczyt</strong> — plik zamieniany jest na drzewo ścieżek (np. <code>Faktura/Naglowek/DostawcaNIP</code>), niezależnie od formatu. Pliki XML z DOCTYPE/ENTITY są odrzucane (bezpieczeństwo).</li>
      <li class="list-group-item"><strong>Rozpoznanie dostawcy</strong> — po NIP/VAT; gdy go nie ma — po „odcisku” struktury pliku.</li>
      <li class="list-group-item"><strong>Szablon</strong> — reguły: <em>pole docelowe ← ścieżka w pliku → transformacje</em> (np. usuń „%”, wytnij partię z kodu GS1-128). Dla nowego dostawcy system proponuje reguły sam, na podstawie słownika synonimów (PL/EN/KSeF/UBL) i typów wartości.</li>
      <li class="list-group-item"><strong>Słowniki</strong> — jednostki miary (<code>pcs</code> → <code>szt</code>), przeliczniki (<code>1 karton = 12 szt</code>), przypisanie towarów dostawcy do naszych indeksów.</li>
      <li class="list-group-item"><strong>Walidacja</strong> — ilość × cena = wartość, suma pozycji = suma faktury, netto + VAT = brutto, wykrywanie duplikatów.</li>
      <li class="list-group-item"><strong>Negocjacja</strong> — gdy czegoś brakuje, faktura trafia do kolejki „do wyjaśnienia”. Operator wybiera podpowiedź i decyduje: <em>tylko ta faktura</em> albo <em>zapamiętaj</em>. Zapamiętanie tworzy nową wersję szablonu.</li>
      <li class="list-group-item"><strong>Wynik</strong> — znormalizowany JSON dostępny przez REST API dla innych systemów.</li>
    </ol>

    <h2 class="h5 mt-4">Scenariusz demo (5 minut)</h2>
    <ol class="small">
      <li>Zaloguj się i wczytaj <strong>alfa-1.xml</strong> — faktura trafi do kolejki z problemami.</li>
      <li>Rozwiąż problemy od góry: utwórz dostawcę, ustaw domyślną walutę, wskaż, że <code>pcs</code> to <code>szt</code>, przypisz „Masę marcepanową” do towaru z kartoteki.</li>
      <li>Wczytaj <strong>alfa-2.xml</strong> — zostanie zatwierdzona automatycznie, bez pytań.</li>
      <li>Spróbuj innych formatów: KSeF, UBL, CSV, JSON — ten sam mechanizm.</li>
      <li>Zajrzyj do <em>Szablony</em> → wersje i różnice, oraz do <em>Edytora mapowań</em>.</li>
    </ol>
  </div>

  <div class="col-lg-5">
    <div class="card mb-3"><div class="card-body small">
      <h2 class="h6">Dostęp demo</h2>
      <div>E-mail: <code>{{ admin_email }}</code></div>
      <div>Hasło: <code>{{ admin_password }}</code></div>
      {% if not current_user.is_authenticated %}<a class="btn btn-sm btn-primary mt-2" href="{{ url_for('auth.login') }}">Zaloguj</a>{% endif %}
    </div></div>

    <div class="card mb-3"><div class="card-body">
      <h2 class="h6">Przykładowe faktury (fikcyjne dane)</h2>
      <table class="table table-sm small mb-2">
        {% for s in samples %}
        <tr><td><strong>{{ s.file }}</strong><br><span class="text-muted">{{ s.format }} — {{ s.shows }}</span></td>
          <td class="text-end">{% if current_user.is_authenticated %}
            <form method="post" action="{{ url_for('demo.load_sample', name=s.file) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-primary">Wczytaj</button></form>
          {% endif %}</td></tr>
        {% endfor %}
      </table>
      {% if current_user.is_authenticated %}
      <form method="post" action="{{ url_for('demo.reset') }}" onsubmit="return confirm('Wyczyścić wszystkie dane demo?')">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-danger">Wyczyść dane demo</button>
      </form>
      {% endif %}
    </div></div>

    <div class="card"><div class="card-body small">
      <h2 class="h6">API</h2>
      <p class="mb-1">Wyślij fakturę z dowolnego systemu:</p>
      <pre class="bg-light p-2 small mb-1">curl -H "X-API-Key: {{ demo_key }}" \
  -F file=@faktura.xml \
  {{ api_base }}/api/v1/documents</pre>
      <a href="{{ url_for('api_docs') }}">Dokumentacja API (Swagger) →</a>
    </div></div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: PASS:** `pytest tests/test_web_demo.py -q && pytest -q`

- [ ] **Step 6: Commit**
```bash
git add app/web/demo.py app/templates/demo.html tests/test_web_demo.py
pytest tests/test_no_private_data.py -q
git commit -m "feat(demo): strona „O demo” z opisem, próbkami i resetem

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
```

---

### Task 18: Weryfikacja E2E (Docker + MariaDB + przeglądarka), prywatna próbka lokalnie, wydanie v0.1.0

**Files:**
- Create: `tests/test_private_samples.py` (pomija się bez katalogu `private/samples/`; **nie zawiera** prywatnych danych)
- Modify: `pyproject.toml` (`version = "0.1.0"`), `CHANGELOG.md`, `README.md`

**Interfaces:**
- Consumes: wszystko powyżej; `resolve_with_top_suggestions` z `tests/test_learning.py`.

- [ ] **Step 1: Test lokalny na prywatnych fakturach (bez danych w repo)**

`tests/test_private_samples.py`:
```python
"""Uruchamia scenariusz uczenia na realnych fakturach z private/samples/ (katalog ignorowany przez git).

W CI i na czystym klonie katalogu nie ma — testy są pomijane.
"""
from pathlib import Path

import pytest

from app.services.pipeline import ingest
from tests.test_learning import resolve_with_top_suggestions

PRIVATE = Path(__file__).resolve().parent.parent / "private" / "samples"
FILES = sorted(p for p in PRIVATE.glob("*") if p.is_file()) if PRIVATE.exists() else []


@pytest.mark.skipif(not FILES, reason="brak prywatnych próbek (private/samples/)")
@pytest.mark.parametrize("path", FILES, ids=[f"private-{i}" for i in range(len(FILES))])
def test_private_sample_learning(seeded, path):
    data = path.read_bytes()
    first = ingest(data, path.name)
    assert first.status == "needs_review"
    resolve_with_top_suggestions(first)
    assert first.status == "approved", first.issues
    again = ingest(data + b"\n", path.name)
    # dostawca rozpoznany po NIP z szablonu → wykryty duplikat (ten sam numer), bez innych problemów
    assert again.supplier_id == first.supplier_id
    assert again.status == "duplicate"
    assert [i["code"] for i in again.issues if i["severity"] == "blocking"] == ["duplicate"]
```
Uwaga: identyfikatory testów są numeryczne (`private-0`), żeby nazwy plików nie trafiały do logów CI.

Run: `pytest tests/test_private_samples.py -v`
Expected: lokalnie PASS dla prywatnej faktury. Jeśli FAIL, popraw synonimy lub heurystyki **wyłącznie ogólnie**: bez wpisywania nazw i wartości z prywatnego pliku do repo.

- [ ] **Step 2: Pełny zestaw testów + audyt zależności**

```bash
pytest -q
pip-audit -r requirements.txt
```
Expected: wszystkie testy zielone; `pip-audit` bez znanych podatności (jeśli są, podbij wersję pakietu w `requirements.txt` i powtórz testy).

- [ ] **Step 3: Docker + MariaDB + migracje**

```bash
docker compose down -v
docker compose up -d --build
docker compose logs app | tail -20          # oczekiwane: "Seed OK", gunicorn nasłuchuje na 5010
curl -fsS http://127.0.0.1:5010/healthz
KEY=$(grep ^DEMO_API_KEY .env | cut -d= -f2)
curl -fsS -H "X-API-Key: $KEY" -F file=@demo/samples/alfa-1.xml http://127.0.0.1:5010/api/v1/documents | python3 -m json.tool | head -30
```
Expected: `/healthz` zwraca wersję. POST zwraca `201` ze `"status": "needs_review"` i listą problemów zaczynającą się od `unknown_supplier`. Jeżeli `flask db upgrade` na MariaDB zgłasza błąd typu (np. długość indeksu, JSON), popraw migrację w `migrations/versions/` i powtórz od `down -v`.

- [ ] **Step 4: Weryfikacja w przeglądarce (claude-in-chrome)**

Użyj skilla `claude-in-chrome` i nagraj GIF `xml-parser-demo-uczenie.gif`:
1. Otwórz `http://<host>:5010/` (adres Tailscale serwera lub `127.0.0.1`) → strona „O demo”, sprawdź stopkę z `v0.1.0` (po kroku 6) lub `v0.0.1`.
2. Zaloguj się danymi z `.env`.
3. „Wczytaj” `alfa-1.xml` → rozwiąż problemy od góry wg scenariusza demo → status „Zatwierdzona”.
4. „Wczytaj” `alfa-2.xml` → od razu „Zatwierdzona”.
5. Otwórz „Szablony” → wersje → diff v1/v2; otwórz edytor mapowań (pełny ekran, **bez** stopki) → kliknij „Podgląd”.
6. Sprawdź `/api/docs` (Swagger ładuje się bez CDN — w narzędziach sieci brak żądań do zewnętrznych domen).
7. Odczytaj konsolę (`read_console_messages`, wzorzec `error|Error`) — brak błędów JS.

Nie klikaj przycisków „Usuń” ani „Wyczyść dane demo” podczas automatyzacji, bo otwierają natywny `confirm()`.

- [ ] **Step 5: Prywatna faktura przez działający system (ręcznie, lokalnie)**

```bash
curl -fsS -H "X-API-Key: $KEY" -F file=@private/samples/$(ls private/samples | head -1) \
  http://127.0.0.1:5010/api/v1/documents | python3 -m json.tool | head -40
```
Przejdź negocjację w panelu (pozycje dostawcy nie istnieją w kartotece demo → „dodaj nowy towar”). Potem wyczyść dane: „Wyczyść dane demo”, żeby realne dane nie zostały w bazie demo.

- [ ] **Step 6: Wydanie v0.1.0**

`pyproject.toml`: `version = "0.1.0"`.

`CHANGELOG.md` — zamień sekcję `[Unreleased]` i dodaj wydanie:
```markdown
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

[Unreleased]: https://github.com/AmigoUK/xml-parser/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AmigoUK/xml-parser/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/AmigoUK/xml-parser/releases/tag/v0.0.1
```
(Usuń poprzednie dwie linie linków `[Unreleased]`/`[0.0.1]` z dołu pliku, żeby nie było duplikatów.)

`README.md` — dopisz sekcję:
```markdown
## Tryb demo

`DEMO_MODE=1` włącza publiczną stronę „O demo” **z danymi logowania admina** i kluczem API demo.
Nie używaj `DEMO_MODE=1` na instancji z prawdziwymi danymi.
```

```bash
pytest -q
git add -A
pytest tests/test_no_private_data.py -q
git status --short          # upewnij się, że nie ma nic z private/ ani storage/
git commit -m "chore(release): v0.1.0 — MVP demo uczącego się parsera faktur

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015a9MwTdU8pYJBCSugH4P9N"
git tag -a v0.1.0 -m "v0.1.0 — MVP demo uczącego się parsera faktur"
git push origin main && git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes "$(awk '/^## \[0.1.0\]/{f=1;next}/^## \[/{f=0}f' CHANGELOG.md)"
docker compose up -d --build   # stopka pokazuje v0.1.0
```

---

## Self-review (wykonany przy pisaniu planu)

**Pokrycie specu → zadania:**
- §1 kryteria sukcesu 1–4 → Task 11 (`needs_review` + podpowiedzi), Task 12 (`test_first_invoice_negotiated_next_one_automatic` na 5 formatach), Task 13 (API).
- §1 ochrona danych prywatnych → Task 1 (strażnik + hook), Task 18 (`test_private_samples.py` bez danych w repo).
- §3 pipeline + statusy + kody problemów → Task 7, 8, 11.
- §4 moduły → Task 3–9 (silnik), 10–12 (usługi), 13–17 (web/API).
- §5 dokument kanoniczny, Decimal jako string → Task 5–7.
- §6 szablon + wersje → Task 7, 10, 12, 16.
- §7 model danych → Task 10. `price_history` jest odłożone do E2 zgodnie ze specem.
- §8 API (bez endpointów E2: eksport/import szablonów, webhooki) → Task 13.
- §9 panel: wszystkie ekrany MVP → Task 14–17. „Użytkownicy” to E2, MVP ma jedno konto z `.env`.
- §10 bezpieczeństwo → Task 3 (XXE/DOCTYPE), Task 1/11/13 (limit), Task 10 (hash kluczy, haseł), Task 1 (CSRF), Task 5 (biała lista, limity regex), Task 17 (biała lista próbek, path traversal).
- §11 próbki → Task 2 (korekta `alfa-1-korekta.xml` to E2).
- §13 testy → każdy task + Task 18 E2E.

**Świadome odchylenia od specu:**
- `unit_map` nie jest transformacją: jednostka jest zawsze rozwiązywana przez słowniki w `apply_template` (Task 7).
- Porównanie NIP/VAT (z prefiksem kraju i bez niego) robi `tax_ids_match` w kodzie, a nie znormalizowana kolumna w bazie.
