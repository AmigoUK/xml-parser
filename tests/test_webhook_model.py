"""Fundament webhooków (v0.9.0): model `WebhookDelivery` (outbox dostaw), migracja 99f2fe61d963
(`webhook_deliveries`), klucze obce (CASCADE od klucza API, blokada usunięcia dokumentu z dostawą), `reset_demo`
z dostawami i domyślne zmienne konfiguracyjne. Migracje w podprocesie (`flask db …`) jak w tests/test_migrations.py;
MariaDB tylko przez `needs_mariadb`."""
import os
import sqlite3
import subprocess
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    EVENT_STATUS_CHANGED,
    EVENT_TEST,
    WEBHOOK_FAILED,
    WEBHOOK_PENDING,
    WEBHOOK_SENT,
    ApiKey,
    Document,
    WebhookDelivery,
)
from tests.conftest import mariadb_url, needs_mariadb  # noqa: F401 (fixture)
from tests.test_migrations import ROOT, _flask, _ok

PARENT = "d2c1e7a94f30"  # kolacja binarna products.code (v0.6.0)
WEBHOOKS = "99f2fe61d963"  # tabela webhook_deliveries (v0.9.0)
TABLE = "webhook_deliveries"
INDEXES = {
    "ix_webhook_deliveries_uuid": ["uuid"],
    "ix_webhook_deliveries_document_id": ["document_id"],
    "ix_webhook_deliveries_status": ["status"],
    "ix_webhook_deliveries_next_attempt_at": ["next_attempt_at"],
    "ix_webhook_deliveries_api_key_created": ["api_key_id", "created_at", "id"],
}
TIME_COLUMNS = ("created_at", "next_attempt_at", "sent_at")


def _key(name="Hurtownia Alfa — ERP"):
    key = ApiKey(name=name, prefix="xp_test", key_hash=os.urandom(32).hex(), active=True)
    db.session.add(key)
    db.session.flush()
    return key


def _document(key=None, sha="a" * 64):
    doc = Document(source="api", sha256=sha, status="approved", api_key_id=key.id if key else None)
    db.session.add(doc)
    db.session.flush()
    return doc


def _delivery(key, doc=None, event=EVENT_STATUS_CHANGED):
    d = WebhookDelivery(api_key_id=key.id, document_id=doc.id if doc else None, event=event,
                        payload={"event": event, "id": doc.id if doc else None, "status": "approved"})
    db.session.add(d)
    db.session.flush()
    return d


# ---------------------------------------------------------------- migracja

def _schema(url):
    """(tabele, {indeks: kolumny} tabeli webhook_deliveries) — nowe połączenie i inspektor, bez cache."""
    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names())
        indexes = {i["name"]: i["column_names"] for i in insp.get_indexes(TABLE)} if TABLE in tables else {}
        return tables, indexes
    finally:
        engine.dispose()


def _check_webhook_migration(flask, url, drop_index):
    """Tabela i indeksy po upgrade, znikają po downgrade; oba kroki ponawialne (DDL MariaDB nietransakcyjny:
    po awarii tabela już jest / już jej nie ma, a alembic_version wskazuje rewizję sprzed kroku)."""
    flask("upgrade", PARENT)
    assert TABLE not in _schema(url)[0]
    flask("upgrade", WEBHOOKS)
    tables, indexes = _schema(url)
    assert TABLE in tables and indexes == INDEXES
    flask("stamp", PARENT)
    flask("upgrade", WEBHOOKS)  # tabela już jest — nie zakłada jej drugi raz
    assert _schema(url)[1] == INDEXES
    drop_index("ix_webhook_deliveries_status")  # stan częściowy: tabela jest, jednego indeksu brak
    flask("stamp", PARENT)
    flask("upgrade", WEBHOOKS)  # dokłada brakujący indeks
    assert _schema(url)[1] == INDEXES
    flask("downgrade", PARENT)
    assert TABLE not in _schema(url)[0]
    flask("stamp", WEBHOOKS)
    flask("downgrade", PARENT)  # tabeli już nie ma — nie próbuje jej usuwać
    flask("upgrade")  # do głowy
    assert _schema(url)[1] == INDEXES
    flask("check")  # modele = schemat po migracjach


def test_webhook_deliveries_upgrade_and_downgrade_on_sqlite(tmp_path):
    db_path = tmp_path / "webhooks.db"

    def drop_index(name):
        c = sqlite3.connect(db_path)
        c.execute(f"DROP INDEX {name}")
        c.commit()
        c.close()

    _check_webhook_migration(lambda *args: _ok(_flask(db_path, tmp_path, *args)), f"sqlite:///{db_path}",
                             drop_index)


