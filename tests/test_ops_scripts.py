"""Skrypty operacyjne: kopia zapasowa (FR-1) i obraz/entrypoint Dockera (FR-7)."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

FAKE_DOCKER = r"""#!/bin/bash
# Atrapa `docker compose exec -T <usługa> ...` sterowana zmiennymi FAKE_DB / FAKE_APP.
svc=""
for a in "$@"; do case "$a" in db|app) svc="$a"; break;; esac; done
if [ "$svc" = db ]; then
  case "${FAKE_DB:-ok}" in
    ok) printf -- '-- MariaDB dump\nCREATE TABLE `documents` (id int);\nINSERT INTO documents VALUES (1);\n-- Dump completed on 2026-10-10\n';;
    fail) printf -- '-- MariaDB dump\n'; echo "mariadb-dump: Got error: 1049: Unknown database" >&2; exit 2;;
    empty) exit 0;;
    truncated) printf -- '-- MariaDB dump\nCREATE TABLE `documents` (id int);\n';;
  esac
elif [ "$svc" = app ]; then
  case "${FAKE_APP:-ok}" in
    ok) d=$(mktemp -d); echo plik > "$d/a.xml"; tar -C "$d" -cf - .; rm -rf "$d";;
    fail) echo "service app is not running" >&2; exit 1;;
  esac
fi
"""


def _run_backup(tmp_path, db="ok", app="ok"):
    proj = tmp_path / "proj"
    (proj / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "backup.sh", proj / "tools" / "backup.sh")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_DB=db, FAKE_APP=app)
    r = subprocess.run([str(proj / "tools" / "backup.sh")], env=env, capture_output=True, text=True, timeout=60)
    backups = proj / "backups"
    dirs = sorted(p for p in backups.iterdir()) if backups.exists() else []
    return r, dirs


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("gzip") is None, reason="wymaga bash i gzip")
class TestBackupScript:
    def test_success_writes_verified_backup(self, tmp_path):
        r, dirs = _run_backup(tmp_path)
        assert r.returncode == 0, r.stderr
        assert "Kopia zapasowa zapisana" in r.stdout
        assert len(dirs) == 1
        assert (dirs[0] / "db.sql.gz").stat().st_size > 20
        assert (dirs[0] / "storage.tar.gz").exists()

    @pytest.mark.parametrize("mode", ["fail", "empty", "truncated"])
    def test_failed_db_dump_is_detected(self, tmp_path, mode):
        r, dirs = _run_backup(tmp_path, db=mode)
        assert r.returncode != 0
        assert "Kopia zapasowa zapisana" not in r.stdout
        assert dirs == [], "niekompletny katalog kopii musi zostać usunięty"

    def test_failed_storage_archive_is_detected(self, tmp_path):
        r, dirs = _run_backup(tmp_path, app="fail")
        assert r.returncode != 0
        assert "Kopia zapasowa zapisana" not in r.stdout
        assert dirs == []


def test_dockerfile_sets_storage_dir():
    text = (ROOT / "Dockerfile").read_text()
    assert "STORAGE_DIR=/data/storage" in text


ENTRY = ROOT / "docker" / "entrypoint.sh"


def _run_entrypoint(tmp_path, probe="ok", upgrade="ok", writable=True):
    """Uruchamia entrypoint z atrapami id/python/flask/gunicorn/sleep (bez roota, bez Dockera)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    probe_body = {
        "ok": "exit 0",
        "down": "echo \"OperationalError: (2003, Can't connect to MySQL server)\" >&2; exit 3",
        "config": "echo 'ArgumentError: Could not parse SQLAlchemy URL' >&2; exit 1",
    }[probe]
    upgrade_body = {"ok": "exit 0", "fail": "echo 'Duplicate column name supplier_scope' >&2; exit 1"}[upgrade]
    fakes = {
        "id": "#!/bin/sh\necho 10001\n",
        "python": f"#!/bin/sh\ncat >/dev/null\n{probe_body}\n",
        "flask": f"#!/bin/sh\n[ \"$1\" = db ] || exit 0\necho FLASK_UPGRADE >&2\n{upgrade_body}\n",
        "gunicorn": "#!/bin/sh\necho GUNICORN\n",
        "sleep": "#!/bin/sh\nexit 0\n",
    }
    for name, body in fakes.items():
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)
    work = tmp_path / "work"
    (work / "migrations").mkdir(parents=True)
    storage = tmp_path / "storage"
    if writable:
        storage.mkdir()
    else:
        storage.write_text("to nie katalog")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", DB_WAIT_ATTEMPTS="3", STORAGE_DIR=str(storage))
    return subprocess.run(["sh", str(ENTRY)], cwd=work, env=env, capture_output=True, text=True, timeout=60)


def test_entrypoint_happy_path_starts_gunicorn(tmp_path):
    r = _run_entrypoint(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "GUNICORN" in r.stdout


def test_entrypoint_unwritable_storage_is_config_error(tmp_path):
    r = _run_entrypoint(tmp_path, writable=False)
    assert r.returncode != 0
    assert "STORAGE_DIR" in r.stderr
    assert "Baza niegotowa" not in r.stderr
    assert "FLASK_UPGRADE" not in r.stderr


def test_entrypoint_retries_only_db_connection_errors(tmp_path):
    r = _run_entrypoint(tmp_path, probe="down")
    assert r.returncode != 0
    assert r.stderr.count("Baza niegotowa") == 2  # 3 próby, 2 komunikaty o ponowieniu
    assert "po 3 próbach" in r.stderr
    assert "FLASK_UPGRADE" not in r.stderr


def test_entrypoint_db_config_error_not_retried(tmp_path):
    r = _run_entrypoint(tmp_path, probe="config")
    assert r.returncode != 0
    assert "Baza niegotowa" not in r.stderr
    assert r.stderr.count("ArgumentError") == 1


def test_entrypoint_migration_error_not_retried(tmp_path):
    r = _run_entrypoint(tmp_path, upgrade="fail")
    assert r.returncode != 0
    assert r.stderr.count("FLASK_UPGRADE") == 1
    assert "Baza niegotowa" not in r.stderr
    assert "Migracja" in r.stderr
