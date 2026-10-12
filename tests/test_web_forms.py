"""Formularze panelu: etykiety i autocomplete logowania, wymagany plik, blokada podwójnego wysłania,
nagłówki i limity formularza CRUD."""
import re

from app.extensions import db
from app.models import Supplier


def test_login_autocomplete_and_email_refilled_after_error(seeded, client):
    html = client.get("/login").get_data(as_text=True)
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html
    assert 'for="login-email"' in html and 'id="login-email"' in html
    assert 'for="login-password"' in html and 'id="login-password"' in html
    r = client.post("/login", data={"email": "admin@example.com", "password": "zle"})
    html = r.get_data(as_text=True)
    assert 'value="admin@example.com"' in html
    assert "zle" not in html.split("<form", 1)[1]  # hasła nigdy nie odsyłamy


def test_upload_form_required_hint_and_submit_lock(auth_client, app):
    html = auth_client.get("/wgraj").get_data(as_text=True)
    assert 'for="file"' in html and 'id="file"' in html
    assert re.search(r"<input[^>]*name=\"file\"[^>]*required", html)
    assert f"Maks. {app.config['MAX_DOCUMENT_BYTES'] // (1024 * 1024)} MiB; XML, JSON lub CSV." in html
    assert '@submit="submitted()"' in html
    assert ':disabled="submitting"' in html
    assert 'x-text="submitLabel()"' in html


def test_crud_form_headings_use_new_label_and_record_name(auth_client, app):
    html = auth_client.get("/dostawcy/nowy").get_data(as_text=True)
    assert "<h1 class=\"h4 mb-3\">Nowy dostawca</h1>" in html
    assert "w-form-narrow" in html
    sup = Supplier(name="Hurtownia Alfa", tax_id="9990000001")
    db.session.add(sup)
    db.session.commit()
    html = auth_client.get(f"/dostawcy/{sup.id}/edycja").get_data(as_text=True)
    assert f"Dostawcy — edycja „{sup.name}”" in html


def test_crud_textarea_maxlength_and_number_inputmode(auth_client):
    html = auth_client.get("/dostawcy/nowy").get_data(as_text=True)
    assert re.search(r"<textarea[^>]*maxlength=\"2000\"", html)
    html = auth_client.get("/przeliczniki/nowy").get_data(as_text=True)
    assert 'inputmode="decimal"' in html
    assert 'placeholder="' in html


def test_forms_have_no_static_inline_style(auth_client):
    for url in ("/dostawcy/nowy", "/towary/import", "/wgraj"):
        assert "style=" not in auth_client.get(url).get_data(as_text=True), url
    auth_client.post("/logout")
    assert "style=" not in auth_client.get("/login").get_data(as_text=True)
