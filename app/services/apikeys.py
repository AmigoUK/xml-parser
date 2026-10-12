import hashlib
import secrets

from app.extensions import db
from app.models import ApiKey, utcnow
from app.services.webhook_security import new_secret


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


# --- webhook przy kluczu (v0.9.0) — czyste mutacje, commit robi widok -------------------------------------------

def set_webhook_url(key: ApiKey, url: str) -> str | None:
    """Ustawia (już zwalidowany) adres webhooka. Gdy klucz nie ma sekretu, generuje go i zwraca — do jednorazowego
    pokazania; przy istniejącym sekrecie zwraca None."""
    key.webhook_url = url
    if key.webhook_secret:
        return None
    key.webhook_secret = new_secret()
    return key.webhook_secret


def rotate_webhook_secret(key: ApiKey) -> str:
    """Nowy sekret webhooka (stary przestaje działać od razu); zwraca go do jednorazowego pokazania."""
    key.webhook_secret = new_secret()
    return key.webhook_secret


def clear_webhook(key: ApiKey) -> None:
    """Wyłącza webhook klucza: usuwa adres i sekret."""
    key.webhook_url = None
    key.webhook_secret = None
