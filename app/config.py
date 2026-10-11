import os
from datetime import timedelta

from dotenv import load_dotenv

# Testy i skrypty narzędziowe ustawiają PYTHON_DOTENV_DISABLED=1, żeby lokalny .env nie wpływał na wynik
# (wyłączają te same wartości co w samym python-dotenv: 1, true, t, yes, y).
if os.environ.get("PYTHON_DOTENV_DISABLED", "").casefold() not in {"1", "true", "t", "yes", "y"}:
    load_dotenv()

DEV_SECRET_KEY = "dev-only-change-me"
PLACEHOLDER_SECRET_KEYS = {DEV_SECRET_KEY, "zmien-mnie", ""}


def _bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "tak"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///xmlparser-dev.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")
    MAX_DOCUMENT_BYTES = int(os.environ.get("MAX_DOCUMENT_BYTES", 10 * 1024 * 1024))
    # limity przeciw DoS (SEC-1): liczba węzłów drzewa (elementy + atrybuty / komórki) i liczba pozycji
    MAX_TREE_NODES = int(os.environ.get("MAX_TREE_NODES", 200_000))
    MAX_LINES = int(os.environ.get("MAX_LINES", 5_000))
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    # fail-closed: tryb demo tylko jawnie (DEMO_MODE=1), nigdy na instancji z prawdziwymi danymi
    DEMO_MODE = _bool("DEMO_MODE", "0")
    DEMO_API_KEY = os.environ.get("DEMO_API_KEY", "")
    REPO_URL = "https://github.com/AmigoUK/xml-parser"
    # ciasteczka sesji (SEC-4/OPS-9); Secure włącz, gdy panel jest za TLS (np. tailscale serve https)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", "0")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_DURATION = timedelta(hours=8)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    # limit prób logowania (SEC-2): główny per (e-mail, IP); per IP i per sam e-mail z wyższymi progami
    LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", 5))
    LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", 15))
    LOGIN_MAX_ATTEMPTS_PER_IP = int(os.environ.get("LOGIN_MAX_ATTEMPTS_PER_IP", 20))
    LOGIN_MAX_ATTEMPTS_PER_EMAIL = int(os.environ.get("LOGIN_MAX_ATTEMPTS_PER_EMAIL", 50))
    LOGIN_EMAIL_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_EMAIL_LOCKOUT_MINUTES", 5))
    # liczba zaufanych reverse proxy przed aplikacją (OPS-8); 0 = nagłówki X-Forwarded-* ignorowane
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", 0))
