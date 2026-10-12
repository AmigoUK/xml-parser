"""Klucze obce są egzekwowane także na SQLite w testach (PRAGMA foreign_keys=ON) — tak jak w MariaDB/InnoDB.

Bez tego ścieżka naruszająca klucz obcy (np. usunięcie rekordu słownikowego, do którego odwołują się inne) przeszłaby
w testach, a na produkcji skończyła się IntegrityError."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Product, Unit, UnitAlias


def test_sqlite_test_database_enforces_foreign_keys(app):
    assert db.session.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1


def test_dangling_foreign_key_is_rejected(app):
    db.session.add(Product(code="X-1", name="x", unit_id=424242))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_deleting_referenced_row_is_rejected(app):
    """Jednostka z aliasem (klucz obcy NOT NULL, bez kaskady w ORM): DELETE odrzucony jak na InnoDB."""
    u = Unit(code="kg", name="kilogram")
    db.session.add(u)
    db.session.flush()
    db.session.add(UnitAlias(alias="kilo", unit_id=u.id))
    db.session.commit()
    db.session.delete(u)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert Unit.query.count() == 1
