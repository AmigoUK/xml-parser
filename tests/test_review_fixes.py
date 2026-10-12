"""Poprawki z końcowego przeglądu przed v0.2.0 (FR-2, FR-5, FR-6)."""
from decimal import Decimal

import pytest

from app.engine.suggest import conversion_guess
from app.engine.values import parse_factor
from app.extensions import db
from app.models import Template, Unit, UnitConversion
from app.services.negotiation import NegotiationError, parse_factor_input, resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes
from tests.test_negotiation_statuses import _crud_conv, inv, supplier  # noqa: F401 (fixture)


# ------------------------------------------------------------------ FR-2: przelicznik X.YYY
@pytest.mark.parametrize("raw,expected", [
    ("1.125", "1.125"), ("2.375", "2.375"), ("12.125", "12.125"), ("1.000", "1"),
    ("1,5", "1.5"), ("1,1250", "1.125"), ("0,125", "0.125"), ("1125", "1125"), ("1 125", "1125"),
    ("1e3", "1000"), ("1,000.5", "1000.5"), (12, "12"), (1.5, "1.5"),
])
def test_parse_factor_dot_is_always_decimal(raw, expected):
    assert parse_factor(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["1,125", "12,125", "1,000"])
def test_parse_factor_comma_three_digits_ambiguous_with_working_hint(raw):
    with pytest.raises(ValueError) as exc:
        parse_factor(raw)
    msg = str(exc.value)
    assert "iejednoznaczn" in msg
    dotted, plain = raw.replace(",", "."), raw.replace(",", "")
    assert dotted in msg and plain in msg
    # obie podsuwane formy są akceptowane
    assert parse_factor(dotted) and parse_factor(plain)


@pytest.mark.parametrize("raw", ["0", "-1", "0.000", "1.234.567", "abc", "", None, True])
def test_parse_factor_invalid(raw):
    with pytest.raises(ValueError):
        parse_factor(raw)


def test_negotiation_wrapper_uses_same_rules():
    assert parse_factor_input("1.125") == Decimal("1.125")
    with pytest.raises(ValueError, match="1.125"):
        parse_factor_input("1,125")


@pytest.mark.parametrize("name", ["Ser żółty 1125 g", "Olej 1,125 l", "Mąka 2.375 kg", "Woda 500 ml"])
def test_conversion_guess_is_accepted_by_parser(name):
    g = conversion_guess(name, "szt")
    assert g["factor"]
    parse_factor(g["factor"])  # podpowiedź systemu nigdy nie jest odrzucana


def test_conversion_guess_1125_g(seeded):
    assert conversion_guess("Ser żółty 1125 g", "szt")["factor"] == "1.125"


def test_negotiation_accepts_suggested_factor(supplier):  # noqa: F811
    d = ingest(inv("FR2/1"), "fr2.json")
    resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": "1.125"}, True, "qa")
    assert UnitConversion.query.one().factor == Decimal("1.125")


def test_negotiation_ambiguous_comma_message(supplier):  # noqa: F811
    d = ingest(inv("FR2/2"), "fr2.json")
    with pytest.raises(NegotiationError, match=r"1\.125.*1125"):
        resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": "1,125"}, True, "qa")
    assert UnitConversion.query.count() == 0


def test_crud_conversion_accepts_dot_decimal(auth_client):
    html = _crud_conv(auth_client, "1,125").get_data(as_text=True)
    assert "1.125" in html and "1125" in html
    assert UnitConversion.query.count() == 0
    _crud_conv(auth_client, "1.125")
    assert UnitConversion.query.one().factor == Decimal("1.125")


def _editor_save(auth_client, transforms):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    rules = Template.query.one().active_version.rules
    lines = {**rules["lines"], "qty": {"path": rules["lines"]["qty"]["path"], "transforms": transforms}}
    return d, auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": {**rules, "lines": lines}})


def test_editor_convert_dot_decimal(auth_client):
    _, r = _editor_save(auth_client, [{"convert": "1.125"}])
    assert r.status_code == 200, r.get_data(as_text=True)


def test_editor_convert_comma_three_digits_rejected_with_hint(auth_client):
    _, r = _editor_save(auth_client, [{"convert": "1,125"}])
    assert r.status_code == 400
    assert "1125" in r.get_data(as_text=True)


