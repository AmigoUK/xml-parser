"""Sekcja „Pomoc”: strony publiczne, integracja z panelem, spójność rejestrów z kodem źródłowym."""
import json
import re
import struct
from pathlib import Path

import pytest
from flask import render_template_string

from app.engine.transforms import REGISTRY, TransformContext, apply_chain
from app.help_content import FAQ, ISSUE_HELP, STATUS_HELP, TOPICS, TRANSFORM_HELP
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
    assert "<h1 class=\"h3" in html and title in html
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


# --- zrzuty ekranu ---

SCREENSHOTS_DIR = ROOT / "app" / "static" / "screenshots"

# temat → zrzuty z app/static/screenshots/ w kolejności na stronie (tools/screenshots.py; diagram renderowany z Mermaid)
HELP_SHOTS = {
    "jak-to-dziala": ["diagram-przetwarzania-td.png", "02-pulpit.png"],
    "pierwsza-faktura": ["03-kolejka.png", "04-dokument.png"],
    "zestaw-demo": ["14-demo-zestaw.png"],
    "edytor-mapowan": ["05-edytor-mapowan.png"],
    "szablony": ["10-szablony.png"],
    "jednostki": ["07-przeliczniki.png"],
    "towary": ["06-kartoteka.png"],
    "statusy-i-problemy": ["04-dokument.png"],
    "api": ["11-api-docs.png"],
    "faq": ["13-faq-worek.png"],
}
NO_SHOTS = {"integracja"}  # zrzut tej strony jest tylko w README


def _shots(html: str) -> list:
    import lxml.html
    figures = lxml.html.fromstring(html).xpath("//figure")
    return [f for f in figures if "help-shot" in (f.get("class") or "").split()]


def _png_size(name: str) -> tuple[int, int]:
    header = (SCREENSHOTS_DIR / name).read_bytes()[:24]
    return struct.unpack(">II", header[16:24])


@pytest.mark.parametrize("slug, files", HELP_SHOTS.items())
def test_topic_screenshots_with_captions(client, slug, files):
    """Zrzut to figure.help-shot: obrazek z wymiarami pliku (bez skoku układu) i własnym alt różnym od podpisu,
    link do pełnego obrazu w nowej karcie z wskazówką także dla czytnika ekranu, podpis."""
    figures = _shots(client.get(f"/pomoc/{slug}").get_data(as_text=True))
    assert [f.xpath(".//img/@src")[0].rsplit("/", 1)[-1] for f in figures] == files
    for f, name in zip(figures, files):
        (img,), (link,), (caption,) = f.xpath(".//img"), f.xpath(".//a"), f.xpath(".//figcaption")
        text = " ".join(caption.text_content().split())
        assert text and img.get("alt") and img.get("alt") != text, name  # alt opisuje obrazek, podpis go omawia
        assert (int(img.get("width")), int(img.get("height"))) == _png_size(name), name
        assert img.get("src").startswith("/static/screenshots/") and link.get("href") == img.get("src")
        assert link.get("target") == "_blank" and link.get("rel") == "noopener"
        assert "nowej karcie" in link.get("title"), name
        hints = link.xpath('./span[contains(@class, "visually-hidden")]')  # wskazówka dla czytnika ekranu w linku
        assert len(hints) == 1 and "nowej karcie" in hints[0].text_content(), name
        assert "img-fluid" in img.get("class").split() and img.get("loading") == "lazy"
        assert ("help-shot-full" in f.get("class").split()) == (name == "diagram-przetwarzania-td.png"), name


def test_screenshot_size_reads_png_header_and_tolerates_missing_file(app):
    from app.web.help import screenshot_size
    assert screenshot_size("02-pulpit.png") == _png_size("02-pulpit.png")
    assert screenshot_size("nie-ma-takiego.png") is None


