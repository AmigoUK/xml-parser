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
