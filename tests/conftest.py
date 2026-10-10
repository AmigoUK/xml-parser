from pathlib import Path

import pytest

from app import create_app
from app.extensions import db


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
