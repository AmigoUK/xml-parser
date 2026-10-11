"""Sekcja „Pomoc”: strony publiczne, integracja z panelem, spójność rejestrów z kodem źródłowym."""
import json
import re
from pathlib import Path

import pytest
from flask import render_template_string

from app.engine.transforms import REGISTRY, TransformContext, apply_chain
from app.help_content import ISSUE_HELP, STATUS_HELP, TOPICS, TRANSFORM_HELP
from app.ingest import read_document
from app.models import STATUS_LABELS, Document

ROOT = Path(__file__).resolve().parent.parent
FOOTER = "Project &amp; Development"
ALL_PAGES = ["/pomoc"] + [f"/pomoc/{t['slug']}" for t in TOPICS]

# Emisja problemu: Issue("kod", …) w app/ oraz _issue("kod", …) w migracjach danych.
ISSUE_EMIT = re.compile(r"\b_?[Ii]ssue\(\s*[\"']([a-z_]+)[\"']")


def _sources():
    files = sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "migrations" / "versions").glob("*.py"))
    return [(p, p.read_text(encoding="utf-8")) for p in files]


def emitted_issue_codes() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path, text in _sources():
        for code in ISSUE_EMIT.findall(text):
            found.setdefault(code, set()).add(str(path.relative_to(ROOT)))
    return found


# --- strony ---

@pytest.mark.parametrize("path", ALL_PAGES)
def test_help_pages_public_with_title_and_footer(client, path):
    r = client.get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert FOOTER in html
    slug = path.rsplit("/", 1)[-1]
    title = next((t["title"] for t in TOPICS if t["slug"] == slug), "Pomoc")
    assert f"<h1 class=\"h3" in html and title in html
    assert "<script>" not in html and "onclick=" not in html  # CSP: bez inline JS


def test_help_index_lists_topics_and_quick_start(client):
    html = client.get("/pomoc").get_data(as_text=True)
    assert "Szybki start w 5 krokach" in html
    for t in TOPICS:
        assert f'href="/pomoc/{t["slug"]}"' in html


def test_topic_layout_has_menu_breadcrumbs_and_pager(client):
    html = client.get("/pomoc/szablony").get_data(as_text=True)
    assert 'class="breadcrumb-item"><a href="/pomoc">Pomoc</a>' in html
    assert re.search(r'list-group-item-action active"\s+href="/pomoc/szablony"', html)
    i = [t["slug"] for t in TOPICS].index("szablony")
    assert f'href="/pomoc/{TOPICS[i - 1]["slug"]}" rel="prev"' in html
    assert f'href="/pomoc/{TOPICS[i + 1]["slug"]}" rel="next"' in html
    first = client.get(f"/pomoc/{TOPICS[0]['slug']}").get_data(as_text=True)
    assert 'rel="prev"' not in first


def test_unknown_slug_404(client):
    assert client.get("/pomoc/nie-ma-takiego").status_code == 404
    assert client.get("/pomoc/_layout").status_code == 404


def test_nav_has_help_link_logged_out_and_in(client, auth_client):
    assert 'href="/pomoc">Pomoc</a>' in client.get("/pomoc").get_data(as_text=True)
    assert 'href="/pomoc">Pomoc</a>' in auth_client.get("/pulpit").get_data(as_text=True)


def test_demo_page_links_help(seeded, client):
    assert 'href="/pomoc"' in client.get("/demo").get_data(as_text=True)


# --- integracja z panelem ---

def _load_alfa(auth_client) -> Document:
    auth_client.post("/demo/wczytaj/alfa-1.xml")
    return Document.query.order_by(Document.id.desc()).first()


def test_editor_links_help_in_new_tab(auth_client):
    doc = _load_alfa(auth_client)
    html = auth_client.get(f"/szablony/dokument/{doc.id}/edytor").get_data(as_text=True)
    assert re.search(r'href="/pomoc/edytor-mapowan" target="_blank" rel="noopener">\? Pomoc</a>', html)
    assert FOOTER not in html  # edytor pełnoekranowy — bez stopki


def test_document_issues_link_to_help(auth_client):
    doc = _load_alfa(auth_client)
    html = auth_client.get(f"/dokumenty/{doc.id}").get_data(as_text=True)
    for code in {i["code"] for i in doc.issues}:
        assert f'href="/pomoc/statusy-i-problemy#{code}"' in html


