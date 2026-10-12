"""`flask check-storage`: po przeniesieniu danych (import bazy + rozpakowanie storage.tar.gz) sprawdza, czy każdy
dokument ma plik raw/<sha256> w magazynie — brakujące pliki to kod wyjścia 1 i lista id."""
from app.services.pipeline import ingest
from app.services.storage import get_storage
from tests.conftest import sample_bytes


def test_check_storage_reports_missing_files(seeded, app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["check-storage"])
    assert r.exit_code == 0, r.output
    assert "dokumentów: 0" in r.output and "brakujących plików: 0" in r.output

    ok = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    gone = ingest(sample_bytes("gamma-ubl.xml"), "g.xml")
    get_storage().delete(gone.sha256)
    r = runner.invoke(args=["check-storage"])
    assert r.exit_code == 1
    assert "dokumentów: 2" in r.output and "brakujących plików: 1" in r.output
    assert f"#{gone.id}" in r.output and f"#{ok.id}" not in r.output
    assert gone.sha256[:12] in r.output
