import os

# Lokalny .env nie może zmieniać wyniku testów (np. TRUSTED_PROXY_COUNT): app/config.py pomija load_dotenv() przy
# PYTHON_DOTENV_DISABLED=1, a conftest ładuje się przed modułami testów — więc przed pierwszym importem aplikacji.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "STORAGE_DIR": str(tmp_path / "storage"),
        "WTF_CSRF_ENABLED": False,
        "DEMO_MODE": True,
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "haslo123",
        "DEMO_API_KEY": "xp_test_demo_key",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


@pytest.fixture
def seeded(app):
    from app.services.seed import seed_base, seed_demo
    seed_base()
    seed_demo()
    return app


@pytest.fixture
def auth_client(seeded, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    return client
