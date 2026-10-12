"""Szablony list panelu: pager, wyszukiwarka dokumentów, filtry historii, stany puste i potwierdzenia usuwania."""
import html as htmllib
import re
from datetime import datetime
from pathlib import Path

from app.extensions import db
from app.models import STATUS_NEEDS_REVIEW, AuditLog, Document, Product, Supplier, Unit

ROOT = Path(__file__).resolve().parent.parent


def _docs(n, **kw):
    out = []
    for i in range(n):
        d = Document(sha256=f"{i:064d}", filename=f"f{i}.xml", **kw)
        db.session.add(d)
        out.append(d)
    db.session.commit()
    return out


def _get(client, url, **args):
    r = client.get(url, query_string=args) if args else client.get(url)
    assert r.status_code == 200, url
    return r.get_data(as_text=True)


def _pager(html):
    """Zawartość <nav aria-label="Stronicowanie"> albo None, gdy pagera nie ma."""
    m = re.search(r'<nav aria-label="Stronicowanie"[^>]*>(.*?)</nav>', html, re.S)
    return m.group(1) if m else None


def _href(html, label):
    """Adres (już odescapowany) linku, którego tekst to `label`."""
    m = re.search(r'<a [^>]*href="([^"]*)"[^>]*>\s*' + re.escape(label) + r"\s*</a>", html)
    assert m, label
    return htmllib.unescape(m.group(1))


def _h1(html):
    return re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S).group(1).strip()


# --- dokumenty i kolejka

def test_documents_pager_shows_count_and_next_link(auth_client, monkeypatch):
    from app.web import documents
    monkeypatch.setattr(documents, "DOCS_LIST_LIMIT", 2)
    ids = [d.id for d in _docs(3)]
    pager = _pager(_get(auth_client, "/dokumenty"))
    assert pager is not None
    assert "Pokazano 2 (najnowsze)" in pager
    assert 'rel="next"' in pager and _href(pager, "Starsze →") == f"/dokumenty?before={ids[1]}"
    assert "← Najnowsze" not in pager  # pierwsza strona — bez kursora w adresie
    pager = _pager(_get(auth_client, f"/dokumenty?before={ids[1]}"))
    assert "Pokazano 1" in pager and "Starsze →" not in pager
    assert _href(pager, "← Najnowsze") == "/dokumenty"


def test_pager_keeps_status_and_q_in_links(auth_client, monkeypatch):
    from app.web import documents
    monkeypatch.setattr(documents, "DOCS_LIST_LIMIT", 2)
    for i, d in enumerate(_docs(3)):
        d.number = f"FV/2026/{i}"
    db.session.commit()
    html = _get(auth_client, "/dokumenty", status="received", q="FV")
    nxt = _href(_pager(html), "Starsze →")
    assert "status=received" in nxt and "q=FV" in nxt and "before=" in nxt
    form = re.search(r'<form[^>]*role="search"[^>]*>(.*?)</form>', html, re.S).group(1)
    assert re.search(r'<input type="search" name="q" value="FV"[^>]*aria-label="[^"]+"', form)
    assert '<input type="hidden" name="status" value="received">' in form
    # przyciski statusów przenoszą frazę wyszukiwania
    assert _href(html, "Zatwierdzona") == "/dokumenty?status=approved&q=FV"
    assert _href(html, "Wszystkie") == "/dokumenty?q=FV"
    # bez filtra statusu nie ma ukrytego pola
    assert 'name="status"' not in _get(auth_client, "/dokumenty", q="FV").split('role="search"')[1].split("</form>")[0]


def test_queue_pager_labels_and_empty_state(auth_client, monkeypatch):
    from app.web import documents
    html = _get(auth_client, "/kolejka")
    assert "Kolejka pusta — wszystko wyjaśnione." in html and _pager(html) is None
    monkeypatch.setattr(documents, "DOCS_LIST_LIMIT", 2)
    ids = [d.id for d in _docs(3, status=STATUS_NEEDS_REVIEW)]
    pager = _pager(_get(auth_client, "/kolejka"))
    assert "Pokazano 2" in pager and "(najnowsze)" not in pager
    assert _href(pager, "Następne →") == f"/kolejka?after={ids[1]}" and 'rel="next"' in pager
    assert "Starsze" not in pager and "Najnowsze" not in pager and "← Pierwsze" not in pager
    pager = _pager(_get(auth_client, f"/kolejka?after={ids[1]}"))
    assert _href(pager, "← Pierwsze") == "/kolejka" and "Następne →" not in pager


