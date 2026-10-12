import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from flask_login import UserMixin
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from .engine.keys import alias_key, mapping_key
from .extensions import db

STATUS_RECEIVED = "received"
STATUS_APPROVED = "approved"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_DUPLICATE = "duplicate"
STATUS_REJECTED = "rejected"
# „żywy” dokument (nie duplikat, nie odrzucony) — tylko taki może mieć klucz unikalności faktury (BE-1)
LIVE_STATUSES = (STATUS_APPROVED, STATUS_NEEDS_REVIEW)
STATUS_LABELS = {
    STATUS_RECEIVED: "Przyjęta",
    STATUS_APPROVED: "Zatwierdzona",
    STATUS_NEEDS_REVIEW: "Do wyjaśnienia",
    STATUS_DUPLICATE: "Duplikat",
    STATUS_REJECTED: "Odrzucona",
}

# webhooki (v0.9.0): stan dostawy w outboxie i rodzaje zdarzeń
WEBHOOK_PENDING = "pending"
WEBHOOK_SENT = "sent"
WEBHOOK_FAILED = "failed"
EVENT_STATUS_CHANGED = "document.status_changed"
EVENT_TEST = "webhook.test"


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


# MariaDB/MySQL: mikrosekundy (keyset po updated_at); SQLite i tak je przechowuje
PRECISE_DATETIME = db.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    # znormalizowany NIP/VAT (BE-11); unikalny w bazie — wyścig dwóch „Utwórz dostawcę” kończy się IntegrityError
    tax_id = db.Column(db.String(64), index=True, unique=True)
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
    __table_args__ = (db.UniqueConstraint("template_id", "version", name="uq_template_version"),)
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
    # sha256 (zakres: dostawca albo 0 = globalny, alias po fold) — unikalny także dla aliasów globalnych
    # (supplier_id NULL nie jest unikalny w UNIQUE) i niezależny od kolacji bazy (BE-17, FR-9)
    alias_key = db.Column(db.String(64), unique=True, index=True)
    unit = db.relationship("Unit")
    supplier = db.relationship("Supplier")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.alias_norm = (self.alias or "").strip().lower()


