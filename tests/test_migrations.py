"""Migracje: e4a1d7c03b52 na danych sprzed v0.2.0 (duplikaty między zakresami FR-8, ponawialność FR-9),
86ccf8021da9 (mikrosekundy w documents.created_at / updated_at — DATETIME(6) w MariaDB, na SQLite bez zmian)
i 2eff54106035 (indeks listy synchronizacji API: documents (api_key_id, updated_at, id)).

Migracje uruchamiane w podprocesie (`flask db upgrade`) — konfiguracja logowania Alembica nie wpływa na
resztę testów; dane wstawiane surowym SQL w schemacie z rewizji b7f3c2a91d40. Testy oznaczone `needs_mariadb`
działają na prawdziwej, pustej bazie MariaDB (`TEST_MARIADB_URL`, nazwa bazy musi zawierać „test”); bez niej są
pomijane."""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.dialects.mysql.mariadb import MariaDBDialect
from sqlalchemy.schema import CreateTable

from app.extensions import db
from app.models import Document

ROOT = Path(__file__).resolve().parent.parent
BEFORE = "b7f3c2a91d40"
UNIQUE_KEYS = "e4a1d7c03b52"  # unikalność kluczy w bazie (v0.2.0)
MICRO = "86ccf8021da9"  # mikrosekundy w czasie dokumentów (v0.5.0)
SYNC_INDEX = "2eff54106035"  # indeks listy synchronizacji API (v0.5.0)
SYNC_INDEX_NAME = "ix_documents_api_key_updated"
SYNC_INDEX_COLUMNS = ["api_key_id", "updated_at", "id"]


