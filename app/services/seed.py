import click
from flask import current_app

from app.engine.keys import alias_key
from app.extensions import db
from app.models import (
    ApiKey,
    AuditLog,
    Document,
    Product,
    ProductMapping,
    Supplier,
    Template,
    TemplateVersion,
    Unit,
    UnitAlias,
    UnitConversion,
    User,
    WebhookDelivery,
)
from app.services.accounts import PLACEHOLDER_PASSWORDS, password_problem  # noqa: F401 (PLACEHOLDER_PASSWORDS — zgodność)
from app.services.apikeys import create_key, hash_key
from app.services.audit import audit
from app.services.storage import get_storage

BASE_UNITS = [
    ("szt", "sztuka", True), ("kg", "kilogram", True), ("l", "litr", True), ("m", "metr", True),
    ("karton", "karton", False), ("worek", "worek", False), ("opak", "opakowanie", False),
]
GLOBAL_ALIASES = [("szt.", "szt"), ("sztuk", "szt"), ("kilogram", "kg"), ("litr", "l")]
DEMO_KEY_NAME = "Klucz demo"
# klucz demo z publicznego .env.example (albo zbyt krótki) nie może stać się pełnoprawnym kluczem API
DEMO_KEY_PLACEHOLDERS = {"xp_demo_klucz_do_testow"}
DEMO_KEY_MIN_LENGTH = 24
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


def seed_base(commit: bool = True) -> None:
    units = {u.code: u for u in Unit.query.all()}
    for code, name, is_base in BASE_UNITS:
        if code not in units:
            units[code] = Unit(code=code, name=name, is_base=is_base)
            db.session.add(units[code])
    db.session.flush()
    for alias, code in GLOBAL_ALIASES:
        if not UnitAlias.query.filter_by(alias_key=alias_key(None, alias)).first():
            db.session.add(UnitAlias(alias=alias, unit_id=units[code].id, supplier_id=None))
    cfg = current_app.config
    admin_email = (cfg.get("ADMIN_EMAIL") or "").strip().lower()
    pw = cfg.get("ADMIN_PASSWORD") or ""
    weak = password_problem(pw) is not None
    if pw and weak and not cfg.get("TESTING"):
        click.echo("OSTRZEŻENIE: ADMIN_PASSWORD jest hasłem przykładowym lub krótszym niż 10 znaków. "
                   "Konto administratora NIE zostało utworzone. Ustaw własne hasło w .env.", err=True)
    elif pw and admin_email and not User.query.filter_by(email=admin_email).first():
        u = User(email=admin_email, role="admin")
        u.set_password(pw)
        db.session.add(u)
    demo_key = cfg.get("DEMO_API_KEY") or ""
    weak_key = demo_key in DEMO_KEY_PLACEHOLDERS or len(demo_key) < DEMO_KEY_MIN_LENGTH
    if cfg.get("DEMO_MODE") and demo_key and weak_key and not cfg.get("TESTING"):
        click.echo(f"OSTRZEŻENIE: DEMO_API_KEY jest wartością przykładową lub krótszą niż {DEMO_KEY_MIN_LENGTH} znaków "
                   "— klucz demo NIE został utworzony. Wygeneruj: "
                   "python -c \"import secrets;print('xp_'+secrets.token_urlsafe(24))\"", err=True)
        demo_key = ""
    demo_on = bool(cfg.get("DEMO_MODE") and demo_key)
    current_hash = hash_key(demo_key) if demo_on else None
    for k in ApiKey.query.filter_by(name=DEMO_KEY_NAME).all():
        k.active = bool(demo_on and k.key_hash == current_hash)
    if demo_on and not ApiKey.query.filter_by(key_hash=current_hash).first():
        create_key(DEMO_KEY_NAME, demo_key)
    if commit:
        db.session.commit()
    else:
        db.session.flush()


def seed_demo(commit: bool = True) -> None:
    units = {u.code: u for u in Unit.query.all()}
    for code, name, gtin, unit in DEMO_PRODUCTS:
        if not Product.query.filter_by(code=code).first():
            db.session.add(Product(code=code, name=name, gtin=gtin, unit_id=units[unit].id))
    if commit:
        db.session.commit()
    else:
        db.session.flush()


def reset_demo(user: str | None = None) -> None:
    """Czyści dane i przywraca stan demo w JEDNEJ transakcji (błąd = rollback, dane nietknięte); pliki
    dokumentów usuwane z magazynu dopiero po udanym commicie (BE-15)."""
    if not current_app.config.get("DEMO_MODE"):
        raise RuntimeError("reset-demo jest dozwolone tylko przy DEMO_MODE=1 (usuwa wszystkie dane).")
    try:
        shas = {sha for (sha,) in db.session.query(Document.sha256).distinct()}
        db.session.query(Document).update({Document.template_version_id: None, Document.template_id: None,
                                           Document.corrects_document_id: None, Document.dedupe_key: None})
        # dostawy webhooków przed dokumentami: document_id bez kaskady blokowałby DELETE dokumentów
        for model in (WebhookDelivery, Document, ProductMapping, UnitConversion, TemplateVersion, Template, Product,
                      AuditLog):
            db.session.query(model).delete()
        db.session.query(UnitAlias).filter(UnitAlias.supplier_id.isnot(None)).delete()
        db.session.query(Supplier).delete()
        db.session.flush()
        seed_base(commit=False)
        seed_demo(commit=False)
        audit("reset", "demo", None, {"documents_files": len(shas)}, user)
        db.session.commit()
    except BaseException:
        db.session.rollback()
        raise
    storage = get_storage()
    for sha in shas:  # po commicie — żaden dokument już ich nie wskazuje
        try:
            storage.delete(sha)
        except (OSError, ValueError):
            current_app.logger.warning("reset demo: nie udało się usunąć pliku %s", sha)