def test_empty_page_with_cursor_links_back_instead_of_empty_state(auth_client):
    ids = [d.id for d in _docs(2, status=STATUS_NEEDS_REVIEW)]
    html = _get(auth_client, f"/kolejka?after={max(ids)}")
    assert "Kolejka pusta" not in html and "Brak dalszych dokumentów." in html
    assert _href(html, "← Pierwsze") == "/kolejka" and _href(_pager(html), "← Pierwsze") == "/kolejka"
    html = _get(auth_client, f"/dokumenty?before={min(ids)}")
    assert "Wgraj fakturę →" not in html and "Brak dalszych dokumentów." in html
    assert _href(html, "← Najnowsze") == "/dokumenty"
    db.session.add(AuditLog(user="ala@example.com", action="ingest", entity="document"))
    db.session.commit()
    html = _get(auth_client, "/historia?before=1")
    assert "Brak dalszych wpisów." in html and _href(html, "← Najnowsze") == "/historia"
    html = _get(auth_client, "/szablony?after=99999")
    assert "Brak dalszych szablonów." in html and "wgraj pierwszą fakturę" not in html
    assert _href(html, "← Pierwsze") == "/szablony"


def test_documents_empty_state_links_upload(auth_client):
    html = _get(auth_client, "/dokumenty")
    assert "Brak dokumentów." in html and _href(html, "Wgraj fakturę →") == "/wgraj"
    assert _pager(html) is None
    html = _get(auth_client, "/dokumenty", q="xyz")
    assert "Brak dokumentów pasujących do „xyz”." in html and "Wgraj fakturę →" not in html
    # partial jest też na pulpicie, gdzie nie ma `q` ani `next_url`
    html = _get(auth_client, "/pulpit")
    assert "Wgraj fakturę →" in html and "Kolejka pusta" not in html


def test_list_pages_wrap_tables_in_table_responsive(auth_client):
    from app.web.catalog import SPECS
    for url in ("/pulpit", "/dokumenty", "/kolejka", "/historia", "/szablony", *(spec.url for spec in SPECS)):
        html = _get(auth_client, url)
        assert re.search(r'<div class="table-responsive">\s*<table', html), url


def test_doc_table_truncates_filename_with_title_and_local_time(auth_client, app):
    app.config["DISPLAY_TZ"] = "Europe/Warsaw"
    name = "bardzo-dluga-nazwa-pliku-faktury-od-hurtowni-alfa-2026-01.xml"
    db.session.add(Document(sha256="a" * 64, filename=name, created_at=datetime(2026, 1, 15, 11, 30)))
    db.session.commit()
    for url in ("/dokumenty", "/pulpit"):
        html = _get(auth_client, url)
        assert f'<span class="d-inline-block text-truncate cell-truncate" title="{name}">{name}</span>' in html, url
        assert '<time datetime="2026-01-15T11:30:00Z"' in html and ">15.01.2026 12:30</time>" in html, url


# --- historia

def test_history_polish_action_label_and_filter_form(auth_client, app):
    app.config["DISPLAY_TZ"] = "Europe/Warsaw"
    db.session.add(AuditLog(user="ala@example.com", action="ingest", entity="document", entity_id=1,
                            created_at=datetime(2026, 1, 15, 11, 30, 5)))
    db.session.add(AuditLog(user="ola@example.com", action="nieznana_akcja", entity="demo"))
    db.session.commit()
    html = _get(auth_client, "/historia")
    assert _h1(html) == "Historia"
    assert '<span title="ingest">Przyjęcie dokumentu</span>' in html
    assert '<span title="nieznana_akcja">nieznana_akcja</span>' in html  # brak etykiety — surowy kod
    assert ">15.01.2026 12:30:05</time>" in html  # |dts — z sekundami, czas lokalny
    form = re.search(r'<form[^>]*role="search"[^>]*>(.*?)</form>', html, re.S).group(1)
    assert re.search(r'<select[^>]*name="action"', form)
    assert '<option value="ingest">Przyjęcie dokumentu</option>' in form
    assert re.search(r'<input[^>]*name="user"[^>]*list="history-users"', form)
    assert '<datalist id="history-users">' in form and '<option value="ala@example.com">' in form
    html = _get(auth_client, "/historia", action="ingest", user="ala@example.com")
    assert '<option value="ingest" selected>Przyjęcie dokumentu</option>' in html
    assert re.search(r'<input[^>]*name="user"[^>]*value="ala@example.com"', html)
    assert "nieznana_akcja</span>" not in html


