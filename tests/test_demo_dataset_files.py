"""Zestaw demo „Miesiąc faktur” (demo/dataset/): 24 fikcyjne faktury sześciu dostawców, manifest z oczekiwanymi
statusami i deterministyczny generator tools/gen_demo_dataset.py. Test prawdy manifestu wczytuje pliki do świeżej
bazy w kolejności `order` i porównuje statusy oraz zbiory kodów problemów z `expected` w manifeście."""
import csv
import hashlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest
from lxml import etree

from app.help_content import ISSUE_HELP
from app.ingest import read_document
from app.services.pipeline import ingest
from tests.test_learning import resolve_with_top_suggestions
from tests.test_no_private_data import find_violations, load_forbidden_tokens

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "demo" / "dataset"
SAMPLES = ROOT / "demo" / "samples"
TOOL = ROOT / "tools" / "gen_demo_dataset.py"
SUPPLIERS = {"alfa", "beta", "gamma", "epsilon", "zeta", "eta"}
EXTRA_FILES = {"manifest.json", "README.md"}


def _tool():
    """Moduł generatora (tools/ nie jest pakietem); rejestrowany w sys.modules — wymagają tego dataclasses."""
    if "gen_demo_dataset" not in sys.modules:
        spec = importlib.util.spec_from_file_location("gen_demo_dataset", TOOL)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["gen_demo_dataset"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["gen_demo_dataset"]


@pytest.fixture(scope="module")
def manifest():
    return json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_lists_exactly_the_files_in_directory(manifest):
    listed = [f["filename"] for f in manifest["files"]]
    assert len(listed) == 24 and len(set(listed)) == 24
    on_disk = {p.name for p in DATASET.iterdir() if p.is_file()} - EXTRA_FILES
    assert set(listed) == on_disk
    assert listed == sorted(listed), "kolejność plików w katalogu = kolejność w manifeście"


def test_manifest_entries_well_formed(manifest):
    assert list(manifest) == ["version", "title", "generator", "suppliers", "files"]
    assert manifest["version"] == 1 and manifest["title"] == "Miesiąc faktur"
    assert manifest["generator"] == {"tool": "tools/gen_demo_dataset.py", "seed": 20261001}
    assert set(manifest["suppliers"]) == SUPPLIERS
    for s in manifest["suppliers"].values():
        assert set(s) == {"name", "tax_id", "format"} and s["format"] in {"xml", "json", "csv"}
    keys = ["order", "filename", "sha256", "supplier", "format", "phase", "shows", "expected", "duplicate_of"]
    by_name = {}
    for n, f in enumerate(manifest["files"], start=1):
        assert list(f) == keys
        assert f["order"] == n
        assert f["filename"].startswith(f"{n:02d}-{f['supplier']}-")
        assert f["supplier"] in SUPPLIERS
        assert f["format"] == f["filename"].rsplit(".", 1)[1] == manifest["suppliers"][f["supplier"]]["format"]
        assert f["phase"] in {"first", "rest"} and f["shows"].strip()
        exp = f["expected"]
        assert list(exp) == ["on_ingest", "after_resolve"]
        for stage in ("on_ingest", "after_resolve"):
            e = exp[stage]
            if e is None:
                assert stage == "after_resolve"
                continue
            assert list(e) == ["status", "blocking", "warnings"]
            assert e["status"] in {"approved", "needs_review", "duplicate"}
            for codes in (e["blocking"], e["warnings"]):
                assert codes == sorted(set(codes))
                assert set(codes) <= set(ISSUE_HELP), codes
        # czyste i duplikat: after_resolve = null; do rozwiązania: after_resolve podane
        assert (exp["after_resolve"] is None) == (exp["on_ingest"]["status"] != "needs_review")
        if f["duplicate_of"] is not None:
            orig = by_name[f["duplicate_of"]]
            assert orig["sha256"] == f["sha256"] and orig["order"] < f["order"]
            assert exp["on_ingest"]["status"] == "duplicate"
        by_name[f["filename"]] = f
    first = [f for f in manifest["files"] if f["phase"] == "first"]
    assert sorted(f["supplier"] for f in first) == sorted(SUPPLIERS)
    for f in first:  # „first” = pierwsza faktura dostawcy w zestawie
        earlier = [g for g in manifest["files"] if g["supplier"] == f["supplier"] and g["order"] < f["order"]]
        assert not earlier
    assert [f["filename"] for f in manifest["files"] if f["duplicate_of"]] == ["20-beta-3-ponownie.xml"]
    assert by_name["20-beta-3-ponownie.xml"]["duplicate_of"] == "14-beta-3.xml"


def test_sha256_in_manifest_matches_files(manifest):
    for f in manifest["files"]:
        assert hashlib.sha256((DATASET / f["filename"]).read_bytes()).hexdigest() == f["sha256"], f["filename"]
    assert (DATASET / "20-beta-3-ponownie.xml").read_bytes() == (DATASET / "14-beta-3.xml").read_bytes()


def test_generator_is_deterministic(tmp_path):
    tool = _tool()
    tool.generate(tmp_path / "a")
    tool.generate(tmp_path / "b")
    names = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert names == sorted(p.name for p in (tmp_path / "b").iterdir())
    for name in names:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    # pliki w repozytorium = wynik generatora (bajt w bajt), --check to potwierdza
    assert names == sorted(p.name for p in DATASET.iterdir() if p.is_file())
    for name in names:
        assert (tmp_path / "a" / name).read_bytes() == (DATASET / name).read_bytes(), name
    assert tool.main(["--check"]) == 0
    assert tool.load(DATASET) == json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))


