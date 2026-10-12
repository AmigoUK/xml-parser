"""Identyfikatory z wejścia (adres, formularz, parametr zapytania) większe niż 2**63-1 nie mogą kończyć się 500.

SQLite nie zwiąże liczby ponad 64 bity (OverflowError przy wykonaniu zapytania), MariaDB zwróciłaby 404 — oba
silniki mają dawać tę samą odpowiedź: 404 dla adresu, czytelny komunikat dla pola formularza."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.ids import MAX_ID, parse_id
from app.models import Document
from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes

HUGE = "99999999999999999999"  # ponad 2**64
KEY = {"X-API-Key": "xp_test_demo_key"}


@pytest.mark.parametrize("raw, expected", [
    ("12", 12), (" 12 ", 12), (12, 12), (str(MAX_ID), MAX_ID),
    (str(MAX_ID + 1), None), (HUGE, None), ("0", None), ("-1", None), ("+1", None), ("1.0", None),
    ("abc", None), ("", None), (None, None), ("١٢", None), (True, None),
])
def test_parse_id(raw, expected):
    assert parse_id(raw) == expected


@pytest.mark.parametrize("doc_id", [HUGE, str(2**63)])
def test_api_huge_document_id_is_404(seeded, client, doc_id):
    r = client.get(f"/api/v1/documents/{doc_id}", headers=KEY)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    r = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=KEY)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"


def test_api_max_id_is_plain_404(seeded, client):
    assert client.get(f"/api/v1/documents/{MAX_ID}", headers=KEY).status_code == 404


@pytest.mark.parametrize("method, url", [
    ("get", f"/dokumenty/{HUGE}"), ("get", f"/dokumenty/{HUGE}/plik"), ("get", f"/dokumenty/{HUGE}/json"),
    ("post", f"/dokumenty/{HUGE}/ponownie"), ("post", f"/dokumenty/{HUGE}/rozwiaz"),
    ("post", f"/dokumenty/{HUGE}/przywroc"),
    ("get", f"/szablony/{HUGE}"), ("get", f"/szablony/{HUGE}/edytor"), ("post", f"/szablony/{HUGE}/usun"),
    ("get", f"/szablony/dokument/{HUGE}/edytor"), ("post", f"/szablony/dokument/{HUGE}/podglad"),
    ("post", f"/szablony/dokument/{HUGE}/zapisz"),
    ("get", f"/dostawcy/{HUGE}/edycja"), ("post", f"/dostawcy/{HUGE}/usun"), ("get", f"/towary/{HUGE}/edycja"),
    ("post", f"/klucze-api/{HUGE}/przelacz"), ("post", f"/klucze-api/{HUGE}/nazwa"),
    ("post", f"/klucze-api/{HUGE}/usun"),
])
def test_panel_huge_ids_are_404(auth_client, method, url):
    assert getattr(auth_client, method)(url).status_code == 404


def test_crud_select_with_huge_id_is_form_error(auth_client):
    r = auth_client.post("/towary/nowy", data={"code": "X-9", "name": "Towar", "gtin": "", "unit_id": HUGE})
    assert r.status_code == 200
    assert "Nieprawidłowa wartość pola" in r.get_data(as_text=True)


def test_template_diff_with_huge_version_ids(auth_client):
    doc = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(doc, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    assert auth_client.get(f"/szablony/{doc.template_id}?a={HUGE}&b={HUGE}").status_code == 200
    assert auth_client.get(f"/szablony/{doc.template_id}?a=1&b={HUGE}").status_code == 200


@pytest.mark.parametrize("bad", [HUGE, "abc", "-1"])
def test_use_supplier_with_bad_id_is_polish_message(auth_client, bad):
    doc = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    r = auth_client.post(f"/dokumenty/{doc.id}/rozwiaz", data={"action": "use_supplier", "supplier_id": bad},
                         follow_redirects=True)
    assert r.status_code == 200
    assert "Nieprawidłowy identyfikator dostawcy" in r.get_data(as_text=True)
    assert "invalid literal" not in r.get_data(as_text=True)


def test_overflow_in_db_binding_is_not_500(app, client):
    """Siatka bezpieczeństwa: id ponad zakres związane bezpośrednio w zapytaniu (ścieżka bez strażnika)."""
    @app.get("/api/_overflow")
    def _api_overflow():
        return str(db.session.get(Document, 2**64))

    @app.get("/_overflow")
    def _panel_overflow():
        return str(db.session.get(Document, 2**64))

    r = client.get("/api/_overflow")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"
    assert client.get("/_overflow").status_code == 404


def test_other_database_errors_still_propagate(app, client):
    @app.get("/api/_broken")
    def _broken():
        return str(db.session.execute(sa.text("SELECT * FROM nie_ma_takiej_tabeli")).all())

    with pytest.raises(OperationalError):
        client.get("/api/_broken")
