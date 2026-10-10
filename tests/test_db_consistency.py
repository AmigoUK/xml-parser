"""Pakiet E: spójność DB (BE-1/EDGE-17, BE-7, BE-8/EDGE-18, BE-9, BE-10, BE-14, BE-15, BE-17, BE-18,
EDGE-23, EDGE-31). Dane fikcyjne."""
import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (ApiKey, AuditLog, Document, Product, ProductMapping, Supplier, Template, TemplateVersion,
                        Unit, UnitAlias, UnitConversion)
from app.services import pipeline
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import ingest, process
from app.services.storage import get_storage
from tests.test_negotiation_statuses import KEY, TAX, codes, inv, line, supplier  # noqa: F401 (fixture)

OTHER_TAX = "1110000111"
LIVE = ("approved", "needs_review")


def live_copies(supplier_id, number):
    return [d for d in Document.query.filter_by(supplier_id=supplier_id).all()
            if d.status in LIVE and (d.result or {}).get("number") == number]


# ------------------------------------------------------------------ obejście wykrywania duplikatów (BE-1)


def test_bypass_reprocessing_earlier_copy_after_later_one_was_approved(seeded):
    """Obejście z przeglądu 2dedbc1: oryginał (niższe id) przetworzony PO zatwierdzeniu późniejszej kopii
    nie widział jej (szukał tylko id < własne) — dwie „żywe” kopie tej samej faktury."""
    a = ingest(inv("OB/1", tax=OTHER_TAX), "a.json")
    assert a.status == "needs_review" and a.supplier_id is None  # nieznany dostawca
    b = ingest(inv("OB/1", tax=OTHER_TAX) + b"\n", "b.json")  # ten sam numer, inne bajty (inny sha256)
    assert b.status == "needs_review"
    resolve(b, "create_supplier", {"name": "Obejście sp. z o.o.", "tax_id": OTHER_TAX}, True, "qa")
    assert b.status == "approved"
    process(a)  # ponowne przetworzenie oryginału — teraz rozpoznaje dostawcę po NIP
    db.session.commit()
    assert len(live_copies(b.supplier_id, "OB/1")) == 1
    statuses = sorted([db.session.get(Document, a.id).status, db.session.get(Document, b.id).status])
    assert statuses == ["approved", "duplicate"]


def test_number_case_and_whitespace_are_normalized(supplier):
    a = ingest(inv("FV/7/2026"), "a.json")
    assert a.status == "approved"
    b = ingest(inv("fv/7/2026"), "b.json")
    assert b.status == "duplicate"  # EDGE-31: SQLite i MariaDB zachowują się tak samo
    c = ingest(inv("FV 8/2026"), "c.json")
    d = ingest(inv("FV  8 / 2026".replace(" / ", "/")), "d.json")
    assert c.status == "approved" and d.status == "duplicate"


def test_long_numbers_differing_after_128_chars_are_not_duplicates(supplier):
    base = "N" * 128
    a = ingest(inv(base + "1"), "a.json")
    b = ingest(inv(base + "2"), "b.json")
    assert a.status == "approved" and b.status == "approved"  # EDGE-23: porównanie pełnego numeru
    assert a.dedupe_key and b.dedupe_key and a.dedupe_key != b.dedupe_key


def test_document_key_includes_doc_type():
    from app.engine.keys import document_key
    assert document_key(1, None, "FV/1") == document_key(1, "", " fv/1 ")
    assert document_key(1, "correction", "FV/1") != document_key(1, None, "FV/1")
    assert document_key(1, None, "FV/1") != document_key(2, None, "FV/1")
    assert document_key(None, None, "FV/1") is None and document_key(1, None, "  ") is None


