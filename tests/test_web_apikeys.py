"""Panel kluczy API: flashe po akcjach, etykiety formularzy, limity długości, potwierdzenia i pusty stan."""
import html as htmllib

from app.extensions import db
from app.models import ApiKey
from app.services.apikeys import create_key


def _key(name="System ERP"):
    key, _ = create_key(name)
    db.session.commit()
    return key


def _text(r):
    return htmllib.unescape(r.get_data(as_text=True))


def test_toggle_flashes_new_state(auth_client):
    k = _key()
    r = auth_client.post(f"/klucze-api/{k.id}/przelacz", follow_redirects=True)
    assert "Klucz „System ERP” wyłączony." in _text(r)
    r = auth_client.post(f"/klucze-api/{k.id}/przelacz", follow_redirects=True)
    assert "Klucz „System ERP” włączony." in _text(r)


def test_rename_empty_flashes_error_and_keeps_name(auth_client):
    k = _key()
    r = auth_client.post(f"/klucze-api/{k.id}/nazwa", data={"name": "  "}, follow_redirects=True)
    assert "Podaj nową nazwę klucza." in _text(r)
    assert db.session.get(ApiKey, k.id).name == "System ERP"


def test_rename_flashes_new_name(auth_client):
    k = _key()
    r = auth_client.post(f"/klucze-api/{k.id}/nazwa", data={"name": "Magazyn"}, follow_redirects=True)
    assert "Zmieniono nazwę klucza na „Magazyn”." in _text(r)
    assert db.session.get(ApiKey, k.id).name == "Magazyn"


def test_delete_flashes_name(auth_client):
    k = _key("Do usunięcia")
    r = auth_client.post(f"/klucze-api/{k.id}/usun", follow_redirects=True)
    assert "Usunięto klucz „Do usunięcia”." in _text(r)
    r = auth_client.post("/klucze-api/999999/usun", follow_redirects=True)
    assert "Nie znaleziono klucza." in _text(r)


def test_page_markup_labels_maxlength_confirms(auth_client):
    k = _key()
    html = _text(auth_client.get("/klucze-api"))
    assert 'for="new-key-name"' in html and 'id="new-key-name"' in html
    assert "w-form-key" in html and "table-responsive" in html
    assert f'maxlength="{ApiKey.name.type.length}"' in html
    assert 'aria-label="Nowa nazwa klucza"' in html and "Zmień nazwę" in html
    assert 'data-confirm="Wyłączyć klucz „System ERP”? Systemy używające go przestaną działać."' in html
    assert "<time " in html or k.last_used_at is None
    # klucz wyłączony: bez potwierdzenia przy włączaniu
    k.active = False
    db.session.commit()
    html = _text(auth_client.get("/klucze-api"))
    assert "Wyłączyć klucz „System ERP”" not in html


def test_empty_keys_state(auth_client):
    ApiKey.query.delete()
    db.session.commit()
    assert "Brak kluczy — utwórz pierwszy powyżej." in _text(auth_client.get("/klucze-api"))
