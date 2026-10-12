"""Serwis zestawu demo: manifest, postęp (nazwa+sha256, dowolne źródło), wczytywanie faz — manifest syntetyczny."""
import hashlib
import json

import pytest

from app.models import ApiKey
from app.services import demo_dataset as dd
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def _exp(status, blocking=(), warnings=()):
    return {"status": status, "blocking": list(blocking), "warnings": list(warnings)}


@pytest.fixture
def dataset(app, tmp_path, monkeypatch):
    d = tmp_path / "dataset"
    d.mkdir()
    base = sample_bytes("alfa-1.xml")
    files = {
        "01-alfa-1.xml": base,
        "02-alfa-2.xml": base.replace(b"FA/2026/10/001", b"FA/2026/10/002"),
        "03-alfa-1-ponownie.xml": base,  # bajt w bajt jak 01
    }
    entries = []
    for i, (name, data) in enumerate(files.items(), 1):
        (d / name).write_bytes(data)
        dup = i == 3
        entries.append({
            "order": i, "filename": name, "sha256": hashlib.sha256(data).hexdigest(), "supplier": "alfa",
            "format": "xml", "phase": "first" if i == 1 else "rest", "shows": "test",
            "expected": {"on_ingest": _exp("duplicate" if dup else "needs_review",
                                           () if dup else ("unknown_supplier",)),
                         "after_resolve": None if dup else _exp("approved")},
            "duplicate_of": "01-alfa-1.xml" if dup else None})
    manifest = {"version": 1, "title": "Test", "generator": {"tool": "x", "seed": 1},
                "suppliers": {"alfa": {"name": "Alfa", "tax_id": "9990000011", "format": "xml"}},
                "files": entries}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(dd, "DATASET_DIR", d)
    return d


def test_load_manifest_parses_entries_and_phases(dataset):
    m = dd.load_manifest()
    assert m.title == "Test" and [e.order for e in m.entries] == [1, 2, 3]
    assert m.entries[0].on_ingest.blocking == ("unknown_supplier",)
    assert m.entries[2].after_resolve is None and m.entries[2].duplicate_of == "01-alfa-1.xml"
    assert [e.filename for e in m.by_phase("pierwsze")] == ["01-alfa-1.xml"]
    assert len(m.by_phase("pozostale")) == 2 and len(m.by_phase("wszystko")) == 3
    with pytest.raises(AttributeError):
        m.entries[0].order = 5  # frozen


def test_is_available_false_without_manifest(app, tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "DATASET_DIR", tmp_path / "brak")
    assert dd.is_available() is False
    with pytest.raises(FileNotFoundError, match="Brak manifestu"):
        dd.load_manifest()
    (tmp_path / "zly.json").write_text("{nie json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifestu"):
        dd.load_manifest(tmp_path / "zly.json")
    (tmp_path / "pusty.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="struktur"):
        dd.load_manifest(tmp_path / "pusty.json")


def test_progress_matches_by_filename_and_sha_any_source(dataset):
    assert all(r.doc_id is None and r.matches_expected is None for r in dd.progress())
    dd.load_entries(dd.load_manifest().by_phase("pierwsze"))
    key = ApiKey(name="k", prefix="xp_", key_hash="h" * 64)
    from app.extensions import db
    db.session.add(key)
    db.session.commit()
    ingest((dataset / "02-alfa-2.xml").read_bytes(), "02-alfa-2.xml", source="api", api_key_id=key.id)
    rows = dd.progress()
    assert [r.source for r in rows] == ["demo", "api", None]
    assert rows[0].status_label == "Do wyjaśnienia" and rows[1].doc_id is not None
    # ta sama nazwa, inna treść -> nie liczy się jako wczytany wpis
    ingest(b"<a/>", "03-alfa-1-ponownie.xml", source="api")
    assert dd.progress()[2].doc_id is None


def test_progress_distinguishes_duplicate_entry_from_original(dataset):
    dd.load_phase("wszystko")
    rows = dd.progress()
    assert rows[0].doc_id != rows[2].doc_id
    assert rows[0].status == "needs_review" and rows[2].status == "duplicate"
    assert rows[2].matches_expected is True


def test_pending_skips_loaded_entries(dataset):
    assert [e.order for e in dd.pending("wszystko")] == [1, 2, 3]
    dd.load_phase("pierwsze")
    assert [e.order for e in dd.pending("wszystko")] == [2, 3]
    assert dd.counts() == {"pierwsze": (0, 1), "pozostale": (2, 2), "wszystko": (2, 3)}


def test_load_phase_is_idempotent(dataset):
    first = dd.load_phase("wszystko")
    assert len(first.loaded) == 3 and first.skipped == []
    from app.models import Document
    again = dd.load_phase("wszystko")
    assert again.loaded == [] and len(again.skipped) == 3
    assert Document.query.count() == 3


def test_load_phase_unknown_key(dataset):
    with pytest.raises(KeyError):
        dd.load_phase("nieznana")


def test_matches_expected_accepts_on_ingest_or_after_resolve(dataset):
    e = dd.load_manifest().entries[0]
    assert dd._matches(e, "needs_review") is True
    assert dd._matches(e, "approved") is True
    assert dd._matches(e, "rejected") is False
    assert dd._matches(e, None) is None
    dup = dd.load_manifest().entries[2]
    assert dd._matches(dup, "approved") is False