class UnitConversion(db.Model):
    __tablename__ = "unit_conversions"
    # jeden przelicznik na (dostawca, towar, z jednostki); NULL = „wszyscy” → zakres 0 (BE-4, BE-17)
    __table_args__ = (db.Index("uq_conversion_scope", "supplier_scope", "product_scope", "from_unit_id",
                               unique=True),)
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    supplier_scope = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    product_scope = db.Column(db.Integer, nullable=False, default=0, server_default="0")
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
            d = Decimal(str(value))
            ok = d.is_finite() and d >= Decimal("0.000001")
        except (InvalidOperation, ValueError):
            ok = False
        if not ok:
            raise ValueError("Przelicznik musi być liczbą większą od zera (min. 0,000001).")
        return value


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    # kolacja binarna w MariaDB (migracja d2c1e7a94f30): `ABC-1` i `abc-1` to różne indeksy — jak w SQLite
    # i w testach; z domyślną utf8mb4_unicode_ci import CSV nadpisywałby po cichu towar o kodzie różniącym się
    # tylko wielkością liter lub akcentem
    code = db.Column(db.String(64).with_variant(mysql.VARCHAR(64, collation="utf8mb4_bin"), "mysql", "mariadb"),
                     unique=True, nullable=False)
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
    # pozycje bez kodu i GTIN zapamiętujemy po znormalizowanej nazwie towaru (BE-3/EDGE-3)
    supplier_name_norm = db.Column(db.String(255))
    # sha256 tożsamości mapowania (dostawca + kod / GTIN / nazwa) — unikalny; hash, bo indeks złożony
    # z kilku VARCHAR(255) utf8mb4 przekroczyłby limit 3072 B w MariaDB (BE-17)
    match_key = db.Column(db.String(64), unique=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    supplier = db.relationship("Supplier")
    product = db.relationship("Product")


class Document(db.Model):
    __tablename__ = "documents"
    __table_args__ = (
        # lista dokumentów klucza API filtrowana po statusie i dacie (BE-17)
        db.Index("ix_documents_api_status_created", "api_key_id", "status", "created_at"),
        # tryb synchronizacji listy API: keyset po (updated_at, id) w obrębie klucza (migracja 2eff54106035)
        db.Index("ix_documents_api_key_updated", "api_key_id", "updated_at", "id"),
    )
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
    # ręczne odrzucenie przez operatora (kto) — trwałe do jawnego „Przywróć”; automatyczne
    # odrzucenia (unreadable, too_many_lines) mają tu NULL i można je przetworzyć ponownie (BE-2)
    rejected_by = db.Column(db.String(255))
    # sha256(dostawca, doc_type, znormalizowany pełny numer) — liczony zawsze, gdy znane (wyszukiwanie kopii)
    dedupe_hash = db.Column(db.String(64), index=True)
    # ten sam hash, ale tylko dla „żywego” oryginału; UNIQUE → najwyżej jeden żywy dokument na fakturę,
    # także przy równoległym przyjęciu (BE-1/EDGE-17). NULL: duplikat, odrzucony, allow_duplicate.
    dedupe_key = db.Column(db.String(64), unique=True, index=True)
    corrects_document_id = db.Column(db.Integer, db.ForeignKey("documents.id"))
    api_key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id"))
    created_at = db.Column(PRECISE_DATETIME, default=utcnow, index=True)
    updated_at = db.Column(PRECISE_DATETIME, default=utcnow, onupdate=utcnow)
    supplier = db.relationship("Supplier")
    template = db.relationship("Template")
    template_version = db.relationship("TemplateVersion")
    # bez backrefu: usunięcie klucza nie dotyka dokumentów (klucz z dokumentami można tylko dezaktywować, BE-18)
    api_key = db.relationship("ApiKey")

    @validates("status")
    def _release_dedupe_key(self, key, value):
        if value not in LIVE_STATUSES:
            self.dedupe_key = None
        return value

    @property
    def is_manually_rejected(self) -> bool:
        return self.status == STATUS_REJECTED and self.rejected_by is not None

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
    # dostawy webhooków znikają razem z kluczem — w ORM (delete-orphan) i w bazie (ON DELETE CASCADE)
    deliveries = db.relationship("WebhookDelivery", back_populates="api_key", cascade="all, delete-orphan",
                                 passive_deletes=True)


def new_delivery_uuid() -> str:
    return str(uuid.uuid4())


class WebhookDelivery(db.Model):
    """Outbox webhooków (v0.9.0, migracja 99f2fe61d963): jeden wiersz = jedno zdarzenie do wysłania na adres klucza
    API. Wiersz powstaje w tej samej sesji co zmiana dokumentu; wysyła go worker z ponowieniami."""
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # lista dostaw klucza (API, panel): keyset po (created_at, id) w obrębie klucza; obsługuje też klucz obcy
        # api_key_id (pierwsza kolumna) — osobny indeks na samym api_key_id byłby nadmiarowy
        db.Index("ix_webhook_deliveries_api_key_created", "api_key_id", "created_at", "id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    # stały identyfikator dostawy (nagłówek X-XP-Delivery) — ten sam przy każdym ponowieniu
    uuid = db.Column(db.String(36), unique=True, index=True, nullable=False, default=new_delivery_uuid)
    api_key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    # NULL dla webhook.test; bez kaskady — dokumentu z dostawą nie da się usunąć (reset demo kasuje najpierw dostawy)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), index=True)
    event = db.Column(db.String(64), nullable=False)
    # ładunek zbudowany przy enqueue; bajty i podpis liczy wysyłka
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(16), nullable=False, default=WEBHOOK_PENDING, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    # kiedy najbliższa próba (także lease workera); NULL = od razu
    next_attempt_at = db.Column(PRECISE_DATETIME, index=True)
    # Text, a nie String(500): zbyt długi komunikat nie może wywrócić zapisu wyniku (tryb strict MariaDB);
    # worker i tak obcina go przed zapisem
    last_error = db.Column(db.Text)
    last_status_code = db.Column(db.Integer)
    created_at = db.Column(PRECISE_DATETIME, nullable=False, default=utcnow)
    sent_at = db.Column(PRECISE_DATETIME)
    api_key = db.relationship("ApiKey", back_populates="deliveries")
    document = db.relationship("Document")


def new_session_token() -> str:
    return secrets.token_hex(16)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="admin")
    # zmieniany przy wylogowaniu i zmianie hasła — unieważnia skopiowane ciasteczka sesji (SEC-4)
    session_token = db.Column(db.String(64), nullable=False, default=new_session_token)

    def get_id(self) -> str:
        if not self.session_token:
            self.session_token = new_session_token()
        return f"{self.id}:{self.session_token}"

    def rotate_session_token(self) -> None:
        self.session_token = new_session_token()

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)
        self.rotate_session_token()

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


class LoginAttempt(db.Model):
    """Nieudane próby logowania — limit prób per e-mail i per IP (SEC-2), wspólny dla wszystkich workerów."""
    __tablename__ = "login_attempts"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    ip = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


@event.listens_for(UnitAlias, "before_insert")
@event.listens_for(UnitAlias, "before_update")
def _alias_key(mapper, connection, target):
    target.alias_key = alias_key(target.supplier_id, target.alias_norm)


@event.listens_for(UnitConversion, "before_insert")
@event.listens_for(UnitConversion, "before_update")
def _conversion_scope(mapper, connection, target):
    target.supplier_scope = target.supplier_id or 0
    target.product_scope = target.product_id or 0


@event.listens_for(ProductMapping, "before_insert")
@event.listens_for(ProductMapping, "before_update")
def _mapping_key(mapper, connection, target):
    target.match_key = mapping_key(target.supplier_id, target.supplier_code, target.supplier_gtin,
                                   target.supplier_name_norm)
