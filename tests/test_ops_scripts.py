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
    ok) printf -- '-- MariaDB dump\nCREATE TABLE `documents` (id int);\nINSERT INTO documents VALUES (1);\n';
        printf -- '-- Dump completed on 2026-10-10\n';;
    fail) printf -- '-- MariaDB dump\n'; echo "mariadb-dump: Got error: 1049: Unknown database" >&2; exit 2;;
    empty) exit 0;;
    truncated) printf -- '-- MariaDB dump\nCREATE TABLE `documents` (id int);\n';;
  esac
elif [ "$svc" = app ]; then
  [ -n "${FAKE_LOG:-}" ] && echo "$*" >> "$FAKE_LOG"
  case "${FAKE_APP:-ok}" in
    ok) d=$(mktemp -d); echo plik > "$d/a.xml"; tar -C "$d" -cf - .; rm -rf "$d";;
    fail) echo "service app is not running" >&2; exit 1;;
  esac
fi
"""


def _run_backup(tmp_path, db="ok", app="ok", backup_dir=None):
    proj = tmp_path / "proj"
    (proj / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "backup.sh", proj / "tools" / "backup.sh")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_DB=db, FAKE_APP=app,
               FAKE_LOG=str(tmp_path / "docker.log"))
    env.pop("BACKUP_DIR", None)
    if backup_dir is not None:
        env["BACKUP_DIR"] = str(backup_dir)
    r = subprocess.run([str(proj / "tools" / "backup.sh")], env=env, capture_output=True, text=True, timeout=60)
    backups = Path(backup_dir) if backup_dir is not None else proj / "backups"
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

    def test_backup_dir_env_and_storage_dir_from_container(self, tmp_path):
        """BACKUP_DIR wskazuje inny wolumen/dysk; archiwum storage czyta STORAGE_DIR z kontenera app."""
        r, dirs = _run_backup(tmp_path, backup_dir=tmp_path / "kopie")
        assert r.returncode == 0, r.stderr
        assert len(dirs) == 1 and dirs[0].parent == tmp_path / "kopie"
        assert not (tmp_path / "proj" / "backups").exists()
        assert "STORAGE_DIR" in (tmp_path / "docker.log").read_text()

    def test_failed_storage_archive_is_detected(self, tmp_path):
        r, dirs = _run_backup(tmp_path, app="fail")
        assert r.returncode != 0
        assert "Kopia zapasowa zapisana" not in r.stdout
        assert dirs == []


def test_dockerfile_sets_storage_dir():
    text = (ROOT / "Dockerfile").read_text()
    assert "STORAGE_DIR=/data/storage" in text


def test_dockerfile_has_healthcheck_and_internal_port():
    """Sonda w obrazie (każda platforma ją dziedziczy) i jedno źródło portu wewnętrznego."""
    text = (ROOT / "Dockerfile").read_text()
    assert "APP_INTERNAL_PORT=5010" in text
    health = next(line for line in text.splitlines() if line.startswith("HEALTHCHECK"))
    assert "--start-period=" in health
    assert "/healthz" in text and "APP_INTERNAL_PORT" in text.split("HEALTHCHECK", 1)[1]


def test_compose_app_gets_only_app_variables():
    """Usługa app nie dostaje całego .env (hasła roota MariaDB) — tylko zmienne aplikacji; port z APP_INTERNAL_PORT;
    sonda z obrazu (bez drugiej kopii w compose)."""
    import yaml
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]
    assert "env_file" not in app and "healthcheck" not in app
    env = app["environment"]
    assert "MARIADB_ROOT_PASSWORD" not in env and "MARIADB_PASSWORD" not in env
    for name in ("SECRET_KEY", "DATABASE_URL", "STORAGE_DIR", "TRUSTED_PROXY_COUNT", "SESSION_COOKIE_SECURE",
                 "PREFERRED_URL_SCHEME", "APP_INTERNAL_PORT", "MIGRATE_ON_START", "GUNICORN_CMD_ARGS"):
        assert name in env, name
    assert "${TRUSTED_PROXY_COUNT:-0}" in str(env["TRUSTED_PROXY_COUNT"])  # brak w .env = bezpieczna wartość
    assert any("${APP_INTERNAL_PORT:-5010}" in p for p in app["ports"])
    assert "MARIADB_ROOT_PASSWORD" in compose["services"]["db"]["environment"]


ENTRY = ROOT / "docker" / "entrypoint.sh"


DB_URL = "mysql+pymysql://xp:tajne@db:3306/xp?charset=utf8mb4"


def _run_entrypoint(tmp_path, probe="ok", upgrade="ok", writable=True, database_url=DB_URL, **extra_env):
    """Uruchamia entrypoint z atrapami id/python/flask/gunicorn/sleep (bez roota, bez Dockera). Atrapa python:
    `-m app.dblock -- cmd…` wykonuje cmd (i loguje DBLOCK), inne wywołania to sonda bazy o zadanym wyniku."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)  # test może uruchomić entrypoint kilka razy w jednym katalogu
    probe_body = {
        "ok": "exit 0",
        "down": "echo \"OperationalError: (2003, Can't connect to MySQL server)\" >&2; exit 3",
        "config": "echo 'ArgumentError: Could not parse SQLAlchemy URL' >&2; exit 1",
    }[probe]
    upgrade_body = {"ok": "exit 0", "fail": "echo 'Duplicate column name supplier_scope' >&2; exit 1"}[upgrade]
    fakes = {
        "id": "#!/bin/sh\necho 10001\n",
        "python": ("#!/bin/sh\nif [ \"$1\" = -m ] && [ \"$2\" = app.dblock ]; then shift 3; echo \"DBLOCK $*\" >&2; "
                   f"exec \"$@\"; fi\n{probe_body}\n"),
        "flask": ("#!/bin/sh\n[ \"$1\" = seed ] && echo FLASK_SEED >&2 && exit 0\n[ \"$1\" = db ] || exit 0\n"
                  f"echo FLASK_UPGRADE >&2\n{upgrade_body}\n"),
        "gunicorn": "#!/bin/sh\necho GUNICORN \"$@\" ARGS=\"$GUNICORN_CMD_ARGS\"\n",
        "sleep": "#!/bin/sh\nexit 0\n",
    }
    for name, body in fakes.items():
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)
    work = tmp_path / "work"
    (work / "migrations").mkdir(parents=True, exist_ok=True)
    storage = tmp_path / "storage"
    if writable:
        storage.mkdir(exist_ok=True)
    else:
        storage.write_text("to nie katalog")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", DB_WAIT_ATTEMPTS="3", STORAGE_DIR=str(storage))
    for name in ("DATABASE_URL", "APP_INTERNAL_PORT", "PORT", "MIGRATE_ON_START", "GUNICORN_CMD_ARGS",
                 "GUNICORN_WORKERS", "GUNICORN_THREADS", "GUNICORN_TIMEOUT", "GUNICORN_WORKER_TMP_DIR"):
        env.pop(name, None)
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    env.update(extra_env)
    return subprocess.run(["sh", str(ENTRY)], cwd=work, env=env, capture_output=True, text=True, timeout=60)