@needs_mariadb
def test_webhook_deliveries_schema_matches_models_on_mariadb(mariadb_url, tmp_path):
    """Prawdziwe CREATE/DROP TABLE na InnoDB: czasy DATETIME(6), klucz api_key_id z ON DELETE CASCADE, document_id
    bez kaskady; `flask db check` bez różnic względem modeli."""
    engine = sa.create_engine(mariadb_url)

    def drop_index(name):
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP INDEX {name} ON {TABLE}"))

    try:
        _check_webhook_migration(lambda *args: _ok(_flask(None, tmp_path, *args, url=mariadb_url)), mariadb_url,
                                 drop_index)
        with engine.connect() as conn:
            precision = dict(conn.execute(sa.text(
                "SELECT COLUMN_NAME, DATETIME_PRECISION FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND DATA_TYPE = 'datetime'"), {"t": TABLE}).all())
            rules = dict(conn.execute(sa.text(
                "SELECT k.COLUMN_NAME, r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k "
                "JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
                "AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
                "WHERE k.TABLE_SCHEMA = DATABASE() AND k.TABLE_NAME = :t"), {"t": TABLE}).all())
        assert precision == {c: 6 for c in TIME_COLUMNS}
        assert rules["api_key_id"] == "CASCADE"
        assert rules["document_id"] in ("RESTRICT", "NO ACTION")
    finally:
        engine.dispose()


# ---------------------------------------------------------------- model i klucze obce

def test_deleting_api_key_cascades_deliveries(app):
    key, other = _key(), _key("Hurtownia Beta")
    first = _delivery(key, event=EVENT_TEST)
    _delivery(other, event=EVENT_TEST)
    db.session.commit()
    # wartości domyślne modelu
    assert first.status == WEBHOOK_PENDING and first.attempts == 0 and first.created_at is not None
    assert len(first.uuid) == 36 and first.next_attempt_at is None and first.sent_at is None
    assert first.payload["event"] == EVENT_TEST and key.deliveries == [first]
    assert (WEBHOOK_SENT, WEBHOOK_FAILED, EVENT_STATUS_CHANGED) == ("sent", "failed", "document.status_changed")

    db.session.delete(key)  # ORM: delete-orphan na ApiKey.deliveries
    db.session.commit()
    assert WebhookDelivery.query.filter_by(api_key_id=key.id).count() == 0
    db.session.execute(sa.delete(ApiKey).where(ApiKey.id == other.id))  # baza: ON DELETE CASCADE
    db.session.commit()
    assert WebhookDelivery.query.count() == 0


def test_deleting_document_with_delivery_is_rejected(app):
    key = _key()
    doc = _document(key)
    _delivery(key, doc)
    db.session.commit()
    assert doc.api_key is key  # Document.api_key
    db.session.delete(doc)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(Document, doc.id) is not None and WebhookDelivery.query.count() == 1


def test_reset_demo_removes_deliveries_before_documents(seeded):
    from app.services.seed import reset_demo

    key = _key()
    _delivery(key, _document(key, sha="b" * 64))
    _delivery(key, event=EVENT_TEST)
    db.session.commit()
    reset_demo()  # bez IntegrityError (FK document_id bez kaskady)
    assert WebhookDelivery.query.count() == 0
    assert Document.query.count() == 0


# ---------------------------------------------------------------- konfiguracja

def test_config_webhook_defaults(app):
    assert app.config["PUBLIC_BASE_URL"] == ""
    assert app.config["WEBHOOK_ALLOW_HTTP"] is False
    assert app.config["WEBHOOK_ALLOWED_HOSTS"] == ""
    assert app.config["WEBHOOK_RETENTION_DAYS"] == 30
    assert app.config["WEBHOOK_HEARTBEAT_FILE"] == ""
    # wartości ze środowiska (nowy proces — Config czyta os.environ przy imporcie)
    code = ("from app.config import Config as C\n"
            "print(repr((C.PUBLIC_BASE_URL, C.WEBHOOK_ALLOW_HTTP, C.WEBHOOK_ALLOWED_HOSTS, C.WEBHOOK_RETENTION_DAYS,"
            " C.WEBHOOK_HEARTBEAT_FILE)))\n")
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1", PUBLIC_BASE_URL="https://xp.example.test",
               WEBHOOK_ALLOW_HTTP="tak", WEBHOOK_ALLOWED_HOSTS="erp.local,10.0.0.0/8", WEBHOOK_RETENTION_DAYS="7",
               WEBHOOK_HEARTBEAT_FILE="/tmp/xp-worker.heartbeat")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == repr(("https://xp.example.test", True, "erp.local,10.0.0.0/8", 7,
                                     "/tmp/xp-worker.heartbeat"))
