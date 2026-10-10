from app.models import Document


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
