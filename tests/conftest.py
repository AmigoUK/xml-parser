import os

# Lokalny .env nie może zmieniać wyniku testów (np. TRUSTED_PROXY_COUNT): app/config.py pomija load_dotenv() przy
# PYTHON_DOTENV_DISABLED=1, a conftest ładuje się przed modułami testów — więc przed pierwszym importem aplikacji.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
# Podprocesy `python -m flask …` (tests/test_migrations.py) czytają .env przez flask.cli.load_dotenv, które wyłącza
# tylko FLASK_SKIP_DOTENV (PYTHON_DOTENV_DISABLED działa wyłącznie na dotenv.load_dotenv).
os.environ.setdefault("FLASK_SKIP_DOTENV", "1")

import re  # noqa: E402
import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402

from app import create_app, models  # noqa: E402, F401 (models: tabele w db.metadata — potrzebne wipe_mariadb)
from app.extensions import db  # noqa: E402


@sa.event.listens_for(sa.engine.Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite domyślnie NIE egzekwuje kluczy obcych — w testach włączamy je, żeby każdy DELETE/UPDATE naruszający
    klucz obcy kończył się IntegrityError tak jak na MariaDB/InnoDB (inaczej testy nie wykryłyby regresji)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "STORAGE_DIR": str(tmp_path / "storage"),
        "WTF_CSRF_ENABLED": False,
        "DEMO_MODE": True,
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "haslo123",
        "DEMO_API_KEY": "xp_test_demo_key",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


@pytest.fixture
def seeded(app):
    from app.services.seed import seed_base, seed_demo
    seed_base()
    seed_demo()
    return app


@pytest.fixture
def auth_client(seeded, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    return client


# ---- prawdziwa MariaDB (pusta baza testowa z TEST_MARIADB_URL)

TEST_MARIADB_URL = os.environ.get("TEST_MARIADB_URL")
# GitHub Actions ustawia CI=true i uruchamia MariaDB (ci.yml): tam brak TEST_MARIADB_URL to błąd konfiguracji,
# a nie powód do pominięcia — test ma się wywrócić w fixture mariadb_url, nie zniknąć jako „skipped”.
needs_mariadb = pytest.mark.skipif(
    not TEST_MARIADB_URL and not os.environ.get("CI"),
    reason="test na prawdziwej MariaDB — ustaw TEST_MARIADB_URL (pusta baza testowa)")


def require_test_database(url: str) -> None:
    """Testy czyszczą całą bazę — odmowa, gdy nazwa bazy w URL nie zawiera słowa „test” jako osobnego członu
    (xp_test, test-db, test — tak; latest, contest, baza demo — nie)."""
    name = (sa.make_url(url).database or "").lower()
    if "test" not in re.split(r"[^a-z0-9]+", name):
        pytest.fail("TEST_MARIADB_URL musi wskazywać bazę testową (nazwa bazy zawiera człon „test”) — testy MariaDB "
                    "usuwają wszystkie tabele.", pytrace=False)


def wipe_mariadb(url: str) -> None:
    """Czyści bazę testową: tabele aplikacji (jak `db.drop_all()`) oraz `alembic_version`."""
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("SET FOREIGN_KEY_CHECKS = 0"))  # kolejność kasowania bez znaczenia, także po awarii
            db.metadata.drop_all(conn)
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


@pytest.fixture
def mariadb_url():
    url = os.environ.get("TEST_MARIADB_URL")
    if not url:
        pytest.fail("Brak TEST_MARIADB_URL, a CI=true — w CI testy MariaDB są obowiązkowe "
                    "(patrz .github/workflows/ci.yml).", pytrace=False)
    require_test_database(url)
    wipe_mariadb(url)
    yield url
    wipe_mariadb(url)  # także po nieudanym teście