def test_entrypoint_happy_path_starts_gunicorn(tmp_path):
    r = _run_entrypoint(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "GUNICORN" in r.stdout and "0.0.0.0:5010" in r.stdout
    assert "FLASK_UPGRADE" in r.stderr and "FLASK_SEED" in r.stderr


def test_entrypoint_runs_migrations_and_seed_under_db_lock(tmp_path):
    """Wiele replik startujących naraz: migracje i seed pod blokadą bazy (python -m app.dblock)."""
    r = _run_entrypoint(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "DBLOCK flask db upgrade" in r.stderr and "DBLOCK flask seed" in r.stderr


def test_entrypoint_skips_migrations_when_disabled(tmp_path):
    """MIGRATE_ON_START=0: platforma uruchamia migracje osobnym zadaniem (init container / job)."""
    r = _run_entrypoint(tmp_path, MIGRATE_ON_START="0")
    assert r.returncode == 0, r.stderr
    assert "FLASK_UPGRADE" not in r.stderr and "FLASK_SEED" not in r.stderr
    assert "MIGRATE_ON_START" in r.stderr and "GUNICORN" in r.stdout


@pytest.mark.parametrize("env, port", [({"APP_INTERNAL_PORT": "6010"}, "6010"),
                                      ({"APP_INTERNAL_PORT": "6010", "PORT": "7000"}, "7000")])
def test_entrypoint_binds_internal_port(tmp_path, env, port):
    """Port wewnętrzny z APP_INTERNAL_PORT; PORT platformy (Cloud Run, Heroku) ma pierwszeństwo."""
    r = _run_entrypoint(tmp_path, **env)
    assert r.returncode == 0, r.stderr
    assert f"0.0.0.0:{port}" in r.stdout


def test_entrypoint_requires_database_url(tmp_path):
    r = _run_entrypoint(tmp_path, database_url=None)
    assert r.returncode != 0
    assert "DATABASE_URL" in r.stderr
    assert "Baza niegotowa" not in r.stderr and "FLASK_UPGRADE" not in r.stderr and "GUNICORN" not in r.stdout


@pytest.mark.parametrize("url", ["sqlite:///xmlparser-dev.db", "SQLite:////data/x.db"])
def test_entrypoint_refuses_sqlite(tmp_path, url):
    """W kontenerze SQLite to błąd konfiguracji (plik w /app roota, nietrwały), nie cichy fallback."""
    r = _run_entrypoint(tmp_path, database_url=url)
    assert r.returncode != 0
    assert "SQLite" in r.stderr and "DATABASE_URL" in r.stderr
    assert "Baza niegotowa" not in r.stderr and "GUNICORN" not in r.stdout


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


def test_entrypoint_gunicorn_flags_as_separate_variables(tmp_path):
    """Pojedynczą flagę nadpisuje osobna zmienna (GUNICORN_WORKERS/THREADS/TIMEOUT) — bez przepisywania całego
    zestawu."""
    r = _run_entrypoint(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "-k gthread -w 2 --threads 8 --timeout 60" in r.stdout and "--max-requests 1000" in r.stdout
    r = _run_entrypoint(tmp_path, GUNICORN_WORKERS="4", GUNICORN_THREADS="16", GUNICORN_TIMEOUT="90")
    assert "-w 4 --threads 16 --timeout 90" in r.stdout and "--max-requests 1000" in r.stdout


def test_entrypoint_worker_tmp_dir_only_when_directory_exists(tmp_path):
    """--worker-tmp-dir /dev/shm tylko, gdy katalog istnieje (runtime bez /dev/shm nie może wywrócić startu)."""
    r = _run_entrypoint(tmp_path)
    assert "--worker-tmp-dir /dev/shm" in r.stdout
    r = _run_entrypoint(tmp_path, GUNICORN_WORKER_TMP_DIR=str(tmp_path / "nie-ma"))
    assert r.returncode == 0 and "--worker-tmp-dir" not in r.stdout
    shm = tmp_path / "shm"
    shm.mkdir()
    r = _run_entrypoint(tmp_path, GUNICORN_WORKER_TMP_DIR=str(shm))
    assert f"--worker-tmp-dir {shm}" in r.stdout


def test_entrypoint_gunicorn_cmd_args_replaces_whole_set(tmp_path):
    r = _run_entrypoint(tmp_path, GUNICORN_CMD_ARGS="-w 1 --timeout 10")
    assert "ARGS=-w 1 --timeout 10" in r.stdout and "--threads" not in r.stdout
