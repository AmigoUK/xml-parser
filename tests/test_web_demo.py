from pathlib import Path

from app.extensions import db
from app.models import Document, User


def test_root_redirects_to_demo(seeded, client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/demo")


def test_demo_page_public_and_descriptive(seeded, client):
    html = client.get("/demo").get_data(as_text=True)
    assert "Jak to działa" in html and "alfa-1.xml" in html
    assert "/api/v1/documents" in html           # przykład curl (klucz demo tylko dla zalogowanych)
    assert "xp_test_demo_key" not in html
    assert "admin@example.com" in html           # e-mail konta demo (hasło nigdy)
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


def test_reset_requires_login(seeded, client):
    r = client.post("/demo/reset")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_reset_outside_demo_mode_is_404_not_500(auth_client, app):
    app.config["DEMO_MODE"] = False
    assert auth_client.post("/demo/reset").status_code == 404
    assert auth_client.post("/demo/wczytaj/alfa-1.xml").status_code == 404


# --- karta zestawu demo «Miesiąc faktur» ------------------------------------------------------------

def _op_client(client):
    u = User(email="operator@example.com", role="operator")
    u.set_password("operator-haslo-1")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"email": "operator@example.com", "password": "operator-haslo-1"})
    return client


def test_demo_page_shows_dataset_table_with_24_rows_and_buttons(auth_client):
    html = auth_client.get("/demo").get_data(as_text=True)
    assert 'id="zestaw"' in html and "Miesiąc faktur" in html
    assert html.count("<tr") >= 25  # nagłówek + 24 wiersze zestawu (+ próbki)
    assert "Wczytaj pierwsze (6)" in html and "Wczytaj pozostałe (18)" in html and "Wczytaj wszystko (24)" in html
    assert "/demo/zestaw/wczytaj/pierwsze" in html


def test_dataset_buttons_hidden_when_logged_out(seeded, client):
    html = client.get("/demo").get_data(as_text=True)
    assert 'id="zestaw"' in html and "Wczytaj pierwsze" not in html
    assert "/demo/zestaw/wczytaj/" not in html


def test_load_first_phase_creates_six_demo_documents_and_redirects_to_anchor(auth_client):
    r = auth_client.post("/demo/zestaw/wczytaj/pierwsze")
    assert r.status_code == 302 and r.headers["Location"].endswith("/demo#zestaw")
    assert Document.query.count() == 6 and {d.source for d in Document.query} == {"demo"}
    html = auth_client.get("/demo").get_data(as_text=True)
    assert "Wczytano 6 faktur, pominięto 0 już wczytanych." in html
    assert "Wczytaj pierwsze (0)" in html and "disabled" in html


def test_load_first_phase_twice_skips_loaded(auth_client):
    auth_client.post("/demo/zestaw/wczytaj/pierwsze")
    auth_client.post("/demo/zestaw/wczytaj/pierwsze")
    assert Document.query.count() == 6
    assert "Wczytano 0 faktur, pominięto 6 już wczytanych." in auth_client.get("/demo").get_data(as_text=True)


def test_load_rest_then_all_is_idempotent(auth_client):
    auth_client.post("/demo/zestaw/wczytaj/pierwsze")
    auth_client.post("/demo/zestaw/wczytaj/pozostale")
    n = Document.query.count()
    assert n >= 24
    auth_client.post("/demo/zestaw/wczytaj/wszystko")
    assert Document.query.count() == n


def test_unknown_phase_404(auth_client):
    assert auth_client.post("/demo/zestaw/wczytaj/nieznana").status_code == 404


def test_reset_button_renamed(auth_client):
    html = auth_client.get("/demo").get_data(as_text=True)
    assert "Resetuj zestaw demo" in html and "Wyczyść dane demo" not in html
    assert 'data-confirm="' in html


def test_reset_forbidden_for_operator_role(seeded, client):
    c = _op_client(client)
    assert c.post("/demo/reset").status_code == 403
    assert "Resetuj zestaw demo" not in c.get("/demo").get_data(as_text=True)


def test_dataset_endpoints_404_outside_demo_mode(auth_client, app):
    app.config["DEMO_MODE"] = False
    assert auth_client.post("/demo/zestaw/wczytaj/pierwsze").status_code == 404
    assert auth_client.get("/demo").status_code == 404


def test_dataset_unavailable_shows_note_instead_of_500(auth_client, monkeypatch):
    monkeypatch.setattr("app.web.demo.dataset_available", lambda: False)
    html = auth_client.get("/demo").get_data(as_text=True)
    assert "Zestaw demo niedostępny" in html


def test_web_demo_only_wires_views():
    src = (Path(__file__).resolve().parent.parent / "app" / "web" / "demo.py").read_text(encoding="utf-8")
    assert "from app.services.demo_dataset import" in src
    assert "ingest(" in src and "DATASET_DIR" not in src and "json.load" not in src and "sha256" not in src
