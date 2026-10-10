"""Migracja e4a1d7c03b52 na danych sprzed v0.2.0: duplikaty między zakresami (FR-8) i ponawialność (FR-9).

Migracje uruchamiane w podprocesie (`flask db upgrade`) — konfiguracja logowania Alembica nie wpływa na
resztę testów; dane wstawiane surowym SQL w schemacie z rewizji b7f3c2a91d40."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BEFORE = "b7f3c2a91d40"
HEAD = "e4a1d7c03b52"


def _flask(db_path, tmp_path, *args):
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1", DATABASE_URL=f"sqlite:///{db_path}",
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
