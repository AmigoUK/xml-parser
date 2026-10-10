"""Pomocnicze operacje na sesji bazy."""
from __future__ import annotations

from typing import Callable, TypeVar

from sqlalchemy.exc import IntegrityError

from app.extensions import db

T = TypeVar("T")
DEFAULT_ATTEMPTS = 3


def commit_with_retry(fn: Callable[[], T], attempts: int = DEFAULT_ATTEMPTS) -> T:
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