def test_history_payload_has_text_break(auth_client, monkeypatch):
    from app.web import history
    monkeypatch.setattr(history, "HISTORY_LIMIT", 1)
    for i in range(2):
        db.session.add(AuditLog(user="ala@example.com", action="ingest", entity="document", entity_id=i + 1,
                                payload={"plik": "x" * 200}))
    db.session.commit()
    html = _get(auth_client, "/historia", action="ingest")
    assert '<code class="small text-break">' in html
    nxt = _href(_pager(html), "Starsze →")
    assert "action=ingest" in nxt and "before=" in nxt


# --- listy CRUD

def test_crud_delete_confirm_contains_singular_and_name(auth_client):
    db.session.add(Supplier(name="Hurtownia Alfa", tax_id="PL9990000011"))
    db.session.commit()
    html = _get(auth_client, "/dostawcy")
    assert 'data-confirm="Usunąć dostawcę „Hurtownia Alfa”?"' in html
    p = Product.query.order_by(Product.code).first()
    html = _get(auth_client, "/towary")
    assert f'data-confirm="Usunąć towar „{p.code} — {p.name}”?"' in html
    assert 'data-confirm="Usunąć?"' not in html


def test_crud_empty_state_add_and_import_links(auth_client):
    Product.query.delete()
    db.session.commit()
    html = _get(auth_client, "/towary")
    empty = re.search(r'<td colspan="\d+" class="text-muted">(.*?)</td>', html, re.S).group(1)
    assert "Brak rekordów." in empty
    assert _href(empty, "Nowy towar →") == "/towary/nowy"  # R12: etykieta akcji ze spec.new_label
    assert "Dodaj pierwszy" not in html
    assert _href(empty, "Import CSV") == "/towary/import"
    assert _href(html, "Nowy towar") == "/towary/nowy"  # przycisk w nagłówku = spec.new_label
    html = _get(auth_client, "/dostawcy")
    assert _href(html, "Nowy dostawca →") == "/dostawcy/nowy" and "Import CSV" not in html
    html = _get(auth_client, "/dostawcy", q="zzz")
    assert "Brak rekordów pasujących do „zzz”." in html


def test_crud_numbered_pager_alphabetical(auth_client, monkeypatch):
    from app.web import crud
    monkeypatch.setattr(crud, "CRUD_PAGE_SIZE", 2)
    codes = [u.code for u in Unit.query.order_by(Unit.code)]
    pages = -(-len(codes) // 2)
    assert pages >= 2
    html = _get(auth_client, "/jednostki")
    pager = _pager(html)
    assert f"Strona 1 z {pages}" in pager and "← Poprzednia" not in pager
    assert _href(pager, "Następna →") == "/jednostki?page=2" and 'rel="next"' in pager
    cells = re.findall(r"<tr>\s*<td>([^<]*)</td>", html)
    assert cells == codes[:2]  # porządek alfabetyczny spec.order_by
    pager = _pager(_get(auth_client, f"/jednostki?page={pages}"))
    assert f"Strona {pages} z {pages}" in pager and "Następna →" not in pager
    assert _href(pager, "← Poprzednia") == f"/jednostki?page={pages - 1}" and 'rel="prev"' in pager
    monkeypatch.setattr(crud, "CRUD_PAGE_SIZE", 200)
    assert _pager(_get(auth_client, "/jednostki")) is None  # jedna strona — bez pagera


def test_crud_search_box_only_for_specs_with_search_fields(auth_client):
    from app.web.catalog import SPECS
    for spec in SPECS:
        html = _get(auth_client, spec.url, q="kg")
        has_form = re.search(r'<form[^>]*role="search"', html) is not None
        assert has_form == bool(spec.search_fields), spec.key
        if spec.search_fields:
            assert re.search(r'<input type="search" name="q" value="kg"[^>]*aria-label="[^"]+"', html), spec.key


def test_headings_match_menu_labels(auth_client):
    from app.web.catalog import SPECS
    pages = [("/dokumenty", "Dokumenty"), ("/historia", "Historia"), ("/szablony", "Szablony")]
    pages += [(spec.url, spec.title) for spec in SPECS]
    for url, label in pages:
        html = _get(auth_client, url)
        assert _h1(html) == label, url
        assert re.search(r'aria-current="page" href="[^"]*">' + re.escape(label) + "</a>", html), url