def test_generator_check_detects_drift(tmp_path):
    tool = _tool()
    assert tool.main(["--out", str(tmp_path)]) == 0
    assert tool.main(["--out", str(tmp_path), "--check"]) == 0
    (tmp_path / "01-alfa-1.xml").write_bytes(b"zmieniony")
    assert tool.main(["--out", str(tmp_path), "--check"]) != 0
    tool.main(["--out", str(tmp_path)])
    (tmp_path / "nadmiarowy.csv").write_text("x", encoding="utf-8")
    assert tool.main(["--out", str(tmp_path), "--check"]) != 0


def test_gtin_check_digit():
    tool = _tool()
    for gtin in ("5909999000013", "5909999000068", "4009999000028", "5909999000129"):
        assert tool.gtin_check_digit(gtin[:-1]) == gtin[-1]


def _sample_numbers() -> set[str]:
    """Numery faktur z demo/samples (te same tagi/kolumny co w zestawie)."""
    nums = set()
    for p in SAMPLES.iterdir():
        text = p.read_text(encoding="utf-8")
        nums |= set(re.findall(r"<(?:FakturaNumer|P_2|cbc:ID)>([^<]+)<", text))
        if p.suffix == ".json":
            nums.add(json.loads(text)["invoice"]["number"])
        if p.suffix == ".csv":
            nums |= {r["NrFaktury"] for r in csv.DictReader(io.StringIO(text), delimiter=";")}
    return nums


def _invoice_number(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)["invoice"]["number"]
    if path.suffix == ".csv":
        return next(csv.DictReader(io.StringIO(text), delimiter=";"))["NrFaktury"]
    m = re.search(r"<(?:FakturaNumer|P_2|cbc:ID|InvoiceNumber)>([^<]+)<", text)
    return m.group(1)