def test_dedupe_key_unique_in_db(supplier):
    a = ingest(inv("U/1"), "a.json")
    assert a.dedupe_key
    other = Document(sha256="0" * 64, status="approved", dedupe_key=a.dedupe_key)
    db.session.add(other)
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_concurrent_insert_race_ends_as_duplicate(supplier, monkeypatch):
    """Wyścig: drugi proces nie widzi (niezatwierdzonego) oryginału — chroni go unikalny indeks."""
    a = ingest(inv("W/1"), "a.json")
    assert a.status == "approved"
    monkeypatch.setattr(pipeline, "_earlier_same_file", lambda doc: None)
    real = pipeline._key_holder
    calls = []

    def stale(doc, key, lock=False):
        calls.append(lock)
        return None if not lock else real(doc, key, lock)
    monkeypatch.setattr(pipeline, "_key_holder", stale)
    b = ingest(inv("W/1"), "b.json")
    assert b.status == "duplicate" and b.dedupe_key is None
    assert True in calls
    assert db.session.get(Document, a.id).status == "approved"


def test_allow_duplicate_releases_key_and_reprocess_keeps_single_live(supplier):
    a = ingest(inv("AD/1"), "a.json")
    b = ingest(inv("AD/1"), "b.json")
    resolve(b, "allow_duplicate", {}, True, "qa")
    assert b.status == "approved" and b.dedupe_key is None and a.dedupe_key
    process(a)
    process(b)
    db.session.commit()
    assert a.status == "approved" and b.status == "approved"  # jawna zgoda operatora


def test_reject_releases_key_and_restore_reclaims(supplier):
    a = ingest(inv("RK/1"), "a.json")
    key = a.dedupe_key
    b = ingest(inv("RK/1"), "b.json")
    resolve(a, "reject", {}, True, "qa")
    assert a.dedupe_key is None
    b = db.session.get(Document, b.id)
    assert b.status == "approved" and b.dedupe_key == key
    from app.services.negotiation import restore
    restore(a, "qa")
    assert db.session.get(Document, a.id).dedupe_key == key
    assert db.session.get(Document, b.id).status == "duplicate"


# ------------------------------------------------------------------ straż ręcznego odrzucenia w process() (BE-2)


def test_process_itself_keeps_manual_rejection(supplier):
    d = ingest(inv("PR/1"), "p.json")
    resolve(d, "reject", {}, True, "qa")
    process(d)
    db.session.commit()
    d = db.session.get(Document, d.id)
    assert d.status == "rejected" and d.rejected_by == "qa"


def test_process_reprocesses_automatic_rejection(supplier, app):
    app.config["MAX_LINES"] = 1
    d = ingest(inv("PR/2", [line(sku="A1", ean=None), line(sku="A2", ean=None)]), "p.json")
    assert d.status == "rejected" and d.rejected_by is None
    app.config["MAX_LINES"] = 100
    process(d)
    assert d.status != "rejected"


# ------------------------------------------------------------------ BE-9 / BE-10: plik i rekord


def test_missing_file_on_reprocess_is_readable_issue(supplier, client):
    d = ingest(inv("F/1"), "f.json")
    d.api_key_id = 1
    db.session.commit()
    (get_storage().base / d.sha256).unlink()
    r = client.post(f"/api/v1/documents/{d.id}/reprocess", headers=KEY)
    assert r.status_code == 200
    js = r.get_json()
    assert js["status"] == "needs_review" and js["issues"][0]["code"] == "file_missing"


def test_unexpected_exception_saves_document_with_internal_error(supplier, client, monkeypatch):
    def boom(*a, **k):
        raise KeyError("zepsuta reguła")
    monkeypatch.setattr(pipeline, "apply_template", boom)
    r = client.post("/api/v1/documents", headers={**KEY, "X-Filename": "x.json"}, data=inv("X/1"))
    assert r.status_code == 201
    js = r.get_json()
    assert js["status"] == "needs_review" and js["issues"][0]["code"] == "internal_error"
    assert db.session.get(Document, js["id"]) is not None


