"""Podział warstw (CLAUDE.md): logika domenowa i granice transakcji w app/services, serializacja API w module
współdzielonym — widoki tylko mapują żądanie na wywołanie serwisu."""
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_catalog_domain_logic_lives_in_services(seeded, app):
    from app.services import catalog as svc
    for name in ("documents_using", "import_products_csv", "product_before_save", "alias_before_save",
                 "unit_before_save", "conversion_before_save", "supplier_before_save", "mapping_before_save",
                 "supplier_delete_blocker", "unit_delete_blocker", "product_delete_blocker",
                 "MAX_IMPORT_BYTES", "MAX_IMPORT_ROWS"):
        assert hasattr(svc, name), name
    from app.models import Product
    csv_data = b"indeks;nazwa;gtin;jednostka\nNOWY-1;Towar testowy;;szt\nTOW-0001;Posypka 2;;kg\n"
    report = svc.import_products_csv(csv_data)
    assert report["added"] == 1 and report["updated"] == 1 and report["errors"] == []
    assert Product.query.filter_by(code="NOWY-1").one().unit.code == "szt"
    assert Product.query.filter_by(code="TOW-0001").one().name == "Posypka 2"
    report = svc.import_products_csv(b"kolumna\nx\n")
    assert report["errors"] and report["added"] == 0


def test_web_catalog_only_wires_views():
    src = (ROOT / "app" / "web" / "catalog.py").read_text(encoding="utf-8")
    assert "csv.DictReader" not in src and "def documents_using" not in src and "def _import_rows" not in src
    assert "from app.services.catalog import" in src


def test_locked_version_lookup_in_templates_service(seeded, app):
    from app.services.templates import locked_active_version_id
    src = (ROOT / "app" / "web" / "templates_views.py").read_text(encoding="utf-8")
    assert "def _locked_active_version_id" not in src and "locked_active_version_id" in src
    from app.models import Document
    assert locked_active_version_id(Document(template_id=None)) is None


def test_api_serializer_shared_by_web_and_api(seeded, client):
    from app.api.serializers import api_issues, doc_to_json  # noqa: F401
    web_src = (ROOT / "app" / "web" / "documents.py").read_text(encoding="utf-8")
    assert "from app.api.routes import" not in web_src and "from app.api.serializers import doc_to_json" in web_src
    from tests.conftest import sample_bytes
    r = client.post("/api/v1/documents", headers={"X-API-Key": "xp_test_demo_key"},
                    data={"file": (io.BytesIO(sample_bytes("alfa-1.xml")), "alfa-1.xml")})
    assert r.status_code == 201 and set(r.get_json()) >= {"id", "status", "issues", "invoice"}
