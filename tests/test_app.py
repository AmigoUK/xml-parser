import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from app.version import __version__

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


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


@pytest.mark.parametrize("value, loads", [
    pytest.param("1", False, id="1-wylacza"),
    pytest.param("true", False, id="true-wylacza"),
    pytest.param("0", True, id="0-nie-wylacza"),
    pytest.param("", True, id="pusta-nie-wylacza"),
])
def test_config_loads_dotenv_unless_disabled(value, loads):
    """app/config.py woła load_dotenv() tylko bez PYTHON_DOTENV_DISABLED (wartości jak w python-dotenv); conftest ją
    ustawia, więc lokalny .env nie zmienia wyniku testów. W podprocesie load_dotenv jest podmienione na licznik
    wywołań — żaden prawdziwy .env nie jest czytany."""
    code = ("import sys, dotenv\n"
            "calls = []\n"
            "dotenv.load_dotenv = lambda *a, **k: calls.append(1) or False\n"
            "import app.config\n"
            "sys.exit(10 + len(calls))\n")
    env = dict(os.environ, PYTHON_DOTENV_DISABLED=value)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == (11 if loads else 10), r.stderr