def test_failed_ingest_removes_orphan_file(seeded, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def broken(*a, **k):
        raise OperationalError("INSERT", {}, Exception("baza niedostępna"))
    monkeypatch.setattr(pipeline, "audit", broken)
    data = inv("OR/1")
    with pytest.raises(OperationalError):
        ingest(data, "o.json")
    import hashlib
    assert not (get_storage().base / hashlib.sha256(data).hexdigest()).exists()
    assert Document.query.count() == 0


def test_storage_dir_must_be_writable(tmp_path):
    from app import create_app
    blocker = tmp_path / "plik"
    blocker.write_text("x")
    with pytest.raises(RuntimeError, match="STORAGE_DIR"):
        create_app({"TESTING": True, "SECRET_KEY": "t", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                    "STORAGE_DIR": str(blocker / "storage")})


# ------------------------------------------------------------------ BE-15: atomowy reset demo


def test_reset_demo_is_atomic(supplier, monkeypatch):
    from app.services import seed
    ingest(inv("RD/1"), "r.json")
    n_docs = Document.query.count()

    def boom(**kw):
        raise RuntimeError("awaria w trakcie seeda")
    monkeypatch.setattr(seed, "seed_demo", boom)
    with pytest.raises(RuntimeError):
        seed.reset_demo()
    assert Document.query.count() == n_docs
    assert Unit.query.count() > 0 and Supplier.query.count() > 0


def test_reset_demo_removes_storage_files(supplier):
    from app.services.seed import reset_demo
    d = ingest(inv("RD/2"), "r.json")
    path = get_storage().base / d.sha256
    assert path.exists()
    reset_demo("qa")
    assert not path.exists()
    assert Document.query.count() == 0 and Product.query.count() > 0
    assert AuditLog.query.filter_by(action="reset", entity="demo").count() == 1


# ------------------------------------------------------------------ BE-17: unikaty w DB


def test_supplier_tax_id_unique_in_db(seeded):
    db.session.add_all([Supplier(name="A", tax_id="PL5550001111"), Supplier(name="B", tax_id="PL5550001111")])
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_conversion_scope_unique_in_db_with_nulls(seeded):
    kg, szt = Unit.query.filter_by(code="kg").one(), Unit.query.filter_by(code="szt").one()
    db.session.add(UnitConversion(from_unit_id=kg.id, to_unit_id=szt.id, factor=2))
    db.session.flush()
    db.session.add(UnitConversion(from_unit_id=kg.id, to_unit_id=szt.id, factor=3))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_global_alias_unique_in_db(seeded):
    szt = Unit.query.filter_by(code="szt").one()
    db.session.add(UnitAlias(alias="pcs", unit_id=szt.id))
    db.session.flush()
    db.session.add(UnitAlias(alias="PCS ", unit_id=szt.id))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


@pytest.mark.parametrize("first,second", [
    ({"supplier_code": "ab-1"}, {"supplier_code": "AB-1"}),
    ({"supplier_gtin": "05909999000013"}, {"supplier_gtin": "05909999000013"}),
    ({"supplier_name_norm": "mąka"}, {"supplier_name_norm": "mąka"}),
])
def test_mapping_unique_in_db(supplier, first, second):
    p = Product.query.first()
    db.session.add(ProductMapping(supplier_id=supplier.id, product_id=p.id, **first))
    db.session.flush()
    db.session.add(ProductMapping(supplier_id=supplier.id, product_id=p.id, **second))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_mapping_code_and_gtin_only_rows_may_coexist(supplier):
    p = Product.query.first()
    db.session.add(ProductMapping(supplier_id=supplier.id, product_id=p.id, supplier_code="K1",
                                  supplier_gtin="05909999000013"))
    db.session.add(ProductMapping(supplier_id=supplier.id, product_id=p.id, supplier_gtin="05909999000013"))
    db.session.flush()


def test_race_on_create_supplier_retries_and_reuses(seeded, monkeypatch):
    """Równoległe „Utwórz dostawcę” z tym samym NIP: drugi dostaje IntegrityError i ponawia → podpina."""
    from app.services import negotiation
    d = ingest(inv("RS/1", tax=OTHER_TAX), "r.json")
    db.session.add(Supplier(name="Równoległy", tax_id=OTHER_TAX))
    db.session.commit()
    real, calls = negotiation.find_supplier_by_tax_id, []

    def stale(tax_id, exclude_id=None):
        calls.append(1)
        return None if len(calls) == 1 else real(tax_id, exclude_id)
    monkeypatch.setattr(negotiation, "find_supplier_by_tax_id", stale)
    resolve(d, "create_supplier", {"name": "Nowy", "tax_id": OTHER_TAX}, True, "qa")
    assert Supplier.query.filter_by(tax_id=OTHER_TAX).count() == 1
    assert d.supplier.name == "Równoległy"


def test_api_list_index_exists(app):
    idx = {i["name"]: i["column_names"] for i in sa_inspect(db.engine).get_indexes("documents")}
    assert ["api_key_id", "status", "created_at"] in idx.values()


# ------------------------------------------------------------------ BE-7: wyścigi i blokada optymistyczna


def test_resolve_retries_on_integrity_error(supplier, monkeypatch):
    from app.services import negotiation
    d = ingest(inv("RT/1", [line(sku="Q1", ean=None, name="Nowy towar Q")]), "q.json")
    real, calls = negotiation.a_create_product, []

    def flaky(doc, data, remember, user):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, Exception("Duplicate entry 'TOW-0012'"))
        return real(doc, data, remember, user)
    monkeypatch.setitem(negotiation.ACTIONS, "create_product", flaky)
    resolve(d, "create_product", {"code": "TOW-0012", "name": "Nowy towar Q", "line_no": "1"}, True, "qa")
    assert len(calls) == 2 and Product.query.filter_by(name="Nowy towar Q").count() == 1


