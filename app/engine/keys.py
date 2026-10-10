"""Klucze unikalności liczone w kodzie (indeksy UNIQUE w bazie — BE-1, BE-17).

Normalizacja odtwarza w kodzie zachowanie kolacji MariaDB `utf8mb4_unicode_ci` (wielkość liter,
akcenty, białe znaki), więc SQLite w testach i MariaDB w produkcji uznają za równe te same wartości
(EDGE-31). Zmiana tych funkcji zmienia klucze zapisane w bazie — wymaga migracji przeliczającej.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

_SEP = "\x1f"


def fold(value) -> str:
    """NFKD bez znaków łączących, bez wielkości liter, zwinięte białe znaki, bez spacji na brzegach."""
    decomposed = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", s).strip()


def _digest(*parts) -> str:
    return hashlib.sha256(_SEP.join(str(p) for p in parts).encode("utf-8")).hexdigest()


def norm_doc_number(number) -> str | None:
    """Pełny (nieobcięty — EDGE-23) numer dokumentu w postaci porównywalnej; spacje wokół „/” i „-” pomijane."""
    if number is None:
        return None
    s = re.sub(r"\s*([/\-])\s*", r"\1", fold(number))
    return s or None


def document_key(supplier_id, doc_type, number) -> str | None:
    """Klucz faktury: (dostawca, rodzaj dokumentu, znormalizowany pełny numer) → sha256 hex (64 znaki)."""
    num = norm_doc_number(number)
    if not supplier_id or not num:
        return None
    return _digest("doc", int(supplier_id), fold(doc_type or ""), num)


def mapping_key(supplier_id, supplier_code, supplier_gtin, supplier_name_norm) -> str | None:
    """Tożsamość mapowania towaru: kod, a gdy brak — GTIN, a gdy brak — nazwa (BE-3). Brak wszystkich → None."""
    if supplier_id is None:
        return None
    if supplier_code not in (None, "") and fold(supplier_code):
        return _digest("map", int(supplier_id), "code", fold(supplier_code))
    if supplier_gtin not in (None, "") and str(supplier_gtin).strip():
        return _digest("map", int(supplier_id), "gtin", str(supplier_gtin).strip().zfill(14))
    if supplier_name_norm not in (None, "") and fold(supplier_name_norm):
        return _digest("map", int(supplier_id), "name", fold(supplier_name_norm))
    return None
