"""Blokada migracji (app/dblock.py): start wielu replik naraz nie uruchamia `flask db upgrade` równolegle."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.dblock import LOCK_NAME, migration_lock, run_locked
from tests.conftest import mariadb_url, needs_mariadb  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parent.parent


def _env(url=None):
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1", FLASK_SKIP_DOTENV="1")
    env.pop("DATABASE_URL", None)
    if url:
        env["DATABASE_URL"] = url
    return env


def test_sqlite_runs_command_without_lock(tmp_path):
    url = f"sqlite:///{tmp_path / 'x.db'}"
    with migration_lock(url) as held:
        assert held is False
    assert run_locked(url, ["sh", "-c", "exit 7"]) == 7
    assert run_locked(url, ["true"]) == 0


def test_cli_passes_exit_code_and_separator(tmp_path):
    url = f"sqlite:///{tmp_path / 'x.db'}"
    r = subprocess.run([sys.executable, "-m", "app.dblock", "--", "sh", "-c", "echo RUN; exit 3"], cwd=ROOT,
                       env=_env(url), capture_output=True, text=True, timeout=60)
    assert r.returncode == 3 and "RUN" in r.stdout


def test_cli_requires_database_url_and_command():
    r = subprocess.run([sys.executable, "-m", "app.dblock", "--", "true"], cwd=ROOT, env=_env(),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "DATABASE_URL" in r.stderr
    r = subprocess.run([sys.executable, "-m", "app.dblock"], cwd=ROOT, env=_env("sqlite:///x.db"),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "Użycie" in r.stderr


@needs_mariadb
def test_lock_is_held_on_mariadb_and_released(mariadb_url):
    engine = sa.create_engine(mariadb_url)
    try:
        def used():
            with engine.connect() as conn:  # osobne połączenie = inna replika
                return conn.execute(sa.text("SELECT IS_USED_LOCK(:n)"), {"n": LOCK_NAME}).scalar() is not None
        assert not used()
        with migration_lock(mariadb_url) as held:
            assert held is True and used()
            with pytest.raises(RuntimeError, match="blokad"):  # druga replika nie doczekała się w limicie
                run_locked(mariadb_url, ["true"], timeout=0)
        assert not used()
        assert run_locked(mariadb_url, ["sh", "-c", "exit 5"]) == 5  # polecenie wykonane, blokada zwolniona po nim
        assert not used()
    finally:
        engine.dispose()