def test_resolve_gives_message_when_conflict_persists(supplier, monkeypatch):
    from app.services import negotiation
    d = ingest(inv("RT/2", [line(sku="Q2", ean=None, name="Inny")]), "q.json")

    def always(doc, data, remember, user):
        raise IntegrityError("INSERT", {}, Exception("dup"))
    monkeypatch.setitem(negotiation.ACTIONS, "create_product", always)
    with pytest.raises(NegotiationError, match="równocze"):
        resolve(d, "create_product", {"code": "X", "name": "Inny", "line_no": "1"}, True, "qa")


def test_new_version_number_from_db(supplier):
    from app.services.templates import new_version
    tpl = supplier.templates[0]
    n = max(v.version for v in tpl.versions)
    db.session.add(TemplateVersion(template_id=tpl.id, version=n + 1, rules={"line_path": "x"}))
    db.session.flush()
    db.session.expire(tpl, ["versions"])
    tv = new_version(tpl, {"line_path": "y"}, "qa", "test")
    assert tv.version == n + 2


def test_editor_save_with_stale_base_version_is_conflict(auth_client):
    d = ingest(inv("ED/1", tax=OTHER_TAX), "e.json")
    resolve(d, "create_supplier", {"name": "Edytor", "tax_id": OTHER_TAX}, True, "qa")
    base = d.template.active_version_id
    rules = d.template.active_version.rules
    r1 = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": rules, "base_version_id": base})
    assert r1.status_code == 200
    r2 = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": rules, "base_version_id": base})
    assert r2.status_code == 409 and "zmienił" in r2.get_json()["error"]
    html = auth_client.get(f"/szablony/dokument/{d.id}/edytor").get_data(as_text=True)
    assert "baseVersionId" in html


# ------------------------------------------------------------------ BE-8 / EDGE-18: długości


def test_crud_too_long_value_is_validation_error(auth_client):
    r = auth_client.post("/dostawcy/nowy", data={"name": "D" * 300, "tax_id": ""}, follow_redirects=True)
    assert "maks. 255" in r.get_data(as_text=True)
    assert Supplier.query.filter(Supplier.name.like("DDD%")).count() == 0


def test_template_name_fits_column_for_long_supplier_name(seeded):
    d = ingest(inv("L/1", tax=OTHER_TAX), "l.json")
    resolve(d, "create_supplier", {"name": "S" * 300, "tax_id": OTHER_TAX}, True, "qa")
    t = Template.query.filter_by(supplier_id=d.supplier_id).one()
    assert len(t.name) <= 255 and len(d.supplier.name) <= 255


def test_negotiation_too_long_codes_are_errors(supplier):
    d = ingest(inv("L/2", [line(sku="K" * 80, ean=None, name="Długi kod")]), "l.json")
    with pytest.raises(NegotiationError, match="64"):
        resolve(d, "map_product", {"product_code": "TOW-0001", "line_no": "1"}, True, "qa")
    with pytest.raises(NegotiationError, match="64"):
        resolve(d, "create_product", {"code": "C" * 80, "name": "x", "line_no": "1"}, False, "qa")
    with pytest.raises(NegotiationError, match="64"):
        resolve(d, "map_unit", {"alias": "u" * 80, "unit": "szt"}, True, "qa")


