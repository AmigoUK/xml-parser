from decimal import Decimal

from app.extensions import db
from app.models import (ApiKey, AuditLog, Product, ProductMapping, Supplier, Template, Unit, UnitAlias,
                        UnitConversion, User)
from app.services.apikeys import create_key, verify_key
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.seed import reset_demo, seed_base, seed_demo
from app.services.storage import get_storage
from app.services.templates import active_rule_sets, create_template, new_version


def test_storage_roundtrip(app):
    st = get_storage()
    sha = st.save(b"<a/>")
    assert len(sha) == 64 and st.load(sha) == b"<a/>"
    assert st.save(b"<a/>") == sha


def test_seed_base_idempotent(app):
    seed_base()
    seed_base()
    assert Unit.query.filter_by(code="szt").one().is_base
    assert not Unit.query.filter_by(code="karton").one().is_base
    assert User.query.count() == 1 and User.query.one().check_password("haslo123")
    assert verify_key("xp_test_demo_key") is not None


def test_db_lookups(app):
    seed_base()
    seed_demo()
    s = Supplier(name="Alfa", tax_id="PL9990000011")
    db.session.add(s)
    db.session.flush()
    szt = Unit.query.filter_by(code="szt").one()
    karton = Unit.query.filter_by(code="karton").one()
    db.session.add(UnitAlias(alias="pcs", unit_id=szt.id, supplier_id=s.id))
    db.session.add(UnitConversion(supplier_id=s.id, from_unit_id=karton.id, to_unit_id=szt.id, factor=Decimal("12")))
    p = Product.query.filter_by(code="TOW-0003").one()
    db.session.add(ProductMapping(supplier_id=s.id, supplier_code="A-300", product_id=p.id))
    db.session.commit()
    lk = DbLookups()
    assert lk.unit_for_alias("PCS", s.id) == "szt"
    assert lk.unit_for_alias("pcs", None) is None
    assert lk.unit_for_alias("Kg", None) == "kg"
    assert lk.is_base_unit("szt") and not lk.is_base_unit("karton")
    assert lk.conversion(s.id, None, "karton") == ("szt", Decimal("12"))
    assert lk.conversion(None, None, "karton") is None
    assert lk.product_for(s.id, "A-300", None) == "TOW-0003"
    assert lk.product_for(None, None, "05909999000013") == "TOW-0001"
    assert "karton" in lk.unit_codes()
    assert {"code": "TOW-0001", "name": "Posypka czekoladowa 1 kg", "gtin": "5909999000013"} in lk.products_brief()


def test_templates_versions(app):
    s = Supplier(name="Alfa", tax_id="PL1")
    db.session.add(s)
    db.session.flush()
    t = create_template(s, ["A/B"], "abc", "xml", {"line_path": "A"}, "admin")
    assert t.active_version.version == 1
    v2 = new_version(t, {"line_path": "B"}, "admin", "zmiana")
    db.session.commit()
    assert v2.version == 2 and t.active_version.rules == {"line_path": "B"}
    assert active_rule_sets() == [{"line_path": "B"}]


def test_api_keys_and_audit(app):
    key, plain = create_key("ERP")
    db.session.commit()
    assert plain.startswith("xp_") and key.prefix == plain[:10]
    assert verify_key(plain).id == key.id
    assert verify_key("xp_nope") is None
    key.active = False
    db.session.commit()
    assert verify_key(plain) is None
    audit("test", "api_key", key.id, {"a": 1}, user="admin")
    db.session.commit()
    assert AuditLog.query.one().payload == {"a": 1}


def test_reset_demo_clears_data(app):
    seed_base()
    db.session.add(Supplier(name="X"))
    db.session.commit()
    reset_demo()
    assert Supplier.query.count() == 0
    assert Product.query.filter_by(code="TOW-0001").count() == 1
    assert ApiKey.query.count() == 1


def test_conversion_factor_must_be_positive(app):
    import pytest
    seed_base()
    szt = Unit.query.filter_by(code="szt").one()
    karton = Unit.query.filter_by(code="karton").one()
    for bad in (Decimal("0"), Decimal("-2")):
        with pytest.raises(ValueError, match="większą od zera"):
            UnitConversion(from_unit_id=karton.id, to_unit_id=szt.id, factor=bad)