# ------------------------------------------------------------------ FR-5: blokada optymistyczna edytora
@pytest.fixture
def file_app(tmp_path):
    """Aplikacja na pliku SQLite — drugie połączenie widzi tylko zatwierdzone dane (jak drugi operator)."""
    from app import create_app
    from app.services.seed import seed_base, seed_demo
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/r.db",
                      "STORAGE_DIR": str(tmp_path / "s"), "WTF_CSRF_ENABLED": False, "DEMO_MODE": True,
                      "ADMIN_EMAIL": "admin@example.com", "ADMIN_PASSWORD": "haslo12345"})
    with app.app_context():
        db.create_all()
        seed_base()
        seed_demo()
        yield app
        db.session.remove()
        db.drop_all()


def _other_operator_saves(tid, rules):
    from sqlalchemy.orm import Session

    from app.models import TemplateVersion
    with Session(db.engine) as s2:
        t = s2.get(Template, tid)
        last = max(v.version for v in t.versions)
        v = TemplateVersion(template_id=tid, version=last + 1, rules=dict(rules), author="operator-A",
                            comment="praca A")
        s2.add(v)
        s2.flush()
        t.active_version_id = v.id
        s2.commit()


def _race_setup(file_app):
    from tests.test_learning import resolve_with_top_suggestions
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve_with_top_suggestions(d)
    t = db.session.get(Template, d.template_id)
    return d.id, t.id, t.active_version_id, t.active_version.rules


def _login(app):
    c = app.test_client()
    c.post("/login", data={"email": "admin@example.com", "password": "haslo12345"})
    return c


def test_editor_conflict_detected_inside_commit(file_app, monkeypatch):
    import app.web.templates_views as tv
    doc_id, tid, base, rules = _race_setup(file_app)
    orig = tv.commit_with_retry

    def racing(fn, *a, **kw):  # drugi operator zatwierdza wersję po kontroli wstępnej, przed zapisem
        _other_operator_saves(tid, rules)
        return orig(fn, *a, **kw)
    monkeypatch.setattr(tv, "commit_with_retry", racing)
    r = _login(file_app).post(f"/szablony/dokument/{doc_id}/zapisz",
                              json={"rules": rules, "comment": "praca B", "base_version_id": base})
    assert r.status_code == 409, r.get_data(as_text=True)
    db.session.expire_all()
    t = db.session.get(Template, tid)
    assert t.active_version.comment == "praca A"
    assert [v.comment for v in t.versions].count("praca B") == 0


def test_editor_conflict_rechecked_on_retry(file_app, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    import app.web.templates_views as tv
    doc_id, tid, base, rules = _race_setup(file_app)
    orig = tv.commit_with_retry
    calls = {"n": 0}

    def wrapped(fn, *a, **kw):
        def attempt():
            calls["n"] += 1
            if calls["n"] == 1:  # pierwsza próba: wyścig o numer wersji → IntegrityError, w tym czasie A zapisał
                db.session.rollback()
                _other_operator_saves(tid, rules)
                raise IntegrityError("INSERT", {}, Exception("uq_template_version"))
            return fn()
        return orig(attempt, *a, **kw)
    monkeypatch.setattr(tv, "commit_with_retry", wrapped)
    r = _login(file_app).post(f"/szablony/dokument/{doc_id}/zapisz",
                              json={"rules": rules, "comment": "praca B", "base_version_id": base})
    assert r.status_code == 409, r.get_data(as_text=True)
    assert calls["n"] == 2
    db.session.expire_all()
    assert db.session.get(Template, tid).active_version.comment == "praca A"


def test_editor_save_with_current_base_still_ok(file_app):
    doc_id, tid, base, rules = _race_setup(file_app)
    r = _login(file_app).post(f"/szablony/dokument/{doc_id}/zapisz",
                              json={"rules": rules, "comment": "praca B", "base_version_id": base})
    assert r.status_code == 200, r.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Template, tid).active_version.comment == "praca B"


# ------------------------------------------------------------------ FR-6: jedna normalizacja klucza mapowania
def _mapping_setup(stored_code=None, stored_name=None, stored_gtin=None):
    from app.models import Product, ProductMapping, Supplier
    s = Supplier(name="Fikcyjny FR6", tax_id="PL1111111111")
    db.session.add(s)
    szt = Unit.query.filter_by(code="szt").one()
    p1 = Product(code="TOW-A", name="A", unit_id=szt.id)
    p2 = Product(code="TOW-B", name="B", unit_id=szt.id)
    db.session.add_all([p1, p2])
    db.session.flush()
    db.session.add(ProductMapping(supplier_id=s.id, supplier_code=stored_code, supplier_gtin=stored_gtin,
                                  supplier_name_norm=stored_name, product_id=p1.id))
    db.session.commit()
    return s


