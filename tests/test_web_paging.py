"""Stronicowanie list panelu, wyszukiwarka dokumentów, filtry i etykiety historii, CrudSpec z nazwami z menu."""
import re
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from flask import template_rendered

from app.extensions import db
from app.models import AuditLog, Document, Supplier, Template, TemplateVersion, Unit
from app.web import paging

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def captured(app):
    """Kontekst ostatnio wyrenderowanego szablonu (szablony dostaną nowe klucze dopiero w F2)."""
    seen = []

    def record(sender, template, context, **extra):
        seen.append(context)
    template_rendered.connect(record, app)
    try:
        yield seen
    finally:
        template_rendered.disconnect(record, app)


def _docs(n, **kw):
    out = []
    for i in range(n):
        d = Document(sha256=f"{i:064d}", filename=f"f{i}.xml", **kw)
        db.session.add(d)
        out.append(d)
    db.session.commit()
    return out


# --- helper app/web/paging.py

def test_page_by_id_desc_returns_next_cursor_only_when_more(app):
    docs = _docs(5)
    ids = [d.id for d in docs]
    rows, cur = paging.page_by_id(Document.query, Document.id, 2)
    assert [r.id for r in rows] == [ids[4], ids[3]] and cur == ids[3]
    rows, cur = paging.page_by_id(Document.query, Document.id, 2, before=cur)
    assert [r.id for r in rows] == [ids[2], ids[1]] and cur == ids[1]
    rows, cur = paging.page_by_id(Document.query, Document.id, 2, before=cur)
    assert [r.id for r in rows] == [ids[0]] and cur is None
    rows, cur = paging.page_by_id(Document.query, Document.id, 5)  # dokładnie pełna strona — brak dalszej
    assert len(rows) == 5 and cur is None


def test_page_by_id_asc_with_after(app):
    ids = [d.id for d in _docs(5)]
    rows, cur = paging.page_by_id(Document.query, Document.id, 2, after=0)  # 0 = od początku, rosnąco
    assert [r.id for r in rows] == ids[:2] and cur == ids[1]
    rows, cur = paging.page_by_id(Document.query, Document.id, 2, after=cur)
    assert [r.id for r in rows] == ids[2:4] and cur == ids[3]
    rows, cur = paging.page_by_id(Document.query, Document.id, 2, after=cur)
    assert [r.id for r in rows] == ids[4:] and cur is None


