"""Uruchamia scenariusz uczenia na realnych fakturach z private/samples/ (katalog ignorowany przez git).

W CI i na czystym klonie katalogu nie ma — testy są pomijane.
"""
from pathlib import Path

import pytest

from app.services.pipeline import ingest
from tests.test_learning import resolve_with_top_suggestions

PRIVATE = Path(__file__).resolve().parent.parent / "private" / "samples"
FILES = sorted(p for p in PRIVATE.glob("*") if p.is_file()) if PRIVATE.exists() else []


@pytest.mark.skipif(not FILES, reason="brak prywatnych próbek (private/samples/)")
@pytest.mark.parametrize("path", FILES, ids=[f"private-{i}" for i in range(len(FILES))])
def test_private_sample_learning(seeded, path):
    data = path.read_bytes()
    first = ingest(data, path.name)
    assert first.status == "needs_review"
    resolve_with_top_suggestions(first)
    assert first.status == "approved", first.issues
    again = ingest(data + b"\n", path.name)
    # dostawca rozpoznany po NIP z szablonu → wykryty duplikat (ten sam numer), bez innych problemów
    assert again.supplier_id == first.supplier_id
    assert again.status == "duplicate"
    assert [i["code"] for i in again.issues if i["severity"] == "blocking"] == ["duplicate"]