def test_screenshot_size_ignores_files_that_are_not_png(app, monkeypatch, tmp_path):
    """Plik, który nie jest pełnym PNG (urwany, bez sygnatury, bez bloku IHDR), daje None — strona bez wymiarów."""
    from app.web import help as help_module
    signature, ihdr = b"\x89PNG\r\n\x1a\n", b"\x00\x00\x00\x0dIHDR"
    files = {
        "ok.png": (SCREENSHOTS_DIR / "02-pulpit.png").read_bytes(),
        "urwany.png": signature + ihdr,                         # przed wymiarami
        "bez-sygnatury.png": b"\x00" * 8 + ihdr + b"\x00" * 8,  # blok IHDR, ale to nie PNG
        "bez-ihdr.png": signature + b"\x00" * 16,               # sygnatura PNG, ale inny pierwszy blok
        "tekst.png": b"to nie jest obraz, tylko tekst dluzszy niz dwadziescia cztery bajty",
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    monkeypatch.setattr(help_module, "SCREENSHOTS_DIR", tmp_path)
    help_module.screenshot_size.cache_clear()  # wyniki są pamiętane po nazwie pliku
    try:
        assert help_module.screenshot_size("ok.png") == _png_size("02-pulpit.png")
        for name in set(files) - {"ok.png"}:
            assert help_module.screenshot_size(name) is None, name
    finally:
        help_module.screenshot_size.cache_clear()


def test_shot_macro_without_file_renders_without_dimensions(app):
    """Brakujący plik zrzutu nie wywraca strony: obrazek bez width/height, reszta figury jak zwykle."""
    with app.test_request_context():
        html = app.jinja_env.from_string(
            '{% from "help/_shot.html" import shot %}{{ shot("nie-ma.png", "Podpis.", "Opis obrazka") }}').render()
    assert 'alt="Opis obrazka"' in html and "width=" not in html and "height=" not in html
    assert "<figcaption" in html and "Podpis." in html


def test_topics_without_screenshots(client):
    assert set(HELP_SHOTS) | NO_SHOTS == {t["slug"] for t in TOPICS}  # nowy temat — zdecyduj o zrzutach
    for path in ["/pomoc"] + [f"/pomoc/{slug}" for slug in sorted(NO_SHOTS)]:
        assert "help-shot" not in client.get(path).get_data(as_text=True), path


def test_help_screenshots_are_served(client):
    """Każdy obrazek w Pomocy zwraca PNG (200) — pliki leżą w app/static/, więc trafiają też do obrazu Docker."""
    import lxml.html
    sources = set()
    for path in ALL_PAGES:
        r = client.get(path)
        assert "img-src 'self'" in r.headers["Content-Security-Policy"]  # CSP przepuszcza obrazy z /static
        sources.update(lxml.html.fromstring(r.get_data(as_text=True)).xpath("//img/@src"))
    assert {s.rsplit("/", 1)[-1] for s in sources} == {name for files in HELP_SHOTS.values() for name in files}
    for src in sorted(sources):
        with client.get(src) as r:
            assert r.status_code == 200 and r.mimetype == "image/png", src
            assert r.data.startswith(b"\x89PNG\r\n\x1a\n"), src


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
    tree = read_document(b"<Faktura><Sprzedawca><Ulica>Polna 1</Ulica><Miasto>Opole</Miasto></Sprzedawca></Faktura>"
)
    step = json.loads(h["step"])
    assert apply_chain(h["input"], [step], TransformContext(tree)) == h["output"]


# --- limity i przykłady ---

def test_limits_follow_configuration(app, client):
    app.config.update(MAX_DOCUMENT_BYTES=3 * 1024 * 1024, MAX_LINES=1234, MAX_TREE_NODES=54321)
    for path in ("/pomoc", "/pomoc/api", "/pomoc/faq"):
        html = client.get(path).get_data(as_text=True)
        assert "3 MiB" in html and "1 234" in html and "54 321" in html, path
        assert "10 MiB" not in html and "200 000" not in html and "5 000 pozycji" not in html


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


# --- integracja z własną aplikacją ---

INTEGRATION = "/pomoc/integracja"
EXAMPLES_DIR = ROOT / "app" / "help_examples"


def _code_blocks(html: str) -> dict[str, list[str]]:
    import lxml.html
    out: dict[str, list[str]] = {}
    for code in lxml.html.fromstring(html).xpath("//pre/code"):
        m = re.search(r"language-([\w-]+)", code.get("class") or "")
        if m:
            out.setdefault(m.group(1), []).append(code.text_content())
    return out


def test_integration_topic_after_api_and_linked(client):
    slugs = [t["slug"] for t in TOPICS]
    assert slugs.index("integracja") == slugs.index("api") + 1
    assert 'href="/pomoc/integracja"' in client.get("/pomoc").get_data(as_text=True)  # karta w spisie
    assert 'href="/pomoc/integracja"' in client.get("/pomoc/api").get_data(as_text=True)
    faq = client.get("/pomoc/faq").get_data(as_text=True)
    assert "Jak podłączyć swoją aplikację?" in faq and 'href="/pomoc/integracja"' in faq
    assert "Jak dowiedzieć się, że operator zatwierdził fakturę wysłaną przez API?" in faq
    assert "powtórzenia odrzucaj po id i updated_at" in faq  # nie po samym id — to gubiłoby późniejsze zmiany


def _text(html: str) -> str:
    """Tekst strony z ujednoliconymi odstępami (zdania w szablonach są łamane między wierszami)."""
    import lxml.html
    return " ".join(lxml.html.fromstring(html).text_content().split())


@pytest.mark.parametrize("path", ["/pomoc/integracja", "/pomoc/api"])
def test_help_describes_sync_mode_and_time_format(client, path):
    """Pomoc opisuje tryb synchronizacji listy (v0.5.0) i czas z „Z”, bez ostrzeżeń sprzed v0.5.0."""
    text = _text(client.get(path).get_data(as_text=True))
    for term in ("updated_since", "cursor", "next_cursor", "updated_at", "1970-01-01T00:00:00Z", "%2B",
                 "2026-10-11T06:04:38.312308Z"):
        assert term in text, term
    assert "jest pomijane" not in text  # dawniej: przesunięcie strefy w since „jest pomijane”
    assert "UTC bez strefy" not in text and "Nie ma stronicowania" not in text


def test_integration_recommends_sync_with_margin_and_keeps_history_note(client):
    text = _text(client.get(INTEGRATION).get_data(as_text=True))
    assert "Sposób B (zalecany do synchronizacji): updated_since + cursor" in text
    assert "last_sync − 5 min" in text and "co najmniej raz" in text
    assert "Odrzucaj powtórzenia po id i updated_at" in text and "Samo id nie wystarczy" in text
    assert "Przed v0.5.0 lista filtrowała tylko po czasie przyjęcia (since)" in text
    assert "planowane w kolejnej wersji" in text


def test_integration_examples_sync_in_four_languages(client):
    """Każdy przykład ma synchronizację przyrostową z marginesem; PHP i Node wypisują id oryginału duplikatu."""
    blocks = _code_blocks(client.get(INTEGRATION).get_data(as_text=True))
    code = {"python": blocks["python"][0], "php": blocks["php"][0], "javascript": blocks["javascript"][0],
            "bash": blocks["bash"][-1]}
    sync = {"python": "def sync_approved(state_path", "php": "function sync_approved(string $statePath",
            "javascript": "async function syncApproved(statePath", "bash": "sync_approved() {"}
    margin = {"python": "timedelta(minutes=5)", "php": "'-5 minutes'", "javascript": "5 * 60 * 1000",
              "bash": "SYNC_MARGIN=300"}
    # brak pola next_cursor (a nie null) przerywa przebieg; import tylko dokumentu, który nadal jest approved
    no_cursor = {"python": '"next_cursor" not in page', "php": "array_key_exists('next_cursor', $page)",
                 "javascript": 'Object.hasOwn(page, "next_cursor")', "bash": "jq -e 'has(\"next_cursor\")'"}
    approved = {"python": 'if doc["status"] == "approved":', "php": "if ($doc['status'] === 'approved')",
                "javascript": 'if (doc.status === "approved")', "bash": '[[ "$status" != approved ]] ||'}
    for lang, text in code.items():
        for term in (sync[lang], margin[lang], "--sync", "updated_since", "next_cursor", "1970-01-01T00:00:00Z",
                     no_cursor[lang], "Błąd protokołu", approved[lang]):
            assert term in text, (lang, term)
    assert "original_id($doc)" in code["php"] and "originalId(doc)" in code["javascript"]
    # wspólny format pliku stanu: puste „seen” jako {} (bez flagi PHP zapisałby [], nieczytelne dla Pythona i jq)
    assert "JSON_FORCE_OBJECT" in code["php"]


def test_help_empty_parameter_rule_matches_api(seeded, client):
    """Pusty status= i since= to brak parametru, ale pusty limit=, updated_since= i cursor= daje 400 — tak mówi
    Pomoc i OpenAPI, i tak działa API (routes.list_documents)."""
    import yaml
    key = {"X-API-Key": "xp_test_demo_key"}
    r = client.get("/api/v1/documents?status=&since=", headers=key)
    assert r.status_code == 200 and set(r.get_json()) == {"items"}  # tryb zwykły
    for empty in ("limit=", "updated_since=", "cursor="):
        r = client.get(f"/api/v1/documents?{empty}", headers=key)
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request", empty
    rules = {"/pomoc/api": "pusty status= albo since= oznacza brak parametru, ale pusty limit=, updated_since= "
                           "albo cursor= daje 400",
             INTEGRATION: "pusty updated_since= albo cursor= (bez wartości) daje 400 bad_request"}
    for path, rule in rules.items():
        text = _text(client.get(path).get_data(as_text=True))
        assert rule in text.lower(), path
        assert "Pusty parametr (np." not in text, path  # dawne ogólne zdanie — fałszywe dla limit
        assert "jak brak parametru" not in text, path  # dawne „pusty updated_since= jest traktowany jak brak…”
    spec = yaml.safe_load((ROOT / "app" / "static" / "openapi.yaml").read_text(encoding="utf-8"))
    listing = spec["paths"]["/documents"]["get"]

    def flat(text: str) -> str:  # opisy w YAML są łamane między wierszami
        return " ".join(text.split())

    assert "pusty `limit=`, `updated_since=` albo `cursor=` daje 400" in flat(listing["description"])
    params = {p["name"]: flat(p["description"]) for p in listing["parameters"]}
    assert "(`updated_since=`) daje 400" in params["updated_since"] and "(`cursor=`) daje 400" in params["cursor"]


def test_openapi_matches_documents_api(seeded, client):
    """openapi.yaml wymienia dokładnie pola i parametry, które ma prawdziwe API listy i dokumentu."""
    import io

    import yaml

    from tests.conftest import sample_bytes
    spec = yaml.safe_load((ROOT / "app" / "static" / "openapi.yaml").read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    key = {"X-API-Key": "xp_test_demo_key"}
    created = client.post("/api/v1/documents", headers=key,
                          data={"file": (io.BytesIO(sample_bytes("alfa-1.xml")), "alfa-1.xml")}).get_json()
    synced = client.get("/api/v1/documents", headers=key,
                        query_string={"updated_since": "1970-01-01T00:00:00Z"}).get_json()
    summary = set(schemas["DocumentSummary"]["properties"])
    assert summary == set(synced["items"][0])
    assert summary | set(schemas["Document"]["allOf"][1]["properties"]) == set(created)
    assert set(schemas["DocumentList"]["properties"]) == set(synced) == {"items", "next_cursor"}
    listing = spec["paths"]["/documents"]["get"]
    assert {p["name"] for p in listing["parameters"]} == {"status", "since", "updated_since", "cursor", "limit"}
    assert "400" in listing["responses"]


def test_integration_examples_four_languages_with_request_host(client):
    html = client.get(INTEGRATION, base_url="http://faktury.example.test:18555").get_data(as_text=True)
    blocks = _code_blocks(html)
    for lang in ("python", "php", "javascript", "bash"):
        assert lang in blocks, lang
    base = "http://faktury.example.test:18555/api/v1"
    for lang, code in [("python", blocks["python"][0]), ("php", blocks["php"][0]),
                       ("javascript", blocks["javascript"][0]), ("bash", blocks["bash"][-1])]:
        assert base in code and "XP_API_KEY" in code, lang
    assert "def send_invoice(path)" in blocks["python"][0] and "def wait_for_result(doc_id" in blocks["python"][0]
    assert "CURLFile" in blocks["php"][0]
    assert "FormData" in blocks["javascript"][0] and "Blob" in blocks["javascript"][0]
    assert "jq" in blocks["bash"][-1]
    assert "__API_BASE__" not in html and "localhost" not in html
    assert "Webhooków nie ma" in html


def test_integration_limits_follow_configuration(app, client):
    from app.api.routes import LIST_DEFAULT_LIMIT, LIST_MAX_LIMIT
    app.config.update(MAX_DOCUMENT_BYTES=3 * 1024 * 1024, MAX_LINES=1234)
    html = client.get(INTEGRATION).get_data(as_text=True)
    assert "3 MiB" in html and "1 234" in html and "10 MiB" not in html
    assert f"domyślnie {LIST_DEFAULT_LIMIT}, maks. {LIST_MAX_LIMIT}" in html


def _key_tree(value):
    """Struktura kluczy JSON-a (listy porównywane po pierwszym elemencie)."""
    if isinstance(value, dict):
        return {k: _key_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_key_tree(value[0])] if value else []
    return None


def test_integration_sample_response_matches_real_api(seeded, client):
    """Przykładowy JSON w Pomocy ma dokładnie te klucze, które zwraca API dla zatwierdzonego alfa-2.xml."""
    import io

    from app.services.pipeline import ingest
    from tests.conftest import sample_bytes
    from tests.test_learning import resolve_with_top_suggestions
    resolve_with_top_suggestions(ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml", source="demo"))
    r = client.post("/api/v1/documents", headers={"X-API-Key": "xp_test_demo_key"},
                    data={"file": (io.BytesIO(sample_bytes("alfa-2.xml")), "alfa-2.xml")})
    assert r.status_code == 201
    real = r.get_json()
    assert real["status"] == "approved"

    sample = json.loads((EXAMPLES_DIR / "odpowiedz-zatwierdzona.json").read_text(encoding="utf-8"))
    assert _key_tree(sample) == _key_tree(real)
    # treść (poza czasem przyjęcia, id i skróconą listą pozycji) to rzeczywisty wynik
    for k in ("status", "number", "issue_date", "format", "filename", "issues_count", "issues"):
        assert sample[k] == real[k], k
    assert sample["invoice"]["lines"][0] == real["invoice"]["lines"][0]
    assert sample["invoice"]["totals"] == real["invoice"]["totals"]

    html = client.get(INTEGRATION).get_data(as_text=True)
    assert json.loads(_code_blocks(html)["json"][0]) == sample


def test_integration_examples_are_valid_code(tmp_path):
    import shutil
    import subprocess
    py = (EXAMPLES_DIR / "integracja.py").read_text(encoding="utf-8")
    compile(py, "integracja.py", "exec")
    checks = {"bash": ["bash", "-n"], "node": ["node", "--check"], "php": ["php", "-l"]}
    files = {"bash": "integracja.sh", "node": "integracja.mjs", "php": "integracja.php"}
    for tool, cmd in checks.items():
        if shutil.which(cmd[0]) is None:
            continue  # narzędzie niedostępne w tym środowisku — sprawdzane tam, gdzie jest
        res = subprocess.run([*cmd, str(EXAMPLES_DIR / files[tool])], capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"{tool}: {res.stdout}{res.stderr}"


# --- FAQ ---

FAQ_TEMPLATES = ROOT / "app" / "templates" / "help" / "faq"


def test_faq_entries_well_formed():
    """Każde pytanie ma treść; `slug` (kotwica do linkowania z Pomocy i Wiki) jest unikalny i w kebab-case,
    a `template` wskazuje istniejący partial w help/faq/ (odpowiedź rozbudowana: kroki, zrzut, pułapki)."""
    slugs = [f["slug"] for f in FAQ if f.get("slug")]
    assert slugs and len(slugs) == len(set(slugs))
    for f in FAQ:
        assert f["q"].strip().endswith("?") and f["a"].strip(), f["q"]
        if f.get("slug"):
            assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", f["slug"]), f["slug"]
        if f.get("template"):
            assert (FAQ_TEMPLATES / f["template"]).is_file(), f["template"]
        if f.get("link"):
            assert f["link"] in {t["slug"] for t in TOPICS}, f["link"]


def test_faq_accordion_anchors_and_partials(client):
    """Pytanie ze slugiem ma nagłówek o id = slug (link /pomoc/faq#slug), pozostałe — id numerowane (pomijane
    w eksporcie); partial jest renderowany w treści odpowiedzi, poniżej krótkiej odpowiedzi."""
    import lxml.html
    html = client.get("/pomoc/faq").get_data(as_text=True)
    doc = lxml.html.fromstring(html)
    for f in FAQ:
        (h,) = doc.xpath('//h2[contains(@class, "accordion-header")][.//button[normalize-space()=$q]]', q=f["q"])
        if f.get("slug"):
            assert h.get("id") == f["slug"]
        else:
            assert h.get("id").startswith("faq-h")
    worek = next(f for f in FAQ if f.get("slug") == "worek-na-kg")
    (body,) = doc.xpath('//h2[@id="worek-na-kg"]/following-sibling::div//div[contains(@class, "accordion-body")]')
    text = " ".join(body.text_content().split())
    assert worek["a"][:40] in text
    assert "1 worek = 25 kg" in text and "Na co uważać" in text
    assert body.xpath('.//figure[contains(@class, "help-shot")]//img[contains(@src, "13-faq-worek.png")]')
    assert "500" in text and "÷ 25" in text  # wynik: 20 worków → 500 kg, cena podzielona przez 25


def test_faq_covers_units_and_conversions(client):
    """Pytania o jednostki i przeliczniki: worek→kg, różne worki per towar, poprawa przelicznika, cena po
    przeliczeniu, tylko na jednostkę bazową, różne zapisy tej samej jednostki."""
    html = client.get("/pomoc/faq").get_data(as_text=True)
    for needle in ("worek", "25 kg", "50 kg", "tylko dla tego towaru", "Przetwórz ponownie", "jednostkę bazową",
                   "cena jednostkowa", "alias"):
        assert needle in html, needle
    assert 'href="/pomoc/jednostki"' in html


def test_units_topic_links_faq_entry(client):
    html = client.get("/pomoc/jednostki").get_data(as_text=True)
    assert 'href="/pomoc/faq#worek-na-kg"' in html


def test_faq_time_and_longer_lists_have_stable_anchors(client):
    faq = client.get("/pomoc/faq").get_data(as_text=True)
    for slug, q in (("czas-w-panelu", "Jaki czas pokazuje panel?"),
                    ("dluzsze-listy", "Lista się urywa — gdzie reszta wpisów?")):
        assert f'id="{slug}"' in faq and q in faq
    assert "DISPLAY_TZ" in faq and "Starsze →" in faq


# --- temat „Zestaw demo” ---

def test_dataset_topic_lists_all_files_and_phases(client):
    from app.services.demo_dataset import load_manifest
    html = client.get("/pomoc/zestaw-demo").get_data(as_text=True)
    m = load_manifest()
    assert len(m.entries) == 24
    for e in m.entries:
        assert e.filename in html, e.filename
    assert "Wczytaj pierwsze (6)" in html and "Wczytaj pozostałe (18)" in html
    assert "GBP" in html and "XP_API_KEY" in html


def test_dataset_topic_renders_api_script_with_request_host(client):
    import html as html_lib
    html = html_lib.unescape(
        client.get("/pomoc/zestaw-demo", base_url="http://faktury.example:8123").get_data(as_text=True))
    assert 'BASE="http://faktury.example:8123/api/v1"' in html
    assert "__API_BASE__" not in html


def test_dataset_topic_without_dataset_dir_is_not_500(client, monkeypatch, tmp_path):
    from app.services import demo_dataset
    monkeypatch.setattr(demo_dataset, "DATASET_DIR", tmp_path)
    r = client.get("/pomoc/zestaw-demo")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "nie jest dostępny" in html and "Wczytaj pierwsze (6)" in html


def test_dataset_faq_has_slug_and_links_to_topic(client):
    entry = next(f for f in FAQ if f.get("slug") == "zestaw-demo-api")
    assert entry["link"] == "zestaw-demo"
    assert 'id="zestaw-demo-api"' in client.get("/pomoc/faq").get_data(as_text=True)


def test_dataset_topic_step_two_prose_matches_manifest(client):
    from app.services.demo_dataset import load_manifest
    m = load_manifest()
    html = client.get("/pomoc/zestaw-demo").get_data(as_text=True)
    rest = [e for e in m.by_phase("pozostale")]
    review = [e for e in rest if e.on_ingest.status == "needs_review"]
    dups = [e for e in rest if e.on_ingest.status == "duplicate"]
    assert [e.order for e in review] == [15, 16, 17, 18] and len(dups) == 1
    step2 = html.index("Wczytaj pozostałe (18)”.")
    table = html.index("Wszystkie 24 faktury")
    for e in review + dups:
        assert e.filename in html[step2:table], e.filename
    gbp = html.index("wybierz GBP")
    assert html.index("Wczytaj pierwsze (6)”.") < step2 < gbp
    assert gbp < html.index("Wczytaj wszystko”</strong>")