def test_issue_card_link_only_for_registered_code(app):
    tpl = ('{% from "_issues.html" import issue_card with context %}'
           '{{ issue_card(doc, 0, issue, ctx) }}')
    ctx = {"field_labels": {}, "leaf_paths": [], "units": [], "products": [], "suppliers": []}
    base = {"severity": "warning", "message": "m", "field": None, "suggestions": [], "source_path": None}
    with app.test_request_context("/"):
        known = render_template_string(tpl, doc=Document(id=1), ctx=ctx, issue={**base, "code": "sum_mismatch_line"})
        unknown = render_template_string(tpl, doc=Document(id=1), ctx=ctx, issue={**base, "code": "kod_spoza_rejestru"})
    assert 'href="/pomoc/statusy-i-problemy#sum_mismatch_line"' in known and ">?</a>" in known
    assert "/pomoc/" not in unknown


# --- spójność rejestrów z kodem ---

def test_issue_registry_matches_emitted_codes():
    emitted = emitted_issue_codes()
    assert len(emitted) >= 10, "wzorzec emisji problemów przestał cokolwiek znajdować"
    missing = sorted(set(emitted) - set(ISSUE_HELP))
    stale = sorted(set(ISSUE_HELP) - set(emitted))
    assert not missing, f"kody problemów bez wpisu w ISSUE_HELP: {missing} ({[emitted[c] for c in missing]})"
    assert not stale, f"wpisy ISSUE_HELP bez emisji w kodzie źródłowym: {stale}"


def test_issue_constructors_use_literal_codes():
    """Każde Issue(...) w app/ ma kod jako literał — inaczej skaner rejestru by go nie zobaczył."""
    bad = []
    for path, text in _sources():
        for m in re.finditer(r"(?<![\w.])Issue\(", text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            if text[line_start:m.start()].lstrip().startswith("class"):
                continue
            if not ISSUE_EMIT.match(text, m.start()):
                bad.append(f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, m.start()) + 1}")
    assert not bad, f"Issue() bez literału kodu: {bad}"


def test_issue_registry_entries_complete(client):
    html = client.get("/pomoc/statusy-i-problemy").get_data(as_text=True)
    for code, h in ISSUE_HELP.items():
        assert h["title"] and h["description"] and h["how_to_fix"]
        assert h["blocking"] in ("tak", "nie", "zależnie")
        assert h["blocking"] != "zależnie" or h.get("blocking_note")
        assert f'id="{code}"' in html


def test_statuses_match_model(client):
    assert set(STATUS_HELP) == set(STATUS_LABELS)
    html = client.get("/pomoc/statusy-i-problemy").get_data(as_text=True)
    for code, label in STATUS_LABELS.items():
        assert f"<code>{code}</code>" in html and label in html


def test_transform_help_covers_registry(client):
    assert set(TRANSFORM_HELP) == set(REGISTRY)
    html = client.get("/pomoc/edytor-mapowan").get_data(as_text=True)
    for name in REGISTRY:
        assert f'id="t-{name}"' in html


@pytest.mark.parametrize("name", sorted(TRANSFORM_HELP))
def test_transform_examples_are_true(name):
    h = TRANSFORM_HELP[name]
    tree = read_document("<Faktura><Sprzedawca><Ulica>Polna 1</Ulica><Miasto>Opole</Miasto></Sprzedawca></Faktura>"
                         .encode())
    step = json.loads(h["step"])
    assert apply_chain(h["input"], [step], TransformContext(tree)) == h["output"]


# --- limity i przykłady ---

def test_limits_follow_configuration(app, client):
    app.config.update(MAX_DOCUMENT_BYTES=3 * 1024 * 1024, MAX_LINES=1234, MAX_TREE_NODES=54321)
    for path in ("/pomoc", "/pomoc/api", "/pomoc/faq"):
        html = client.get(path).get_data(as_text=True)
        assert "3 MB" in html and "1 234" in html and "54 321" in html, path
        assert "10 MB" not in html and "200 000" not in html and "5 000 pozycji" not in html


def test_import_and_list_limits_from_code(client):
    from app.api.routes import LIST_MAX_LIMIT
    from app.web.catalog import MAX_IMPORT_ROWS
    assert f"{MAX_IMPORT_ROWS:,}".replace(",", " ") in client.get("/pomoc/towary").get_data(as_text=True)
    assert f"maks. {LIST_MAX_LIMIT}" in client.get("/pomoc/api").get_data(as_text=True)


def test_curl_examples_use_request_host(client):
    html = client.get("/pomoc/api", base_url="http://faktury.example.test:18555").get_data(as_text=True)
    assert "http://faktury.example.test:18555/api/v1/documents" in html
    assert "http://faktury.example.test:18555/api/v1/documents/42/reprocess" in html
    assert "http://faktury.example.test:18555/api/v1/suppliers" in html
    assert "TWÓJ_KLUCZ" in html and "X-API-Key" in html
    assert "localhost" not in html
