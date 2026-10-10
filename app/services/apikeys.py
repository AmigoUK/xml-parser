import hashlib
import secrets

from app.extensions import db
from app.models import ApiKey, utcnow


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_key(name: str, plaintext: str | None = None) -> tuple[ApiKey, str]:
    plaintext = plaintext or "xp_" + secrets.token_urlsafe(32)
    key = ApiKey(name=name, prefix=plaintext[:10], key_hash=hash_key(plaintext), active=True)
    db.session.add(key)
    db.session.flush()
    return key, plaintext


def verify_key(plaintext: str | None) -> ApiKey | None:
    if not plaintext:
        return None
    key = ApiKey.query.filter_by(key_hash=hash_key(plaintext), active=True).first()
    if key:
        key.last_used_at = utcnow()
    return key