def test_page_by_number_keeps_order_and_counts(seeded):
    q = Unit.query.order_by(Unit.code)
    codes = [u.code for u in q.all()]
    assert len(codes) >= 3
    rows, page, pages, total = paging.page_by_number(q, 2, 2)
    assert [u.code for u in rows] == codes[2:4]
    assert (page, total, pages) == (2, len(codes), -(-len(codes) // 2))
    rows, page, pages, total = paging.page_by_number(q, 2, 10_000)  # poza zakresem → ostatnia strona
    assert page == pages and [u.code for u in rows] == codes[(pages - 1) * 2:]
    rows, page, pages, total = paging.page_by_number(Unit.query.filter(Unit.code == "brak"), 2, None)
    assert (rows, page, pages, total) == ([], 1, 1, 0)


def test_bad_cursor_or_page_means_first_page(auth_client, app):
    for bad in ("abc", "0", "-3", "1.5", "99999999999999999999999", "١٢"):
        with app.test_request_context(f"/dokumenty?before={bad}&page={bad}"):
            assert paging.cursor_arg("before") is None
            assert paging.cursor_arg("page") is None
        r = auth_client.get(f"/dokumenty?before={bad}")
        assert r.status_code == 200
        r = auth_client.get(f"/dostawcy?page={bad}")
        assert r.status_code == 200
    with captured(app) as seen:
        auth_client.get("/jednostki?page=abc")
    assert seen[-1]["page"] == 1


def test_next_url_preserves_filters_and_view_args(app):
    with app.test_request_context("/dokumenty?status=approved&q=Alfa&before=7"):
        from flask import request
        request.url_rule = app.url_map.bind("localhost").match("/dokumenty", return_rule=True)[0]
        request.view_args = {}
        url = paging.next_url("before", 3)
        assert url.startswith("/dokumenty?") and "status=approved" in url and "q=Alfa" in url
        assert "before=3" in url and "before=7" not in url
        first = paging.first_url("before")
        assert "before" not in first and "status=approved" in first and "q=Alfa" in first
    with app.test_request_context("/szablony/5?a=1&b=2"):
        from flask import request
        rule, args = app.url_map.bind("localhost").match("/szablony/5", return_rule=True)
        request.url_rule, request.view_args = rule, args
        url = paging.next_url("page", 2)
        assert url.startswith("/szablony/5?") and "a=1" in url and "b=2" in url and "page=2" in url


def test_paging_links_ignore_reserved_and_view_arg_params(auth_client, app):
    """Parametry `_anchor`/`_external`/`_scheme`/`_method` i nazwy view_args nie trafiają do url_for (bez 500)."""
    from app.web import crud
    db.session.add_all([Supplier(name=f"Dostawca {i}", tax_id=f"PL99900003{i:02d}") for i in range(3)])
    db.session.commit()
    old_size = crud.CRUD_PAGE_SIZE
    crud.CRUD_PAGE_SIZE = 2
    try:
        with captured(app) as seen:
            r = auth_client.get("/dostawcy?_anchor=x&_external=1&_scheme=https&_method=POST&q=Dostawca")
    finally:
        crud.CRUD_PAGE_SIZE = old_size
    assert r.status_code == 200
    ctx = seen[-1]
    assert ctx["next_url"] == "/dostawcy?q=Dostawca&page=2" and ctx["first_url"] == "/dostawcy?q=Dostawca"
    _docs(2)
    assert auth_client.get("/dokumenty?before=999&_anchor=x&_external=1").status_code == 200


def test_paging_links_skip_params_colliding_with_view_args(app):
    @app.get("/test-stronicowania/<int:tid>")
    def _probe(tid):
        return {"next": paging.next_url("before", 3), "first": paging.first_url("before")}
    r = app.test_client().get("/test-stronicowania/5?tid=3&status=ok&before=9&_anchor=x&_external=1")
    assert r.status_code == 200
    assert r.json == {"next": "/test-stronicowania/5?status=ok&before=3", "first": "/test-stronicowania/5?status=ok"}


# --- dokumenty i kolejka

def test_documents_list_paginates_at_limit(auth_client, app, monkeypatch):
    from app.web import documents
    monkeypatch.setattr(documents, "DOCS_LIST_LIMIT", 2)
    ids = [d.id for d in _docs(3)]
    with captured(app) as seen:
        auth_client.get("/dokumenty")
    ctx = seen[-1]
    assert [d.id for d in ctx["docs"]] == [ids[2], ids[1]] and ctx["shown"] == 2
    assert ctx["next_url"] == f"/dokumenty?before={ids[1]}" and ctx["first_url"] is None
    with captured(app) as seen:
        auth_client.get(ctx["next_url"])
    ctx = seen[-1]
    assert [d.id for d in ctx["docs"]] == [ids[0]] and ctx["next_url"] is None
    assert ctx["first_url"] == "/dokumenty"
    assert ctx["title"] == "Dokumenty" and ctx["queue"] is False  # stare klucze zostają


def test_documents_search_by_number_and_supplier_name(auth_client, app):
    alfa = Supplier(name="Hurtownia Alfa", tax_id="PL9990000011")
    db.session.add(alfa)
    db.session.commit()
    a, b, c = _docs(3)
    a.number, a.supplier_id = "FV/2026/001", alfa.id
    b.number = "FV/2026/777"
    c.number = "50%_RABAT"
    db.session.commit()

    def found(q):
        with captured(app) as seen:
            assert auth_client.get("/dokumenty", query_string={"q": q}).status_code == 200
        return {d.id for d in seen[-1]["docs"]}, seen[-1]["q"]
    assert found("777") == ({b.id}, "777")
    assert found("hurtownia alfa")[0] == {a.id}
    assert found("  FV/2026  ")[0] == {a.id, b.id}
    assert found("%")[0] == {c.id}  # znaki LIKE dosłownie, nie jako wzorzec
    ids, q = found("x" * 300)
    assert q == "x" * 100 and ids == set()
    with captured(app) as seen:
        auth_client.get("/dokumenty", query_string={"q": "FV", "status": "received"})
    assert {d.id for d in seen[-1]["docs"]} == {a.id, b.id} and seen[-1]["current"] == "received"


def test_queue_fifo_with_after_cursor(auth_client, app, monkeypatch):
    from app.models import STATUS_NEEDS_REVIEW
    from app.web import documents
    monkeypatch.setattr(documents, "DOCS_LIST_LIMIT", 2)
    _docs(1)  # inny status — nie w kolejce
    ids = [d.id for d in _docs(3, status=STATUS_NEEDS_REVIEW)]
    with captured(app) as seen:
        auth_client.get("/kolejka")
    ctx = seen[-1]
    assert [d.id for d in ctx["docs"]] == ids[:2] and ctx["queue"] is True
    assert ctx["next_url"] == f"/kolejka?after={ids[1]}" and ctx["first_url"] is None
    with captured(app) as seen:
        auth_client.get(ctx["next_url"])
    ctx = seen[-1]
    assert [d.id for d in ctx["docs"]] == ids[2:] and ctx["next_url"] is None and ctx["first_url"] == "/kolejka"


# --- historia

def test_history_filters_by_action_and_user(auth_client, app):
    from app.web import history
    for user, action in (("ala@example.com", "ingest"), ("ola@example.com", "ingest"),
                         ("ala@example.com", "delete")):
        db.session.add(AuditLog(user=user, action=action, entity="document"))
    db.session.commit()

    def ctx(**args):
        with captured(app) as seen:
            assert auth_client.get("/historia", query_string=args).status_code == 200
        return seen[-1]
    rows = ctx(action="ingest")["rows"]
    assert {r.action for r in rows} == {"ingest"} and len(rows) == 2
    rows = ctx(action="ingest", user="ala@example.com")["rows"]
    assert [(r.user, r.action) for r in rows] == [("ala@example.com", "ingest")]
    c = ctx()
    assert {"ala@example.com", "ola@example.com"} <= set(c["users"]) and c["users"] == sorted(c["users"])
    assert dict(c["actions"]) == history.ACTION_LABELS
    assert c["labels"] is history.ACTION_LABELS
    assert ctx(action="x" * 500)["rows"] == []


def test_history_paginates_with_before(auth_client, app, monkeypatch):
    from app.web import history
    monkeypatch.setattr(history, "HISTORY_LIMIT", 2)
    for i in range(3):
        db.session.add(AuditLog(user="ala@example.com", action="ingest", entity="document", entity_id=i + 1))
    db.session.commit()
    with captured(app) as seen:
        auth_client.get("/historia?action=ingest")
    ctx = seen[-1]
    assert ctx["shown"] == 2 and "action=ingest" in ctx["next_url"] and "before=" in ctx["next_url"]
    with captured(app) as seen:
        auth_client.get(ctx["next_url"])
    assert seen[-1]["shown"] == 1 and seen[-1]["next_url"] is None


def test_history_action_labels_cover_all_audited_actions():
    from app.services.negotiation import ACTIONS
    from app.web.history import ACTION_LABELS
    found = set()
    for path in (ROOT / "app").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?<![\w.])(?<!def )audit\(\s*([^,)\n]+),", src):
            literals = re.findall(r'(f?)"([^"]*)"', m.group(1))
            # akcja spoza literałów (np. audit(zmienna, …)) — test musi o tym wiedzieć, a nie jej pominąć
            assert literals, f"{path}: audit() z nieliteralną akcją {m.group(1)!r}"
            for prefix, lit in literals:
                if prefix:  # f-string: jedyny wzorzec to resolve:{action} z negocjacji
                    assert lit == "resolve:{action}", f"{path}: nieznany wzorzec akcji {lit!r}"
                    found |= {f"resolve:{a}" for a in ACTIONS}
                else:
                    found.add(lit)
    assert {"ingest", "create", "update", "delete", "resolve:reject"} <= found
    assert found == set(ACTION_LABELS)
    assert all(isinstance(v, str) and v for v in ACTION_LABELS.values())


# --- listy CRUD

def test_crud_list_search_q(auth_client, app):
    db.session.add_all([Supplier(name="Hurtownia Alfa", tax_id="PL9990000021"),
                        Supplier(name="Piekarnia Beta", tax_id="PL9990000022")])
    db.session.commit()

    def names(url, **args):
        with captured(app) as seen:
            assert auth_client.get(url, query_string=args).status_code == 200
        return [getattr(r, "name", None) for r in seen[-1]["rows"]], seen[-1]

    assert names("/dostawcy", q="alfa")[0] == ["Hurtownia Alfa"]
    rows, ctx = names("/dostawcy", q="0000022")
    assert rows == ["Piekarnia Beta"] and ctx["q"] == "0000022" and ctx["total"] == 1
    assert names("/dostawcy", q="%")[0] == []
    rows, ctx = names("/towary", q="590")  # products: GTIN
    assert rows and all("590" in (p.gtin or "") or "590" in p.code or "590" in p.name for p in ctx["rows"])


def test_crud_list_pages_alphabetical(auth_client, app, monkeypatch):
    from app.web import crud
    monkeypatch.setattr(crud, "CRUD_PAGE_SIZE", 2)
    codes = [u.code for u in Unit.query.order_by(Unit.code)]
    seen_codes = []
    page = 1
    while True:
        with captured(app) as seen:
            auth_client.get(f"/jednostki?page={page}")
        ctx = seen[-1]
        assert ctx["page"] == page and ctx["total"] == len(codes) and ctx["pages"] == -(-len(codes) // 2)
        seen_codes += [u.code for u in ctx["rows"]]
        if ctx["next_url"] is None:
            break
        assert ctx["next_url"] == f"/jednostki?page={page + 1}"
        page += 1
    assert seen_codes == codes and page == ctx["pages"]
    assert ctx["prev_url"] == f"/jednostki?page={page - 1}" and ctx["first_url"] == "/jednostki"


def test_crud_flash_names_object(auth_client):
    html = auth_client.post("/dostawcy/nowy", data={"name": "Hurtownia Gamma", "tax_id": "PL9990000031"},
                            follow_redirects=True).get_data(as_text=True)
    assert "Zapisano dostawcę „Hurtownia Gamma”." in html
    s = Supplier.query.filter_by(name="Hurtownia Gamma").one()
    html = auth_client.post(f"/dostawcy/{s.id}/usun", follow_redirects=True).get_data(as_text=True)
    assert "Usunięto dostawcę „Hurtownia Gamma”." in html
    html = auth_client.post("/jednostki/nowy", data={"code": "paleta", "name": "Paleta"},
                            follow_redirects=True).get_data(as_text=True)
    assert "Zapisano jednostkę „paleta”." in html


def test_all_specs_have_singular_forms_and_titles_match_menu():
    from app.web.catalog import SPECS
    nav = (ROOT / "app/templates/_nav.html").read_text(encoding="utf-8")
    # pozycje menu „Dane” to makro dd_item(url_for('catalog.list_<key>'), 'Etykieta', 'key')
    menu = dict(re.findall(r"dd_item\(url_for\('catalog\.list_(\w+)'\), '([^']+)'", nav))
    assert len(SPECS) == len(menu) == 6
    for spec in SPECS:
        assert spec.title == menu[spec.key], spec.key
        assert spec.new_label.startswith(("Nowy ", "Nowa ", "Nowe ")), spec.key
        assert spec.singular_acc and spec.singular_acc == spec.singular_acc.lower(), spec.key
        assert callable(spec.display) or spec.display is None
        for name in spec.search_fields:
            assert isinstance(getattr(spec.model, name), sa.orm.attributes.InstrumentedAttribute), name
    by_key = {s.key: s for s in SPECS}
    assert by_key["suppliers"].search_fields == ("name", "tax_id")
    assert by_key["products"].search_fields == ("code", "name", "gtin")
    assert by_key["mappings"].search_fields == ("supplier_code", "supplier_gtin", "supplier_name_norm")
    assert by_key["units"].search_fields == ("code", "name")
    assert by_key["aliases"].search_fields == ("alias",)
    assert by_key["suppliers"].new_label == "Nowy dostawca"


# --- szablony

def _templates(n):
    for i in range(n):
        s = Supplier(name=f"Dostawca {i}", tax_id=f"PL99900001{i:02d}")
        db.session.add(s)
        db.session.flush()
        t = Template(name=f"Szablon {i}", supplier_id=s.id)
        db.session.add(t)
        db.session.flush()
        v = TemplateVersion(template_id=t.id, version=1, rules={}, comment="start")
        db.session.add(v)
        db.session.flush()
        t.active_version_id = v.id
        _docs_for(t, i + 1)
    db.session.commit()


def _docs_for(t, n):
    for j in range(n):
        db.session.add(Document(sha256=f"{t.id:032d}{j:032d}", template_id=t.id))


def _count_index_queries(app, client):
    statements = []

    def listener(conn, cursor, statement, *args):
        statements.append(statement)
    db.session.expire_all()  # obiekty z testu nieaktualne — liczymy realne zapytania widoku
    sa.event.listen(db.engine, "before_cursor_execute", listener)
    try:
        with captured(app) as seen:
            assert client.get("/szablony").status_code == 200
    finally:
        sa.event.remove(db.engine, "before_cursor_execute", listener)
    return statements, seen[-1]


def test_templates_index_single_count_query(auth_client, app):
    _templates(2)
    few, _ = _count_index_queries(app, auth_client)
    for i in range(2, 6):
        s = Supplier(name=f"Dostawca X{i}", tax_id=f"PL99900002{i:02d}")
        db.session.add(s)
        db.session.flush()
        t = Template(name=f"Szablon X{i}", supplier_id=s.id)
        db.session.add(t)
        db.session.flush()
        _docs_for(t, i)
    db.session.commit()
    many, ctx = _count_index_queries(app, auth_client)
    assert len([s for s in many if "FROM documents" in s]) == 1
    assert len(many) == len(few)  # liczba zapytań nie rośnie z liczbą szablonów (bez N+1)
    counts = {r["t"].name: r["docs"] for r in ctx["rows"]}
    assert counts["Szablon 0"] == 1 and counts["Szablon 1"] == 2 and counts["Szablon X5"] == 5
    assert {r["t"].name: (r["active"].version if r["active"] else None) for r in ctx["rows"]}["Szablon 1"] == 1
    assert ctx["shown"] == 6 and ctx["next_url"] is None


def test_templates_index_paginates(auth_client, app, monkeypatch):
    from app.web import templates_views
    monkeypatch.setattr(templates_views, "TEMPLATES_PAGE_SIZE", 1)
    _templates(2)
    with captured(app) as seen:
        auth_client.get("/szablony")
    ctx = seen[-1]
    assert [r["t"].name for r in ctx["rows"]] == ["Szablon 0"] and "after=" in ctx["next_url"]
    with captured(app) as seen:
        auth_client.get(ctx["next_url"])
    assert [r["t"].name for r in seen[-1]["rows"]] == ["Szablon 1"] and seen[-1]["next_url"] is None