def test_dataset_does_not_collide_with_samples(manifest):
    samples = {p.name: p.read_bytes() for p in SAMPLES.iterdir()}
    sample_shas = {hashlib.sha256(b).hexdigest() for b in samples.values()}
    assert not sample_shas & {f["sha256"] for f in manifest["files"]}
    numbers = [_invoice_number(DATASET / f["filename"]) for f in manifest["files"] if not f["duplicate_of"]]
    assert len(numbers) == len(set(numbers)) == 23
    assert not set(numbers) & _sample_numbers()
    # tożsamość dostawców z próbek (nazwa + NIP) — szablon nauczony na próbce działa na zestawie i odwrotnie
    sample_text = "\n".join(b.decode("utf-8") for b in samples.values())
    for key, s in manifest["suppliers"].items():
        if key != "eta":
            assert s["name"] in sample_text and s["tax_id"] in sample_text, key


def test_files_parse(manifest):
    for f in manifest["files"]:
        data = (DATASET / f["filename"]).read_bytes()
        if f["format"] == "xml":
            etree.fromstring(data)
        elif f["format"] == "json":
            json.loads(data.decode("utf-8"))
        else:
            rows = list(csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter=";"))
            assert rows
        tree = read_document(data, f["filename"])
        assert tree.fmt == f["format"]


def _gtin_ok(code: str) -> bool:
    digits = [int(c) for c in code]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits[:-1])))
    return (10 - total % 10) % 10 == digits[-1]


def test_fictional_identifiers_only(manifest):
    forbidden = load_forbidden_tokens()
    files = [DATASET / f["filename"] for f in manifest["files"]] + [DATASET / n for n in EXTRA_FILES]
    for path in files:
        text = re.sub(r"[0-9a-f]{64}", "", path.read_text(encoding="utf-8"))  # bez skrótów sha256 z manifestu
        # NIP-y: tylko fikcyjna pula 99900000xx (PL) — każdy samodzielny 10-cyfrowy numer
        for nip in re.findall(r"(?<!\d)\d{10}(?!\d)", text):
            assert nip.startswith("99900000"), (path.name, nip)
        # GTIN-y: prefiksy demonstracyjne 590999… / 400999… i poprawna cyfra kontrolna
        for gtin in re.findall(r"(?<!\d)\d{13}(?!\d)", text):
            assert gtin.startswith(("590999", "400999")) and _gtin_ok(gtin), (path.name, gtin)
        # strażnik danych prywatnych (tests/test_no_private_data.py) — także dla plików jeszcze nieśledzonych
        if forbidden:
            assert not find_violations(text, forbidden), path.name
    for s in manifest["suppliers"].values():
        assert re.fullmatch(r"(PL)?99900000\d\d|GB999000044|DE999999999", s["tax_id"]), s
    assert manifest["suppliers"]["eta"] == {"name": "Eta Packaging Sp. z o.o.", "tax_id": "9990000077",
                                            "format": "xml"}


def _codes(doc) -> dict:
    issues = doc.issues or []
    return {"status": doc.status,
            "blocking": sorted({i["code"] for i in issues if i["severity"] == "blocking"}),
            "warnings": sorted({i["code"] for i in issues if i["severity"] == "warning"})}


def test_expected_statuses_on_fresh_db(seeded, manifest):
    """Test prawdy manifestu: świeża baza z kartoteką demo, pliki w kolejności `order`; faktury z problemami
    rozwiązywane pierwszymi podpowiedziami („zapamiętaj”) — statusy i zbiory kodów równe `expected`."""
    docs = {}
    for f in manifest["files"]:
        doc = ingest((DATASET / f["filename"]).read_bytes(), f["filename"], source="demo")
        docs[f["filename"]] = doc
        exp = f["expected"]
        assert _codes(doc) == exp["on_ingest"], (f["filename"], doc.issues)
        if f["duplicate_of"]:
            orig = docs[f["duplicate_of"]]
            dup = next(i for i in doc.issues if i["code"] == "duplicate")
            assert dup["source_value"] == str(orig.id)
        if exp["after_resolve"] is not None:
            resolve_with_top_suggestions(doc)
            assert _codes(doc) == exp["after_resolve"], (f["filename"], doc.issues)
