"""Sonda bazy dla entrypointu (app/dbprobe.py): 0 = OK, 3 = baza nieosiągalna (ponawiać), 1 = błąd konfiguracji
(nie ponawiać: zły URL, złe hasło/użytkownik/baza, SQLite nieotwieralny, brak sterownika)."""
import subprocess
import sys
from pathlib import Path

from app.dbprobe import main
from tests.conftest import mariadb_url, needs_mariadb  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parent.parent


def test_ok_and_unreachable_and_bad_url(tmp_path, capsys):
    assert main(f"sqlite:///{tmp_path / 'x.db'}") == 0
    assert "Baza:" in capsys.readouterr().err
    assert main("mysql+pymysql://xp:tajne@127.0.0.1:1/xp") == 3  # connection refused: ponawiać
    assert "OperationalError" in capsys.readouterr().err
    assert main("nonsense://x") == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_password_is_not_printed(tmp_path, capsys):
    main("mysql+pymysql://xp:bardzo-tajne@127.0.0.1:1/xp")
    assert "bardzo-tajne" not in capsys.readouterr().err


def test_cli_exit_code(tmp_path):
    r = subprocess.run([sys.executable, "-m", "app.dbprobe"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "DATABASE_URL": f"sqlite:///{tmp_path / 'x.db'}",
                            "PYTHON_DOTENV_DISABLED": "1"})
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-m", "app.dbprobe"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1"})
    assert r.returncode == 1 and "DATABASE_URL" in r.stderr


@needs_mariadb
def test_wrong_password_is_config_error_not_retried(mariadb_url, capsys):
    import sqlalchemy as sa
    url = sa.make_url(mariadb_url).set(password="zle-haslo")
    assert main(url.render_as_string(hide_password=False)) == 1
    err = capsys.readouterr().err
    assert "1045" in err and "zle-haslo" not in err
    assert main(mariadb_url) == 0
