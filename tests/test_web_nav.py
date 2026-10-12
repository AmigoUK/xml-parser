"""Nawigacja panelu: aktywna pozycja (aria-current) oraz atrybuty ARIA togglera i menu „Dane”."""
import re

from app.models import Document


def test_exactly_one_active_item_on_dashboard(auth_client):
    html = auth_client.get("/pulpit").get_data(as_text=True)
    assert html.count('aria-current="page"') == 1
    assert 'aria-current="page" href="/pulpit">Pulpit</a>' in html


def test_catalog_page_activates_dane_and_item(auth_client):
    html = auth_client.get("/jednostki").get_data(as_text=True)
    assert html.count('aria-current="page"') == 1
    assert 'aria-current="page" href="/jednostki">Jednostki</a>' in html
    toggle = re.search(r'<a [^>]*id="nav-dane"[^>]*>', html).group(0)
    assert "active" in toggle
    # edycja/nowy rekord też zostawia aktywne menu Dane
    nowy = auth_client.get("/dostawcy/nowy").get_data(as_text=True)
    assert "active" in re.search(r'<a [^>]*id="nav-dane"[^>]*>', nowy).group(0)


def test_document_detail_activates_documents(auth_client):
    auth_client.post("/demo/wczytaj/alfa-1.xml")
    doc = Document.query.order_by(Document.id.desc()).first()
    html = auth_client.get(f"/dokumenty/{doc.id}").get_data(as_text=True)
    assert html.count('aria-current="page"') == 1
    assert 'aria-current="page" href="/dokumenty">Dokumenty</a>' in html


def test_help_link_markup_exact(client, auth_client):
    assert 'href="/pomoc">Pomoc</a>' in client.get("/pomoc").get_data(as_text=True)
    html = auth_client.get("/pomoc").get_data(as_text=True)
    assert 'aria-current="page" href="/pomoc">Pomoc</a>' in html


def test_password_link_and_logout_present(auth_client):
    html = auth_client.get("/pulpit").get_data(as_text=True)
    assert 'href="/konto/haslo"' in html
    assert "Wyloguj" in html


def test_toggler_and_dropdown_aria_attributes(auth_client):
    html = auth_client.get("/pulpit").get_data(as_text=True)
    assert 'aria-controls="nav"' in html
    assert 'aria-label="Przełącz nawigację"' in html
    assert 'id="nav"' in html
    assert 'id="nav-dane"' in html and 'role="button"' in html
    assert 'aria-labelledby="nav-dane"' in html
    assert html.count('aria-expanded="false"') == 2


def test_no_active_item_on_login_page(client):
    html = client.get("/login").get_data(as_text=True)
    assert "aria-current" not in html


def test_demo_page_activates_o_demo(auth_client):
    html = auth_client.get("/demo").get_data(as_text=True)
    assert html.count('aria-current="page"') == 1
    assert 'aria-current="page" href="/">O demo</a>' in html