def _doc_with_line(s, code=None, name="Towar", gtin=None):
    from app.models import Document
    d = Document(filename="f.json", sha256="0" * 64, fmt="json", status="needs_review", supplier_id=s.id,
                 result={"lines": [{"line_no": 1, "supplier_code": code, "gtin": gtin, "name": name}]}, issues=[])
    db.session.add(d)
    db.session.commit()
    return d


@pytest.mark.parametrize("stored,line", [("AB  1", "AB 1"), ("ABC", "abc"), ("Kód-1", "KOD-1"), (" X1 ", "X1")])
def test_lookup_finds_mapping_with_same_key(seeded, stored, line):
    from app.services.lookups_db import DbLookups
    s = _mapping_setup(stored_code=stored)
    assert DbLookups().product_for(s.id, line, None) == "TOW-A"


@pytest.mark.parametrize("stored,line", [("AB  1", "AB 1"), ("ABC", "abc")])
def test_remember_updates_existing_mapping_instead_of_conflict(seeded, stored, line, monkeypatch):
    import app.services.negotiation as neg
    from app.models import ProductMapping
    monkeypatch.setattr(neg, "process", lambda doc, *a, **k: None)
    s = _mapping_setup(stored_code=stored)
    d = _doc_with_line(s, code=line)
    resolve(d, "map_product", {"line_no": 1, "product_code": "TOW-B"}, True, "t")
    rows = ProductMapping.query.all()
    assert len(rows) == 1 and rows[0].product.code == "TOW-B"


def test_name_mapping_matches_by_key(seeded, monkeypatch):
    import app.services.negotiation as neg
    from app.models import ProductMapping
    from app.services.lookups_db import DbLookups
    monkeypatch.setattr(neg, "process", lambda doc, *a, **k: None)
    s = _mapping_setup(stored_name="ser żółty  gouda")
    assert DbLookups().product_for(s.id, None, None, "Ser Zołty Gouda") == "TOW-A"
    d = _doc_with_line(s, code=None, name="SER ŻÓŁTY GOUDA")
    resolve(d, "map_product", {"line_no": 1, "product_code": "TOW-B"}, True, "t")
    assert ProductMapping.query.count() == 1


def test_gtin_mapping_matches_padded(seeded, monkeypatch):
    import app.services.negotiation as neg
    from app.models import ProductMapping
    from app.services.lookups_db import DbLookups
    monkeypatch.setattr(neg, "process", lambda doc, *a, **k: None)
    s = _mapping_setup(stored_gtin="05901234123457")
    assert DbLookups().product_for(s.id, None, "5901234123457") == "TOW-A"
    d = _doc_with_line(s, code=None, gtin="5901234123457")
    resolve(d, "map_product", {"line_no": 1, "product_code": "TOW-B"}, True, "t")
    assert ProductMapping.query.count() == 1


# ---------------------------------------------------- FR-9: alias jednostki po kluczu niezależnym od kolacji
def test_alias_lookup_and_remember_use_alias_key(seeded, monkeypatch):
    import app.services.negotiation as neg
    from app.models import Supplier, UnitAlias
    from app.services.lookups_db import DbLookups
    monkeypatch.setattr(neg, "process", lambda doc, *a, **k: None)
    s = Supplier(name="Fikcyjny FR9", tax_id="PL2222222222")
    db.session.add(s)
    db.session.flush()
    kg, szt = Unit.query.filter_by(code="kg").one(), Unit.query.filter_by(code="szt").one()
    db.session.add(UnitAlias(alias="Opakowánie", unit_id=kg.id, supplier_id=s.id))
    db.session.commit()
    assert DbLookups().unit_for_alias("opakowanie", s.id) == "kg"
    d = _doc_with_line(s)
    resolve(d, "map_unit", {"alias": "OPAKOWANIE", "unit": "szt"}, True, "t")
    rows = UnitAlias.query.filter_by(supplier_id=s.id).all()
    assert len(rows) == 1 and rows[0].unit_id == szt.id and rows[0].alias_key


def test_global_alias_duplicate_rejected_by_db(seeded):
    from sqlalchemy.exc import IntegrityError

    from app.models import UnitAlias
    szt = Unit.query.filter_by(code="szt").one()
    db.session.add(UnitAlias(alias="Sztuka-X", unit_id=szt.id, supplier_id=None))
    db.session.commit()
    db.session.add(UnitAlias(alias="sztuka-x ", unit_id=szt.id, supplier_id=None))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