def _flask(db_path, tmp_path, *args, url=None):
    """`flask db …` w podprocesie: na SQLite w `db_path` albo — z `url` — na wskazanej bazie (MariaDB)."""
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1", DATABASE_URL=url or f"sqlite:///{db_path}",
               STORAGE_DIR=str(tmp_path / "storage"), SECRET_KEY="migr-test", FLASK_APP="app:create_app",
               DEMO_MODE="0", ADMIN_PASSWORD="")
    r = subprocess.run([sys.executable, "-m", "flask", "db", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    return r


def _ok(r):
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _dup_issue(ref):
    return {"code": "duplicate", "severity": "blocking", "message": f"Ta faktura była już przetworzona (dokument #{ref}).",
            "field": None, "line_no": None, "source_path": None, "source_value": str(ref), "suggestions": []}


WARN = {"code": "sum_mismatch", "severity": "warning", "message": "drobna różnica", "field": None,
        "line_no": None, "source_path": None, "source_value": None, "suggestions": []}


def _populate(db_path):
    """Stan bazy jak po v0.1.1 (duplikaty liczone globalnie, bez zakresu klucza API)."""
    c = sqlite3.connect(db_path)
    c.execute("INSERT INTO units (id, code, name, is_base) VALUES (1, 'szt', 'sztuka', 1)")
    c.execute("INSERT INTO suppliers (id, name, tax_id) VALUES (1, 'Fikcyjny', 'pl 999-000-00-11')")
    c.execute("INSERT INTO suppliers (id, name, tax_id) VALUES (2, 'Kopia', 'PL9990000011')")
    for k in (1, 2):
        c.execute("INSERT INTO api_keys (id, name, prefix, key_hash, active) VALUES (?, ?, ?, ?, 1)",
                  (k, f"Klucz {k}", f"xp_{k}", f"{k}" * 64))
    docs = [
        # id, api_key, number, status, issues
        (1, None, "F/1", "approved", []),
        (2, 1, "F/1", "duplicate", [_dup_issue(1), WARN]),   # inny zakres → do ponownego przetworzenia
        (3, 1, "F/1", "duplicate", [_dup_issue(1)]),         # inny zakres, ale #2 jest już oryginałem klucza 1
        (4, None, "F/1", "duplicate", [_dup_issue(1)]),      # ten sam zakres (panel) → zostaje duplikatem
        (5, 2, "F/1", "approved", []),                       # v0.1.1: drugi klucz, zatwierdzony
        (6, 2, "F/1", "duplicate", [_dup_issue(5)]),         # ten sam zakres → zostaje
        (7, 2, "F/9", "duplicate", [_dup_issue(1)]),         # duplikat po sha256 dokumentu panelu
        (8, 1, "F/8", "duplicate", [_dup_issue(999)]),       # wskazuje nieistniejący dokument → bez zmian
        (9, 1, "F/7", "rejected", [_dup_issue(1)]),          # odrzucony — nie ruszamy
    ]
    for did, key, num, status, issues in docs:
        c.execute("INSERT INTO documents (id, source, sha256, supplier_id, status, number, issues, result, overrides,"
                  " api_key_id) VALUES (?, 'upload', ?, 1, ?, ?, ?, ?, '{}', ?)",
                  (did, f"{did:064d}", status, num, json.dumps(issues), json.dumps({"number": num}), key))
    for aid, alias in enumerate(["pcs", "PCS ", "Pcs", "łyżka", "lyzka", "Kärton", "karton"], start=1):
        c.execute("INSERT INTO unit_aliases (id, alias, alias_norm, unit_id, supplier_id) VALUES (?, ?, ?, 1, NULL)",
                  (aid, alias, alias.strip().lower()))
    c.execute("INSERT INTO unit_aliases (id, alias, alias_norm, unit_id, supplier_id) VALUES (20, 'op', 'op', 1, 1)")
    c.commit()
    c.close()


def _docs(db_path):
    c = sqlite3.connect(db_path)
    rows = {r[0]: {"status": r[1], "issues": json.loads(r[2] or "[]"), "key": r[3]}
            for r in c.execute("SELECT id, status, issues, dedupe_key FROM documents")}
    c.close()
    return rows


@pytest.fixture
def old_db(tmp_path):
    db_path = tmp_path / "old.db"
    _ok(_flask(db_path, tmp_path, "upgrade", BEFORE))
    _populate(db_path)
    return db_path


def test_upgrade_recomputes_cross_scope_duplicates(old_db, tmp_path):
    _ok(_flask(old_db, tmp_path, "upgrade"))
    d = _docs(old_db)
    # #2: był duplikatem dokumentu panelu — teraz oryginał klucza 1, do ponownego przetworzenia
    assert d[2]["status"] == "needs_review"
    codes = [i["code"] for i in d[2]["issues"]]
    assert "duplicate" not in codes and "reprocess_required" in codes and "sum_mismatch" in codes
    assert d[2]["key"]
    # #3: w zakresie klucza 1 oryginałem jest #2
    assert d[3]["status"] == "duplicate" and d[3]["issues"][0]["source_value"] == "2" and not d[3]["key"]
    assert d[4]["status"] == "duplicate" and d[4]["issues"][0]["source_value"] == "1"
    assert d[5]["status"] == "approved" and d[5]["key"]
    assert d[6]["status"] == "duplicate" and d[6]["issues"][0]["source_value"] == "5"
    assert d[7]["status"] == "needs_review" and d[7]["key"]
    assert d[8]["status"] == "duplicate"
    assert d[9]["status"] == "rejected"
    _ok(_flask(old_db, tmp_path, "check"))


def test_upgrade_alias_dedupe_matches_python_key(old_db, tmp_path):
    _ok(_flask(old_db, tmp_path, "upgrade"))
    c = sqlite3.connect(old_db)
    left = sorted(r[0] for r in c.execute("SELECT alias FROM unit_aliases WHERE supplier_id IS NULL"))
    keys = [r[0] for r in c.execute("SELECT alias_key FROM unit_aliases")]
    c.close()
    # „pcs”/„PCS ”/„Pcs” → najstarszy; „Kärton”/„karton” równe po złożeniu akcentów; „łyżka” ≠ „lyzka” (ł nie
    # rozkłada się w NFKD) — oba zostają, a unikat na haszu nie zależy od kolacji bazy
    assert left == sorted(["pcs", "łyżka", "lyzka", "Kärton"])
    assert all(k and len(k) == 64 for k in keys) and len(set(keys)) == len(keys)


def _partial_mariadb_like_state(db_path):
    """Symulacja częściowego upgrade'u na MariaDB (DDL nietransakcyjny): część kroków wykonana,
    alembic_version nadal na poprzedniej rewizji."""
    c = sqlite3.connect(db_path)
    c.execute("UPDATE suppliers SET tax_id = 'PL9990000011' WHERE id = 1")
    c.execute("UPDATE suppliers SET tax_id = NULL WHERE id = 2")
    c.execute("DROP INDEX ix_suppliers_tax_id")
    c.execute("CREATE UNIQUE INDEX ix_suppliers_tax_id ON suppliers (tax_id)")
    c.execute("ALTER TABLE unit_aliases ADD COLUMN alias_key VARCHAR(64)")
    c.execute("ALTER TABLE unit_conversions ADD COLUMN supplier_scope INTEGER DEFAULT '0' NOT NULL")
    c.execute("ALTER TABLE unit_conversions ADD COLUMN product_scope INTEGER DEFAULT '0' NOT NULL")
    c.execute("CREATE UNIQUE INDEX uq_conversion_scope ON unit_conversions (supplier_scope, product_scope, from_unit_id)")
    c.execute("ALTER TABLE product_mappings ADD COLUMN match_key VARCHAR(64)")
    c.execute("ALTER TABLE documents ADD COLUMN dedupe_hash VARCHAR(64)")
    c.commit()
    c.close()


def test_upgrade_resumes_after_partial_failure(old_db, tmp_path):
    _partial_mariadb_like_state(old_db)
    _ok(_flask(old_db, tmp_path, "upgrade"))
    _ok(_flask(old_db, tmp_path, "check"))
    d = _docs(old_db)
    assert d[2]["status"] == "needs_review" and d[3]["status"] == "duplicate"


def test_downgrade_and_upgrade_again(old_db, tmp_path):
    _ok(_flask(old_db, tmp_path, "upgrade"))
    _ok(_flask(old_db, tmp_path, "downgrade", BEFORE))
    _ok(_flask(old_db, tmp_path, "upgrade"))
    _ok(_flask(old_db, tmp_path, "check"))


# ---------------------------------------------------------------- mikrosekundy w czasie dokumentów (86ccf8021da9)

needs_mariadb = pytest.mark.skipif(
    not os.environ.get("TEST_MARIADB_URL"),
    reason="test na prawdziwej MariaDB — ustaw TEST_MARIADB_URL (pusta baza testowa)")


@pytest.mark.parametrize("dialect", [mysql.dialect(), MariaDBDialect()], ids=["mysql", "mariadb"])
def test_document_times_have_microseconds_on_mysql_family(dialect):
    ddl = str(CreateTable(Document.__table__).compile(dialect=dialect))
    assert "created_at DATETIME(6)" in ddl and "updated_at DATETIME(6)" in ddl


def test_document_times_are_plain_datetime_on_sqlite():
    """SQLite przechowuje mikrosekundy bez zmiany typu kolumny."""
    ddl = str(CreateTable(Document.__table__).compile(dialect=sqlite.dialect()))
    assert "created_at DATETIME," in ddl and "updated_at DATETIME," in ddl
    assert "DATETIME(6)" not in ddl


@pytest.mark.parametrize("revision, parent", [(MICRO, UNIQUE_KEYS), (SYNC_INDEX, MICRO)], ids=["mikro", "indeks"])
def test_revision_follows_parent_on_a_single_chain(revision, parent):
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1  # jedna głowa, bez rozgałęzień
    assert script.get_revision(revision).down_revision == parent


def _sqlite_scalar(db_path, sql):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


def _sqlite_schema(db_path):
    c = sqlite3.connect(db_path)
    try:
        return sorted(c.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    finally:
        c.close()


def test_micro_migration_is_noop_on_sqlite(old_db, tmp_path):
    """Na SQLite rewizja się przesuwa (w obie strony), a schemat zostaje bez zmian."""
    _ok(_flask(old_db, tmp_path, "upgrade", UNIQUE_KEYS))
    schema = _sqlite_schema(old_db)
    _ok(_flask(old_db, tmp_path, "upgrade", MICRO))
    assert _sqlite_scalar(old_db, "SELECT version_num FROM alembic_version") == MICRO
    assert _sqlite_schema(old_db) == schema
    _ok(_flask(old_db, tmp_path, "downgrade", UNIQUE_KEYS))
    assert _sqlite_scalar(old_db, "SELECT version_num FROM alembic_version") == UNIQUE_KEYS
    assert _sqlite_schema(old_db) == schema


# ---------------------------------------------------------------- indeks listy synchronizacji (2eff54106035)

def _document_indexes(url):
    """{nazwa: kolumny} indeksów tabeli documents — nowe połączenie i inspektor, bez cache."""
    engine = sa.create_engine(url)
    try:
        return {i["name"]: i["column_names"] for i in sa.inspect(engine).get_indexes("documents")}
    finally:
        engine.dispose()


def _check_sync_index_migration(flask, url):
    """Indeks jest po upgrade, znika po downgrade; oba kroki ponawialne. Stany częściowe jak po awarii na MariaDB
    (DDL nietransakcyjny): indeks już jest / już go nie ma, a alembic_version wskazuje rewizję sprzed kroku."""
    flask("upgrade", MICRO)
    assert SYNC_INDEX_NAME not in _document_indexes(url)
    flask("upgrade", SYNC_INDEX)
    assert _document_indexes(url)[SYNC_INDEX_NAME] == SYNC_INDEX_COLUMNS
    flask("stamp", MICRO)
    flask("upgrade", SYNC_INDEX)  # indeks już jest — nie zakłada go drugi raz
    assert _document_indexes(url)[SYNC_INDEX_NAME] == SYNC_INDEX_COLUMNS
    flask("downgrade", MICRO)
    assert SYNC_INDEX_NAME not in _document_indexes(url)
    flask("stamp", SYNC_INDEX)
    flask("downgrade", MICRO)  # indeksu już nie ma — nie próbuje go usuwać
    flask("upgrade")  # do głowy
    assert _document_indexes(url)[SYNC_INDEX_NAME] == SYNC_INDEX_COLUMNS


def test_sync_index_migration_on_sqlite(tmp_path):
    db_path = tmp_path / "index.db"
    _check_sync_index_migration(lambda *args: _ok(_flask(db_path, tmp_path, *args)), f"sqlite:///{db_path}")


# ---- prawdziwa MariaDB (pusta baza testowa z TEST_MARIADB_URL; bez niej testy są pomijane)

def _wipe_mariadb(url):
    """Czyści bazę testową: tabele aplikacji (jak `db.drop_all()`) oraz `alembic_version`."""
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("SET FOREIGN_KEY_CHECKS = 0"))  # kolejność kasowania bez znaczenia, także po awarii
            db.metadata.drop_all(conn)
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


def _require_test_database(url):
    """Testy czyszczą całą bazę — odmowa, gdy nazwa bazy w URL nie zawiera „test” (np. omyłkowo wskazana baza demo)."""
    if "test" not in (sa.make_url(url).database or "").lower():
        pytest.fail("TEST_MARIADB_URL musi wskazywać bazę testową (nazwa bazy zawiera „test”) — testy MariaDB "
                    "usuwają wszystkie tabele.", pytrace=False)


@pytest.mark.parametrize("url", [
    pytest.param("mysql+pymysql://u:p@db:3306/xmlparser?charset=utf8mb4", id="baza-demo"),
    pytest.param("mysql+pymysql://tester:test@test-db:3306/xmlparser", id="test-tylko-poza-nazwa-bazy"),
    pytest.param("mysql+pymysql://u:p@db:3306", id="bez-nazwy-bazy"),
])
def test_mariadb_tests_refuse_database_without_test_in_name(url):
    with pytest.raises(pytest.fail.Exception):
        _require_test_database(url)


def test_mariadb_tests_accept_test_database():
    _require_test_database("mysql+pymysql://root:pw@127.0.0.1:18519/xp_test?charset=utf8mb4")


@pytest.fixture
def mariadb_url():
    url = os.environ["TEST_MARIADB_URL"]
    _require_test_database(url)
    _wipe_mariadb(url)
    yield url
    _wipe_mariadb(url)  # także po nieudanym teście


def _time_precision(engine):
    """{kolumna: DATETIME_PRECISION} dla documents.created_at / updated_at według information_schema."""
    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT COLUMN_NAME, DATETIME_PRECISION FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' "
            "AND COLUMN_NAME IN ('created_at', 'updated_at')")).all()
    return {name: precision for name, precision in rows}