def test_api_key_name_too_long(auth_client):
    r = auth_client.post("/klucze-api/nowy", data={"name": "K" * 300}, follow_redirects=True)
    assert "maks. 255" in r.get_data(as_text=True)
    assert ApiKey.query.filter(ApiKey.name.like("KKK%")).count() == 0


# ------------------------------------------------------------------ BE-14: kody używane w dokumentach


def test_product_used_in_document_cannot_be_deleted_or_recoded(supplier, auth_client):
    d = ingest(inv("P/1"), "p.json")
    code = d.result["lines"][0]["product_index"]
    p = Product.query.filter_by(code=code).one()
    r = auth_client.post(f"/towary/{p.id}/usun", follow_redirects=True)
    assert "dokument" in r.get_data(as_text=True) and db.session.get(Product, p.id)
    r = auth_client.post(f"/towary/{p.id}/edycja", data={"code": "NOWY-1", "name": p.name, "gtin": p.gtin or "",
                                                         "unit_id": p.unit_id or ""}, follow_redirects=True)
    assert "dokument" in r.get_data(as_text=True)
    assert db.session.get(Product, p.id).code == code


def test_unit_used_in_document_cannot_be_deleted_or_recoded(seeded, auth_client):
    u = Unit(code="beczka", name="beczka", is_base=True)
    db.session.add(u)
    db.session.flush()
    doc = Document(sha256="1" * 64, status="approved", result={"lines": [{"line_no": 1, "unit": "beczka"}]})
    db.session.add(doc)
    db.session.commit()
    r = auth_client.post(f"/jednostki/{u.id}/usun", follow_redirects=True)
    assert "dokument" in r.get_data(as_text=True) and db.session.get(Unit, u.id)
    r = auth_client.post(f"/jednostki/{u.id}/edycja", data={"code": "baryłka", "name": "x", "is_base": "1"},
                         follow_redirects=True)
    assert "dokument" in r.get_data(as_text=True) and db.session.get(Unit, u.id).code == "beczka"


def test_unused_product_can_be_recoded(seeded, auth_client):
    p = Product.query.filter_by(code="TOW-0010").one()
    auth_client.post(f"/towary/{p.id}/edycja", data={"code": "TOW-9999", "name": p.name, "gtin": "", "unit_id": ""})
    assert db.session.get(Product, p.id).code == "TOW-9999"


# ------------------------------------------------------------------ BE-18: klucz API z dokumentami


def test_api_key_with_documents_cannot_be_deleted(seeded, auth_client):
    key = ApiKey.query.first()
    d = Document(sha256="2" * 64, status="approved", api_key_id=key.id)
    db.session.add(d)
    db.session.commit()
    r = auth_client.post(f"/klucze-api/{key.id}/usun", follow_redirects=True)
    assert "dezaktywuj" in r.get_data(as_text=True)
    assert db.session.get(ApiKey, key.id) is not None
    assert db.session.get(Document, d.id).api_key_id == key.id


def test_api_key_without_documents_can_be_deleted(seeded, auth_client):
    from app.services.apikeys import create_key
    key, _ = create_key("Do usunięcia")
    db.session.commit()
    auth_client.post(f"/klucze-api/{key.id}/usun")
    assert db.session.get(ApiKey, key.id) is None


# ------------------------------------------------------------------ izolacja zakresów duplikatów (klucze API)


def _key(name):
    from app.services.apikeys import create_key
    key, plain = create_key(name)
    db.session.commit()
    return key, {"X-API-Key": plain}


