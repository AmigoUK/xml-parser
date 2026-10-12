"""Kursor stronicowania listy dokumentów w trybie synchronizacji REST API v1 (keyset po `(updated_at, id)`).

Kursor to dla klienta nieprzezroczysty token: base64url bez dopełnienia z `czas|id` ostatniego zwróconego
dokumentu (czas: naiwny UTC z bazy, `isoformat` z 6 cyframi mikrosekund). Niesie wyłącznie pozycję — bez filtrów
i bez danych wrażliwych; zakres klucza API zawsze wynika z nagłówka żądania, nie z kursora. Czysty moduł
pomocniczy — bez modeli i bez bazy.
"""
import base64
import re
from datetime import datetime

from app.ids import MAX_ID  # największe id kolumny całkowitej — wspólny strażnik (app/ids.py)

from .timeutil import parse_api_datetime

SEPARATOR = "|"
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")  # alfabet base64url, bez dopełnienia „=”


def encode_cursor(updated_at: datetime, doc_id: int) -> str:
    """base64url bez dopełnienia z `updated_at.isoformat(timespec="microseconds") + "|" + str(doc_id)`."""
    raw = updated_at.isoformat(timespec="microseconds") + SEPARATOR + str(doc_id)
    return base64.urlsafe_b64encode(raw.encode("ascii")).rstrip(b"=").decode("ascii")


def decode_cursor(text: str) -> tuple[datetime, int]:
    """Odwrotność encode_cursor. Każdy błąd (base64, brak `|`, zły czas, id nie-liczba, id < 1) → ValueError.

    Czas jest odczytywany jak parametry czasu API (`parse_api_datetime`: naiwny UTC), a id spoza zakresu kolumny
    całkowitej (> MAX_ID) też daje ValueError — w SQLite takie id przy porównaniu kończyłoby się błędem 500.
    """
    if not isinstance(text, str) or not _BASE64URL.fullmatch(text):
        raise ValueError("Kursor musi być tekstem base64url bez dopełnienia.")
    # binascii.Error (zła długość) i UnicodeDecodeError (treść spoza ASCII) są podklasami ValueError
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("ascii")
    time_text, separator, id_text = raw.partition(SEPARATOR)
    if not separator:
        raise ValueError("Kursor nie zawiera separatora „|” między czasem a id.")
    updated_at = parse_api_datetime(time_text)  # ValueError: zły czas
    if not id_text.isdigit() or not 1 <= int(id_text) <= MAX_ID:  # isdigit na ASCII: same cyfry 0–9, bez znaku
        raise ValueError("Id w kursorze musi być liczbą całkowitą od 1.")
    return updated_at, int(id_text)
