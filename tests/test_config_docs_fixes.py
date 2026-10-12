"""Poprawki konfiguracji, dokumentacji i panelu/API z audytu 2026-10-11 (znaleziska średnie): neutralny adres bazowy
w eksporcie Pomocy i README, czas sesji z env, jawne zależności deweloperskie, favicon i metadane Open Graph,
pełniejsza specyfikacja OpenAPI."""
import importlib.util
import inspect
import io
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KEY = {"X-API-Key": "xp_test_demo_key"}


def _exporter():
    spec = importlib.util.spec_from_file_location("export_help", ROOT / "tools" / "export_help.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- adres bazowy: panel pokazuje adres instancji, eksport i README — neutralny przykład ------------------------

def test_export_help_uses_neutral_base_url_and_export_flag():
    exporter = _exporter()
    assert "localhost" not in exporter.BASE_URL and "18506" not in exporter.BASE_URL
    assert exporter.BASE_URL.startswith("https://") and "example" in exporter.BASE_URL
    assert exporter.DEFAULT_CONFIG.get("HELP_EXPORT") is True


def test_help_marks_base_url_as_example_only_in_export(app, client):
    html = client.get("/pomoc/api", base_url="http://parser.firma.test").get_data(as_text=True)
    assert "Adres bazowy tej instancji" in html and "http://parser.firma.test/api/v1" in html
    app.config["HELP_EXPORT"] = True
    for path in ("/pomoc/api", "/pomoc/integracja"):
        html = client.get(path, base_url="https://parser.example.com").get_data(as_text=True)
        assert "Adres bazowy tej instancji" not in html, path
        assert "przykład" in html and "w panelu" in html, path


def test_docs_and_readme_have_no_local_port_as_base_url():
    for name in ("docs/pomoc/api.md", "docs/pomoc/integracja.md", "README.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "localhost:18506" not in text, name
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "BASE=http://localhost:${APP_PORT:-18506}" in readme and '$BASE/api/v1/documents' in readme


# --- konfiguracja: czas sesji i retencja dziennika z env, zależności deweloperskie -----------------------------

def test_session_hours_and_audit_retention_from_env():
    from app import config as cfg
    src = inspect.getsource(cfg)
    assert 'SESSION_HOURS = int(os.environ.get("SESSION_HOURS", 8))' in src
    assert "timedelta(hours=SESSION_HOURS)" in src
    assert 'AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", 90))' in src
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for var in ("SESSION_HOURS", "AUDIT_RETENTION_DAYS"):
        assert f"# {var}=" in env_example and f"      {var}: ${{{var}:-" in compose, var


def test_help_session_hours_follow_configuration(app):
    from datetime import timedelta

    from app.web.help import help_limits
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)
    with app.test_request_context():
        assert help_limits()["session_hours"] == 2


def test_dev_requirements_pin_test_and_lint_tools():
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    for pkg in ("requests==", "ruff==", "pytest-cov=="):
        assert pkg in text, pkg


# --- panel: favicon i metadane Open Graph ------------------------------------------------------------------------

def test_favicon_and_social_meta(client):
    html = client.get("/login").get_data(as_text=True)
    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in html
    assert '<meta name="description" content="' in html
    assert '<meta property="og:title" content="' in html
    assert '<meta property="og:image" content="http://localhost/static/og-image.png">' in html
    assert client.get("/static/favicon.svg").status_code == 200
    assert client.get("/static/og-image.png").status_code == 200
    r = client.get("/favicon.ico")
    assert r.status_code in (301, 302, 308) and r.headers["Location"].endswith("/static/favicon.svg")


# --- OpenAPI: dostawcy ze schematem, 401 przy każdej operacji, nagłówek X-Filename -------------------------------

def test_openapi_suppliers_schema_401_and_filename_header(seeded, client):
    from app.extensions import db
    from app.models import ApiKey, Document, Supplier
    spec = yaml.safe_load((ROOT / "app" / "static" / "openapi.yaml").read_text(encoding="utf-8"))
    paths, schemas = spec["paths"], spec["components"]["schemas"]
    for path, method in (("/documents", "post"), ("/documents", "get"), ("/documents/{id}", "get"),
                         ("/documents/{id}/reprocess", "post"), ("/suppliers", "get"),
                         ("/webhook-deliveries", "get")):
        assert "401" in paths[path][method]["responses"], (path, method)
    header = [p for p in paths["/documents"]["post"].get("parameters", []) if p["in"] == "header"]
    assert header and header[0]["name"] == "X-Filename" and header[0]["required"] is False
    sup = paths["/suppliers"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert sup == {"$ref": "#/components/schemas/SupplierList"}
    assert set(schemas["SupplierList"]["properties"]) == {"items"}
    key = ApiKey.query.filter_by(name="Klucz demo").one()
    s = Supplier(name="Alfa", tax_id="1234567890")
    db.session.add(s)
    db.session.flush()
    db.session.add(Document(sha256="a" * 64, status="approved", supplier_id=s.id, api_key_id=key.id))
    db.session.commit()
    items = client.get("/api/v1/suppliers", headers=KEY).get_json()["items"]
    assert items and set(items[0]) == set(schemas["Supplier"]["properties"]) == {"id", "name", "tax_id"}
    assert client.get("/api/v1/suppliers").status_code == 401
    assert client.get("/api/v1/documents/1").status_code == 401
    assert client.post("/api/v1/documents/1/reprocess").status_code == 401


# --- webhooki (v0.9.0): dokumentacja operacyjna ---------------------------------------------------------------------
WEBHOOK_ENV = ("PUBLIC_BASE_URL", "WEBHOOK_ALLOW_HTTP", "WEBHOOK_ALLOWED_HOSTS", "WEBHOOK_RETENTION_DAYS",
               "WEBHOOK_HEARTBEAT_FILE", "WORKER_MEM_LIMIT", "WORKER_CPUS")


def test_readme_env_table_lists_webhook_variables():
    import re

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("|")]
    table = "\n".join(rows)
    for name in WEBHOOK_ENV:
        assert f"`{name}`" in table, name
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    start = example.index("Webhooki (v0.9.0)")
    block = example[start:].split("\n\n", 1)[0]
    for name in re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", block, flags=re.M):
        assert f"`{name}`" in table, name
    assert "docs/pomoc/webhooki.md" in readme
    assert "webhooks-worker --once" in readme and "prune-webhooks" in readme


def test_wdrozenie_mentions_worker_and_public_base_url():
    text = (ROOT / "docs" / "wdrozenie.md").read_text(encoding="utf-8")
    for needle in ("PUBLIC_BASE_URL", "WEBHOOK_ALLOWED_HOSTS", "WEBHOOK_ALLOW_HTTP", "worker", "99f2fe61d963",
                   "webhooks-worker"):
        assert needle in text, needle