def test_same_invoice_from_two_api_keys_both_approved_and_isolated(supplier, client):
    from app.services.negotiation import restore
    _, ha = _key("System A")
    _, hb = _key("System B")
    ra = client.post("/api/v1/documents", headers={**ha, "X-Filename": "x.json"}, data=inv("ISO/1")).get_json()
    rb = client.post("/api/v1/documents", headers={**hb, "X-Filename": "x.json"}, data=inv("ISO/1")).get_json()
    assert ra["status"] == "approved" and rb["status"] == "approved"
    # kopia w zakresie A — duplikat oryginału A, nie B
    ra2 = client.post("/api/v1/documents", headers={**ha, "X-Filename": "x.json"}, data=inv("ISO/1")).get_json()
    assert ra2["status"] == "duplicate" and ra2["issues"][0]["source_value"] == str(ra["id"])
    # panel („web”) to osobny zakres
    web = ingest(inv("ISO/1"), "w.json")
    assert web.status == "approved"
    b_status = lambda: db.session.get(Document, rb["id"]).status  # noqa: E731
    a = db.session.get(Document, ra["id"])
    assert client.post(f"/api/v1/documents/{a.id}/reprocess", headers=ha).status_code == 200
    assert b_status() == "approved"
    resolve(a, "reject", {}, True, "qa")
    assert b_status() == "approved"
    assert db.session.get(Document, ra2["id"]).status == "approved"  # zwolniony duplikat w zakresie A
    restore(db.session.get(Document, a.id), "qa")
    assert db.session.get(Document, a.id).status == "approved"
    assert db.session.get(Document, ra2["id"]).status == "duplicate"
    assert b_status() == "approved" and db.session.get(Document, web.id).status == "approved"


def test_later_copy_in_other_scope_not_demoted_by_earlier_reprocess(seeded):
    """Wcześniejszy dokument klucza A przetworzony po zatwierdzeniu kopii klucza B nie degraduje B."""
    from app.services.apikeys import create_key
    ka, _ = create_key("A")
    kb, _ = create_key("B")
    db.session.commit()
    a = ingest(inv("ISO/2", tax=OTHER_TAX), "a.json", source="api", api_key_id=ka.id)
    b = ingest(inv("ISO/2", tax=OTHER_TAX) + b"\n", "b.json", source="api", api_key_id=kb.id)
    resolve(b, "create_supplier", {"name": "Izolacja", "tax_id": OTHER_TAX}, True, "qa")
    assert b.status == "approved"
    process(a)
    db.session.commit()
    assert db.session.get(Document, a.id).status == "approved"
    assert db.session.get(Document, b.id).status == "approved"


@pytest.mark.skipif(not __import__("os").environ.get("TEST_MARIADB_URL"),
                    reason="wyścig na prawdziwej MariaDB — ustaw TEST_MARIADB_URL (pusta baza testowa)")
def test_parallel_ingest_race_on_mariadb(tmp_path):
    """Równoległe przyjęcie tej samej faktury (wątki, osobne transakcje, REPEATABLE READ): jeden żywy."""
    import os
    import threading

    from app import create_app
    url = os.environ["TEST_MARIADB_URL"]
    app = create_app({"TESTING": True, "SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": url,
                      "STORAGE_DIR": str(tmp_path / "s"), "DEMO_MODE": True, "ADMIN_PASSWORD": ""})
    with app.app_context():
        db.drop_all()
        db.create_all()
        from app.services.seed import seed_base, seed_demo
        seed_base()
        seed_demo()
        d = ingest(inv("T/1"), "t1.json")
        resolve(d, "create_supplier", {"name": "Testowy Dostawca", "tax_id": TAX}, True, "qa")
    n = 4
    barrier = threading.Barrier(n)
    real = pipeline._resolve_duplicate

    def gated(doc, invoice):  # wszyscy po odczytach, przed zapisem klucza — maksymalne nakładanie
        try:
            barrier.wait(timeout=20)
        except threading.BrokenBarrierError:
            pass
        return real(doc, invoice)
    statuses = []

    def worker(i):
        with app.app_context():
            try:
                statuses.append(ingest(inv("RACE/1") + b" " * (i + 1), f"r{i}.json").status)
            finally:
                db.session.remove()
    pipeline._resolve_duplicate = gated
    try:
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        pipeline._resolve_duplicate = real
    assert sorted(statuses) == ["approved"] + ["duplicate"] * (n - 1)
    with app.app_context():
        db.drop_all()
