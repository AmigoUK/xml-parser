"""Pomocnicze operacje na sesji bazy."""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.exc import IntegrityError

from app.extensions import db

DEFAULT_ATTEMPTS = 3


def commit_with_retry[T](fn: Callable[[], T], attempts: int = DEFAULT_ATTEMPTS) -> T:
    """Wykonuje `fn` i commit; przy IntegrityError (wyścig o unikalny klucz, np. numer wersji szablonu)
    wycofuje transakcję i ponawia na świeżym stanie bazy — do `attempts` razy, potem rzuca dalej (BE-7)."""
    for attempt in range(1, attempts + 1):
        try:
            result = fn()
            db.session.commit()
            return result
        except IntegrityError:
            db.session.rollback()
            if attempt == attempts:
                raise
        except BaseException:
            db.session.rollback()
            raise
    raise AssertionError("nieosiągalne")


def fit_column(column, value):
    """Obcina wartość do długości kolumny tekstowej (MariaDB w trybie strict odrzuca dłuższe); None zostaje None."""
    if value is None:
        return None
    return str(value)[:column.type.length]
