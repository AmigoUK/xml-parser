"""E2E zestawu demo „Miesiąc faktur”: fazy wczytywania przez serwis `demo_dataset` i prawdziwy silnik na świeżej bazie
(fixture `seeded`). Sprawdza kody problemów przy wczytaniu, wyniki pierwszych podpowiedzi (pinowane), brak nauki przy
„wszystko naraz”, powtarzalność po `reset_demo()` oraz zgodność wierszy postępu z manifestem."""
import pytest

import tests.test_learning as learning
from app.models import Document, Product
from app.services import demo_dataset as dd
from app.services.seed import reset_demo
from tests.test_learning import resolve_with_top_suggestions


@pytest.fixture
def resolves(monkeypatch):
    """Rejestr wywołań `resolve` z pomocnika uczenia: lista (plik, akcja, dane)."""
    calls = []
    original = learning.resolve

    def recording(doc, action, data, *args, **kwargs):
        calls.append((doc.filename, action, dict(data)))
        return original(doc, action, data, *args, **kwargs)

    monkeypatch.setattr(learning, "resolve", recording)
    return calls


def _codes(doc, severity=None):
    return sorted({i["code"] for i in doc.issues if severity is None or i["severity"] == severity})


def _flow(check=None):
    """Przebieg jak w panelu: faza pierwsza (6 faktur, każda rozwiązana pierwszymi podpowiedziami), potem „pozostałe”
    JEDNĄ partią (`load_phase("pozostale")`, jak przycisk „Wczytaj pozostałe” i skrypt curl), a dopiero po niej
    rozwiązanie faktur z pułapkami. `check(entry, doc)` wywoływane po wczytaniu, przed rozwiązaniem. Zwraca dokumenty
    w kolejności manifestu."""
    manifest = dd.load_manifest()
    by_name = {e.filename: e for e in manifest.entries}
    docs = {}

    def handle(doc):
        entry = by_name[doc.filename]
        if check:
            check(entry, doc)
        if entry.after_resolve is not None:
            resolve_with_top_suggestions(doc)
            assert doc.status == entry.after_resolve.status, doc.filename
        docs[doc.filename] = doc

    for doc in dd.load_phase("pierwsze").loaded:
        handle(doc)
    rest = dd.load_phase("pozostale")
    assert not rest.skipped and len(rest.loaded) == 18
    for doc in rest.loaded:
        handle(doc)
    return [docs[e.filename] for e in manifest.entries]


def _sequence(docs):
    return [(d.filename, d.status, tuple(_codes(d))) for d in docs]


def _calls(resolves, filename, action):
    return [data for f, a, data in resolves if f == filename and a == action]


def test_first_phase_all_needs_review_with_expected_codes(seeded):
    manifest = dd.load_manifest()
    result = dd.load_phase("pierwsze")
    assert not result.skipped and len(result.loaded) == 6
    by_name = {e.filename: e for e in manifest.entries}
    for doc in result.loaded:
        exp = by_name[doc.filename].on_ingest
        assert doc.status == "needs_review"
        assert tuple(_codes(doc, "blocking")) == exp.blocking
        assert "unknown_supplier" in _codes(doc)


def test_resolve_first_then_rest_follow_manifest(seeded, resolves):
    def check(entry, doc):
        assert doc.status == entry.on_ingest.status, doc.filename
        assert tuple(_codes(doc, "blocking")) == entry.on_ingest.blocking, doc.filename
        assert tuple(_codes(doc, "warning")) == entry.on_ingest.warnings, doc.filename

    docs = {d.filename: d for d in _flow(check)}
    assert len(docs) == 24
    assert all(d.status in ("approved", "duplicate") for d in docs.values())

    # towary dopasowane z kartoteki pierwszą podpowiedzią (indeksy pozycji sprawdzone na plikach)
    for name, line_no, code in [("01-alfa-1.xml", 3, "TOW-0003"), ("02-beta-1.xml", 2, "TOW-0005"),
                                ("03-eta-1.xml", 2, "TOW-0007"), ("04-gamma-1.xml", 1, "TOW-0010")]:
        assert {"line_no": line_no, "product_code": code} in _calls(resolves, name, "map_product"), name

    # nowe towary: 06 (2), 15 (1), 18 (1)
    created = {n: _calls(resolves, n, "create_product") for n in ("06-zeta-1.csv", "15-eta-3.xml", "18-zeta-3.csv")}
    assert [len(v) for v in created.values()] == [2, 1, 1]
    for calls in created.values():
        for c in calls:
            assert Product.query.filter_by(code=c["code"]).count() == 1

    # przeliczniki dostawców
    for name in ("02-beta-1.xml", "06-zeta-1.csv"):
        assert {"from_unit": "worek", "to_unit": "kg", "factor": "25", "scope": "supplier"} in \
            _calls(resolves, name, "add_conversion")
    assert {"from_unit": "karton", "to_unit": "szt", "factor": "20", "scope": "supplier"} in \
        _calls(resolves, "18-zeta-3.csv", "add_conversion")
    assert {"alias": "kart.", "unit": "karton"} in _calls(resolves, "18-zeta-3.csv", "map_unit")

    # 13: ostrzeżenie o niezgodności pozycji, bez blokady
    assert docs["13-alfa-3.xml"].status == "approved" and _codes(docs["13-alfa-3.xml"]) == ["sum_mismatch_line"]
    # 16: nowy alias PCE dostawcy Gamma
    assert _calls(resolves, "16-gamma-3.xml", "map_unit") == [{"alias": "PCE", "unit": "szt"}]
    # 17: pierwsza podpowiedź waluty to PLN (Pomoc uczy wybrać GBP)
    assert _calls(resolves, "17-epsilon-3.json", "map_field") == [{"field": "currency", "value": "PLN"}]
    assert docs["17-epsilon-3.json"].result["currency"] == "PLN"
    # 20: duplikat wskazuje id dokumentu 14
    dup = docs["20-beta-3-ponownie.xml"]
    assert dup.status == "duplicate"
    assert [i["code"] for i in dup.issues] == ["duplicate"]
    assert dup.issues[0]["source_value"] == str(docs["14-beta-3.xml"].id)


def test_all_at_once_without_learning(seeded):
    result = dd.load_phase("wszystko")
    assert len(result.loaded) == 24 and not result.skipped
    for doc in result.loaded:
        if doc.filename == "20-beta-3-ponownie.xml":
            assert doc.status == "duplicate"
        else:
            assert doc.status == "needs_review", doc.filename
            assert "unknown_supplier" in _codes(doc, "blocking"), doc.filename
    assert sum(d.status == "needs_review" for d in result.loaded) == 23


def test_reset_then_identical_run(seeded):
    first = _sequence(_flow())
    assert len(first) == 24
    reset_demo()
    assert Document.query.count() == 0
    assert all(r.doc_id is None for r in dd.progress())
    assert _sequence(_flow()) == first


def test_progress_rows_match_expected_after_full_flow(seeded):
    assert all(r.doc_id is None for r in dd.progress())
    _flow()
    rows = dd.progress()
    assert len(rows) == 24
    for r in rows:
        assert r.matches_expected is True, r.entry.filename
        assert r.source == "demo"
