"""Polskie strony błędów panelu (403/404/405/413/500) — API nadal zwraca JSON."""
from app.extensions import db
from app.models import User

KEY = {"X-API-Key": "xp_test_demo_key"}


def _assert_shell(html):
    """Strona błędu ma pełną skorupę panelu: nawigację, link do Pulpitu i Pomocy oraz stopkę z kredytami."""
    assert "<nav" in html
    assert '<a class="btn btn-primary" href="/">Wróć do Pulpitu</a>' in html
    assert 'href="/pomoc"' in html
    assert "<footer" in html and "dev@attv.uk" in html


def test_panel_404_is_polish_page_with_nav(auth_client):
    r = auth_client.get("/nie-ma-takiej-strony")
    html = r.get_data(as_text=True)
    assert r.status_code == 404
    assert "Nie znaleziono strony" in html
    _assert_shell(html)
    assert "Not Found" not in html


def test_panel_405_polish_page(auth_client):
    r = auth_client.post("/pulpit")
    html = r.get_data(as_text=True)
    assert r.status_code == 405
    assert "Metoda niedozwolona" in html
    _assert_shell(html)
    assert "Method Not Allowed" not in html


def test_panel_403_for_non_admin_demo_reset(seeded, client):
    u = User(email="operator@example.com", role="operator")
    u.set_password("operator-haslo-1")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"email": "operator@example.com", "password": "operator-haslo-1"})
    r = client.post("/demo/reset")
    html = r.get_data(as_text=True)
    assert r.status_code == 403
    assert "Brak uprawnień" in html
    _assert_shell(html)
    assert "Forbidden" not in html


def test_upload_413_redirects_to_form_with_flash(auth_client, app):
    app.config["MAX_CONTENT_LENGTH"] = 1000
    r = auth_client.post("/wgraj", data={"file": (__import__("io").BytesIO(b"x" * 5000), "a.xml")},
                         content_type="multipart/form-data")
    assert r.status_code == 302 and r.headers["Location"].endswith("/wgraj")
    html = auth_client.get("/wgraj").get_data(as_text=True)
    assert "za duży" in html


def test_panel_413_outside_upload_renders_page(seeded, app):
    app.config["MAX_CONTENT_LENGTH"] = 1000

    @app.post("/test-formularz")
    def form_view():
        return str(len(__import__("flask").request.form))

    client = app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    r = client.post("/test-formularz", data={"x": "y" * 5000})
    html = r.get_data(as_text=True)
    assert r.status_code == 413
    assert "Plik jest za duży" in html
    _assert_shell(html)
    assert "Request Entity Too Large" not in html


def test_panel_500_polish_without_details(seeded, app):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/test-boom")
    def boom():
        raise RuntimeError("tajny-szczegol-wyjatku")

    client = app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    r = client.get("/test-boom")
    html = r.get_data(as_text=True)
    assert r.status_code == 500
    assert "Błąd serwera" in html
    _assert_shell(html)
    assert "tajny-szczegol-wyjatku" not in html and "RuntimeError" not in html


def test_panel_overflow_renders_404_page(seeded, app):
    @app.get("/test-overflow")
    def overflow_view():
        raise OverflowError("Python int too large to convert to SQLite INTEGER")

    client = app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    r = client.get("/test-overflow")  # ścieżka spoza /api/ — musi przejść przez handler OverflowError
    html = r.get_data(as_text=True)
    assert r.status_code == 404
    assert "Nie znaleziono strony" in html
    _assert_shell(html)
    assert "SQLite" not in html
    assert client.get("/dokumenty/99999999999999999999999").status_code == 404


def test_error_pages_keep_security_headers(auth_client):
    r = auth_client.get("/nie-ma-takiej-strony")
    assert r.status_code == 404
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"


def test_api_errors_still_json(seeded, client):
    r = client.get("/api/v1/nie-ma", headers=KEY)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    r = client.delete("/api/v1/documents", headers=KEY)
    assert r.status_code == 405 and r.get_json()["error"]["code"] == "method_not_allowed"
