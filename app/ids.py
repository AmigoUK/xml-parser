"""Identyfikatory rekordów z wejścia (adres URL, formularz, parametr zapytania) — jeden strażnik zakresu.

Kolumny `id` to 64-bitowe liczby całkowite (BIGINT / SQLite INTEGER): większa wartość nie istnieje w żadnej bazie,
a w SQLite nie da się jej nawet związać w zapytaniu (OverflowError → 500). Zamiast tego: nieistniejący adres (404)
albo błąd pola formularza. Moduł bez Flaska i bez bazy; z Werkzeuga tylko bazowy konwerter adresów.
"""
import re

from werkzeug.routing import IntegerConverter

MAX_ID = 2**63 - 1  # największe id kolumny całkowitej — większe nie istnieje w żadnej bazie
_DIGITS = re.compile(r"[0-9]+")  # tylko cyfry ASCII: str.isdigit() przyjmuje też np. cyfry arabsko-indyjskie


def parse_id(raw) -> int | None:
    """Liczba całkowita 1…MAX_ID z tekstu (albo z int) — inaczej None, nigdy wyjątek."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= MAX_ID else None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not _DIGITS.fullmatch(text):
        return None
    value = int(text)
    return value if 1 <= value <= MAX_ID else None


class BoundedIntConverter(IntegerConverter):
    """`<int:…>` w adresach ograniczony do zakresu kolumny id: większa liczba to nieistniejący adres (404),
    tak samo na SQLite i MariaDB."""

    def __init__(self, map, fixed_digits=0, min=None, max=None, signed=False):
        limit = MAX_ID if max is None or max > MAX_ID else max
        super().__init__(map, fixed_digits, min, limit, signed)
