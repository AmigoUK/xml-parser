from flask import current_app

from app.extensions import db
from app.models import (ApiKey, AuditLog, Document, Product, ProductMapping, Supplier, Template,
                        TemplateVersion, Unit, UnitAlias, UnitConversion, User)
from app.services.apikeys import create_key, hash_key

BASE_UNITS = [
    ("szt", "sztuka", True), ("kg", "kilogram", True), ("l", "litr", True), ("m", "metr", True),
    ("karton", "karton", False), ("worek", "worek", False), ("opak", "opakowanie", False),
]
GLOBAL_ALIASES = [("szt.", "szt"), ("sztuk", "szt"), ("kilogram", "kg"), ("litr", "l")]
DEMO_PRODUCTS = [
    ("TOW-0001", "Posypka czekoladowa 1 kg", "5909999000013", "szt"),
    ("TOW-0002", "Mak niebieski 500 g", "5909999000020", "szt"),
    ("TOW-0003", "Masa marcepanowa 5kg", None, "szt"),
    ("TOW-0004", "Mąka pszenna typ 450", "5909999000044", "kg"),
    ("TOW-0005", "Mąka żytnia typ 750", None, "kg"),
    ("TOW-0006", "Pudełko na tort 30x30 cm", "5909999000068", "szt"),
    ("TOW-0007", "Podkład pod tort 28cm", None, "szt"),
    ("TOW-0008", "Masło extra 82% 1kg", "5909999000082", "szt"),
    ("TOW-0009", "Śmietanka 30% 1l", "5909999000099", "szt"),
    ("TOW-0010", "Wanilia burbon (laski)", None, "szt"),
    ("TOW-0011", "Aromat rumowy 100ml", "4009999000028", "szt"),
]


def seed_base() -> None:
    units = {u.code: u for u in Unit.query.all()}
    for code, name, is_base in BASE_UNITS:
        if code not in units:
            units[code] = Unit(code=code, name=name, is_base=is_base)
            db.session.add(units[code])
    db.session.flush()
    for alias, code in GLOBAL_ALIASES:
        if not UnitAlias.query.filter_by(alias_norm=alias, supplier_id=None).first():
            db.session.add(UnitAlias(alias=alias, unit_id=units[code].id, supplier_id=None))
    cfg = current_app.config
    admin_email = (cfg.get("ADMIN_EMAIL") or "").strip().lower()
    if cfg.get("ADMIN_PASSWORD") and admin_email and not User.query.filter_by(email=admin_email).first():
        u = User(email=admin_email, role="admin")
        u.set_password(cfg["ADMIN_PASSWORD"])
        db.session.add(u)
    demo_key = cfg.get("DEMO_API_KEY")
    if cfg.get("DEMO_MODE") and demo_key and not ApiKey.query.filter_by(key_hash=hash_key(demo_key)).first():
        create_key("Klucz demo", demo_key)
    db.session.commit()


def seed_demo() -> None:
    units = {u.code: u for u in Unit.query.all()}
    for code, name, gtin, unit in DEMO_PRODUCTS:
        if not Product.query.filter_by(code=code).first():
            db.session.add(Product(code=code, name=name, gtin=gtin, unit_id=units[unit].id))
    db.session.commit()


def reset_demo() -> None:
    db.session.query(Document).update({Document.template_version_id: None, Document.template_id: None,
                                       Document.corrects_document_id: None})
    for model in (Document, ProductMapping, UnitConversion, TemplateVersion, Template, Product, AuditLog):
        db.session.query(model).delete()
    db.session.query(UnitAlias).filter(UnitAlias.supplier_id.isnot(None)).delete()
    db.session.query(Supplier).delete()
    db.session.commit()
    seed_base()
    seed_demo()