def _document_times(engine):
    with engine.connect() as conn:
        return tuple(conn.execute(sa.text("SELECT created_at, updated_at FROM documents")).one())


def _set_updated_at(engine, value):
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE documents SET updated_at = :value"), {"value": value})


@needs_mariadb
def test_micro_migration_on_mariadb(mariadb_url, tmp_path):
    """Prawdziwy ALTER TABLE: 0 → 6 → 0 → 6, ponawialny, z zachowaniem danych i indeksów."""
    seconds = {"created_at": 0, "updated_at": 0}
    micro = {"created_at": 6, "updated_at": 6}
    created, updated = datetime(2026, 10, 11, 6, 4, 38), datetime(2026, 10, 11, 6, 4, 39)
    fraction = datetime(2026, 10, 11, 6, 4, 39, 987654)

    def flask(*args):  # upgrade/downgrade zawsze do konkretnej rewizji — test nie zależy od późniejszych migracji
        return _ok(_flask(None, tmp_path, *args, url=mariadb_url))

    engine = sa.create_engine(mariadb_url)
    try:
        flask("upgrade", UNIQUE_KEYS)
        assert _time_precision(engine) == seconds
        with engine.begin() as conn:  # dokument sprzed zmiany: czas w pełnych sekundach
            conn.execute(sa.text("INSERT INTO documents (source, sha256, status, created_at, updated_at) "
                                 "VALUES ('upload', :sha, 'received', :created, :updated)"),
                         {"sha": "0" * 64, "created": created, "updated": updated})

        flask("upgrade", MICRO)
        assert _time_precision(engine) == micro
        assert _document_times(engine) == (created, updated)  # sekundy zachowane (.000000)
        _set_updated_at(engine, fraction)
        assert _document_times(engine)[1] == fraction  # DATETIME(6) przechowuje mikrosekundy

        flask("upgrade", MICRO)  # druga próba: baza już na tej rewizji
        assert _time_precision(engine) == micro and _document_times(engine)[1] == fraction

        flask("stamp", UNIQUE_KEYS)  # jak po awarii między ALTER a wpisem do alembic_version
        flask("upgrade", MICRO)  # ponowny przebieg migracji na kolumnach, które już mają DATETIME(6)
        assert _time_precision(engine) == micro and _document_times(engine)[1] == fraction

        with engine.begin() as conn:  # stan częściowy: tylko updated_at wrócił do pełnych sekund
            conn.execute(sa.text("ALTER TABLE documents MODIFY updated_at DATETIME NULL"))
        assert _time_precision(engine) == {"created_at": 6, "updated_at": 0}
        flask("stamp", UNIQUE_KEYS)
        flask("upgrade", MICRO)
        assert _time_precision(engine) == micro

        _set_updated_at(engine, fraction)
        flask("downgrade", UNIQUE_KEYS)
        assert _time_precision(engine) == seconds
        assert _document_times(engine) == (created, updated)  # ułamek sekundy obcięty, sekundy zostają

        flask("upgrade", MICRO)
        assert _time_precision(engine) == micro
        indexes = {i["name"] for i in sa.inspect(engine).get_indexes("documents")}
        assert {"ix_documents_created_at", "ix_documents_api_status_created"} <= indexes
    finally:
        engine.dispose()


