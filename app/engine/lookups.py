import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class Lookups(Protocol):
    def unit_for_alias(self, alias: str, supplier_id: int | None) -> str | None: ...
    def is_base_unit(self, code: str) -> bool: ...
    def conversion(self, supplier_id: int | None, product_code: str | None,
                   from_unit: str) -> tuple[str, Decimal] | None: ...
    def product_for(self, supplier_id: int | None, supplier_code: str | None,
                    gtin: str | None, name: str | None = None) -> str | None: ...
    def product_exists(self, code: str) -> bool: ...
    def unit_exists(self, code: str) -> bool: ...


def norm_alias(alias: str) -> str:
    return (alias or "").strip().lower()


NAME_NORM_MAX = 255


def norm_product_name(name: str | None) -> str | None:
    """Klucz mapowania towaru po nazwie (pozycje bez kodu i GTIN — BE-3): NFKC, bez wielkości liter,
    zwinięte białe znaki. Pusta nazwa → None."""
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name or "")).strip().casefold()
    return s[:NAME_NORM_MAX] or None


@dataclass
class MemoryLookups:
    units: dict[str, bool] = field(default_factory=lambda: {"szt": True, "kg": True, "l": True, "m": True})
    aliases: dict[tuple[str, int | None], str] = field(default_factory=dict)
    conversions: dict[tuple[int | None, str | None, str], tuple[str, Decimal]] = field(default_factory=dict)
    product_by_code: dict[tuple[int | None, str], str] = field(default_factory=dict)
    product_by_gtin: dict[str, str] = field(default_factory=dict)
    product_by_name: dict[tuple[int | None, str], str] = field(default_factory=dict)
    known_products: set[str] | None = None  # None = każdy kod towaru istnieje

    def unit_for_alias(self, alias, supplier_id):
        a = norm_alias(alias)
        if a in self.units:
            return a
        return self.aliases.get((a, supplier_id)) or self.aliases.get((a, None))

    def is_base_unit(self, code):
        return self.units.get(code, True)

    def conversion(self, supplier_id, product_code, from_unit):
        for key in ((supplier_id, product_code, from_unit), (supplier_id, None, from_unit),
                    (None, product_code, from_unit), (None, None, from_unit)):
            if key in self.conversions:
                return self.conversions[key]
        return None

    def product_for(self, supplier_id, supplier_code, gtin, name=None):
        if supplier_code and (supplier_id, supplier_code) in self.product_by_code:
            return self.product_by_code[(supplier_id, supplier_code)]
        if gtin:
            return self.product_by_gtin.get(gtin.zfill(14))
        if not supplier_code and norm_product_name(name):
            return self.product_by_name.get((supplier_id, norm_product_name(name)))
        return None

    def product_exists(self, code):
        return self.known_products is None or code in self.known_products

    def unit_exists(self, code):
        return code in self.units
