from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask_login import UserMixin
from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

STATUS_RECEIVED = "received"
STATUS_APPROVED = "approved"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_DUPLICATE = "duplicate"
STATUS_REJECTED = "rejected"
STATUS_LABELS = {
    STATUS_RECEIVED: "Przyjęta",
    STATUS_APPROVED: "Zatwierdzona",
    STATUS_NEEDS_REVIEW: "Do wyjaśnienia",
    STATUS_DUPLICATE: "Duplikat",
    STATUS_REJECTED: "Odrzucona",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    tax_id = db.Column(db.String(64), index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)


class Template(db.Model):
    __tablename__ = "templates"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), index=True)
    name = db.Column(db.String(255), nullable=False)
    fingerprint = db.Column(db.String(32), index=True)
    paths = db.Column(db.JSON, default=list)
    active_version_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utcnow)
    supplier = db.relationship("Supplier", backref="templates")
    versions = db.relationship("TemplateVersion", backref="template", order_by="TemplateVersion.version",
                               cascade="all, delete-orphan")

    @property
    def active_version(self):
        if self.active_version_id is None:
            return None
        return db.session.get(TemplateVersion, self.active_version_id)


class TemplateVersion(db.Model):
    __tablename__ = "template_versions"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    rules = db.Column(db.JSON, nullable=False)
    author = db.Column(db.String(255))
    comment = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=utcnow)


class Unit(db.Model):
    __tablename__ = "units"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_base = db.Column(db.Boolean, default=True, nullable=False)


class UnitAlias(db.Model):
    __tablename__ = "unit_aliases"
    __table_args__ = (db.UniqueConstraint("alias_norm", "supplier_id", name="uq_alias_supplier"),)
    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(64), nullable=False)
    alias_norm = db.Column(db.String(64), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    unit = db.relationship("Unit")
    supplier = db.relationship("Supplier")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.alias_norm = (self.alias or "").strip().lower()


class UnitConversion(db.Model):
    __tablename__ = "unit_conversions"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    from_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    to_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)
    factor = db.Column(db.Numeric(18, 6), nullable=False)
    supplier = db.relationship("Supplier")
    product = db.relationship("Product")
    from_unit = db.relationship("Unit", foreign_keys=[from_unit_id])
    to_unit = db.relationship("Unit", foreign_keys=[to_unit_id])

    @validates("factor")
    def _validate_factor(self, key, value):
        try:
            ok = Decimal(str(value)) > 0
        except (InvalidOperation, ValueError):
            ok = False
        if not ok:
            raise ValueError("Przelicznik musi być liczbą większą od zera.")
        return value


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    gtin = db.Column(db.String(14), index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"))
    unit = db.relationship("Unit")


class ProductMapping(db.Model):
    __tablename__ = "product_mappings"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_code = db.Column(db.String(64))
    supplier_gtin = db.Column(db.String(14))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    supplier = db.relationship("Supplier")
    product = db.relationship("Product")


class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(16), nullable=False, default="upload")
    filename = db.Column(db.String(255))
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    fmt = db.Column(db.String(8))
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"))
    template_version_id = db.Column(db.Integer, db.ForeignKey("template_versions.id"))
    status = db.Column(db.String(16), nullable=False, default=STATUS_RECEIVED, index=True)
    doc_type = db.Column(db.String(16))
    number = db.Column(db.String(128), index=True)
    issue_date = db.Column(db.String(10))
    result = db.Column(db.JSON)
    issues = db.Column(db.JSON, default=list)
    overrides = db.Column(db.JSON, default=dict)
    draft_rules = db.Column(db.JSON)
    error = db.Column(db.Text)
    corrects_document_id = db.Column(db.Integer, db.ForeignKey("documents.id"))
    api_key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    supplier = db.relationship("Supplier")
    template = db.relationship("Template")
    template_version = db.relationship("TemplateVersion")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class ApiKey(db.Model):
    __tablename__ = "api_keys"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    prefix = db.Column(db.String(12), nullable=False)
    key_hash = db.Column(db.String(64), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    webhook_url = db.Column(db.String(500))
    webhook_secret = db.Column(db.String(128))
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="admin")

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(255))
    action = db.Column(db.String(64), nullable=False)
    entity = db.Column(db.String(64), nullable=False)
    entity_id = db.Column(db.Integer)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
