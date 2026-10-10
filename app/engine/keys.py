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


def dedupe_scope(api_key_id) -> str:
    """Zakres wykrywania duplikatów: dokumenty jednego klucza API albo wspólny zakres panelu „web”.
    Dokumenty z różnych zakresów nigdy nie są dla siebie duplikatami (izolacja kluczy API)."""
    return f"api:{int(api_key_id)}" if api_key_id else "web"


def document_key(supplier_id, doc_type, number, scope: str = "web") -> str | None:
    """Klucz faktury: (zakres, dostawca, rodzaj dokumentu, znormalizowany pełny numer) → sha256 hex (64 znaki)."""
    num = norm_doc_number(number)
    if not supplier_id or not num:
        return None
    return _digest("doc", scope, int(supplier_id), fold(doc_type or ""), num)


def norm_mapping_code(value) -> str | None:
    """Kod towaru u dostawcy w postaci porównywalnej (fold) — wspólna dla klucza i wyszukiwania (FR-6)."""
    if value in (None, ""):
        return None
    return fold(value) or None


def norm_mapping_gtin(value) -> str | None:
    """GTIN do klucza mapowania: bez spacji na brzegach, uzupełniony zerami do 14 cyfr (FR-6)."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    return s.zfill(14) if s else None


def norm_mapping_name(value) -> str | None:
    """Znormalizowana nazwa towaru (``supplier_name_norm``) w postaci klucza (fold) (FR-6)."""
    if value in (None, ""):
        return None
    return fold(value) or None


def mapping_key(supplier_id, supplier_code, supplier_gtin, supplier_name_norm) -> str | None:
    """Tożsamość mapowania towaru: kod, a gdy brak — GTIN, a gdy brak — nazwa (BE-3). Brak wszystkich → None.

    Ta sama funkcja liczy ``match_key`` przy zapisie i klucz przy wyszukiwaniu mapowania (FR-6)."""
    if supplier_id is None:
        return None
    code = norm_mapping_code(supplier_code)
    if code:
        return _digest("map", int(supplier_id), "code", code)
    gtin = norm_mapping_gtin(supplier_gtin)
    if gtin:
        return _digest("map", int(supplier_id), "gtin", gtin)
    name = norm_mapping_name(supplier_name_norm)
    if name:
        return _digest("map", int(supplier_id), "name", name)
    return None
