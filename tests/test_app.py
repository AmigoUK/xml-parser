import tomllib
from pathlib import Path

from app.version import __version__

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_from_pyproject():
    expected = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert __version__ == expected and __version__.count(".") == 2


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok", "version": __version__, "db": "ok"}


def test_healthz_checks_db_ok(client):
    r = client.get("/healthz")
    assert r.get_json()["db"] == "ok"


def test_healthz_503_when_db_down(client, app, monkeypatch):
    from app.extensions import db

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db.session, "execute", boom)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.get_json()["status"] == "error"
    assert "db down" not in r.get_data(as_text=True)