@needs_mariadb
def test_document_times_keep_microseconds_on_mariadb(mariadb_url, tmp_path):
    """Dwa dokumenty przyjęte tuż po sobie (w tej samej sekundzie) mają różne updated_at — z mikrosekundami."""
    from app import create_app
    from app.services.pipeline import ingest
    from app.services.seed import seed_base, seed_demo
    from tests.test_negotiation_statuses import inv

    app = create_app({"TESTING": True, "SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": mariadb_url,
                      "STORAGE_DIR": str(tmp_path / "s"), "DEMO_MODE": True, "ADMIN_PASSWORD": ""})
    with app.app_context():
        try:
            db.create_all()
            assert _time_precision(db.engine) == {"created_at": 6, "updated_at": 6}
            seed_base()
            seed_demo()
            ids = [ingest(inv("MIKRO/1"), "m1.json").id, ingest(inv("MIKRO/2"), "m2.json").id]
            db.session.expire_all()  # odczyt z bazy, nie z pamięci sesji
            first, second = (db.session.get(Document, i) for i in ids)
            times = (first.updated_at, second.updated_at)
            assert times[0] != times[1]
            assert all(t.microsecond for t in times), times  # DATETIME(0) obcięłoby ułamki do okrągłych sekund
        finally:
            db.session.remove()  # zwolnienie transakcji — inaczej DROP TABLE czeka na blokadę metadanych
            db.engine.dispose()


@needs_mariadb
def test_sync_index_migration_on_mariadb(mariadb_url, tmp_path):
    """Prawdziwe CREATE / DROP INDEX na InnoDB — DROP przechodzi, bo klucz obcy api_key_id ma nadal indeks
    ix_documents_api_status_created (api_key_id na pierwszej pozycji)."""
    _check_sync_index_migration(lambda *args: _ok(_flask(None, tmp_path, *args, url=mariadb_url)), mariadb_url)
