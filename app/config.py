import os

from dotenv import load_dotenv

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
    DEMO_MODE = _bool("DEMO_MODE", "1")
    DEMO_API_KEY = os.environ.get("DEMO_API_KEY", "")
    REPO_URL = "https://github.com/AmigoUK/xml-parser"
