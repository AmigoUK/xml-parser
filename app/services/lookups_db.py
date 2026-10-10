import unicodedata
from decimal import Decimal

from app.engine.lookups import norm_alias, norm_product_name
from app.extensions import db
from app.models import Product, ProductMapping, Supplier, Unit, UnitAlias, UnitConversion


def _fold(value: str) -> str:
    """Przybliżenie kolacji MariaDB *_unicode_ci: bez akcentów, bez wielkości liter i spacji na końcu."""
    decomposed = unicodedata.normalize("NFKD", str(value))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().rstrip(" ")


class DbLookups:
    """Implementacja protokołu Lookups na bazie. Cache na czas życia obiektu (jedno przetworzenie)."""

    def __init__(self):
        self._units = {u.code: u for u in Unit.query.all()}
        self._units_by_id = {u.id: u for u in self._units.values()}
        # pamięć wyników na czas jednego przetworzenia — bez niej 5 000 pozycji = dziesiątki tys. zapytań (EDGE-5)
        self._memo: dict[tuple, object] = {}
        self._gtin_index: dict[str, str] | None = None

    def _cached(self, key: tuple, compute):
        if key not in self._memo:
            self._memo[key] = compute()
        return self._memo[key]

    def unit_codes(self) -> list[str]:
        return sorted(self._units)

    def unit_for_alias(self, alias, supplier_id):
        return self._cached(("alias", norm_alias(alias), supplier_id), lambda: self._unit_for_alias(alias, supplier_id))

    def _unit_for_alias(self, alias, supplier_id):
        a = norm_alias(alias)
        if a in self._units:
            return a
        q = UnitAlias.query.filter_by(alias_norm=a)
        row = q.filter_by(supplier_id=supplier_id).first() if supplier_id else None
        row = row or q.filter(UnitAlias.supplier_id.is_(None)).first()
        return self._units_by_id[row.unit_id].code if row else None

    def is_base_unit(self, code):
        u = self._units.get(code)
        return True if u is None else bool(u.is_base)

    def conversion(self, supplier_id, product_code, from_unit):
        return self._cached(("conv", supplier_id, product_code, from_unit),
                            lambda: self._conversion(supplier_id, product_code, from_unit))

    def _conversion(self, supplier_id, product_code, from_unit):
        u = self._units.get(from_unit)
        if u is None:
            return None
        product = Product.query.filter_by(code=product_code).first() if product_code else None
        pid = product.id if product else None
        for sid, prid in ((supplier_id, pid), (supplier_id, None), (None, pid), (None, None)):
            q = UnitConversion.query.filter_by(from_unit_id=u.id)
            q = q.filter(UnitConversion.supplier_id.is_(None)) if sid is None else q.filter_by(supplier_id=sid)
            q = q.filter(UnitConversion.product_id.is_(None)) if prid is None else q.filter_by(product_id=prid)
            row = q.order_by(UnitConversion.id.desc()).first()  # najnowszy wygrywa (stare duplikaty — BE-4)
            if row:
                return self._units_by_id[row.to_unit_id].code, Decimal(row.factor)
        return None

    def _mapping_keys(self, supplier_id) -> tuple[set, set, set]:
        """Złożone (fold) klucze mapowań dostawcy z jednego zapytania — szybkie odrzucenie pozycji bez
        mapowania. Trafienie i tak idzie zapytaniem do bazy, więc zachowana jest semantyka kolacji DB."""
        def load():
            codes, gtins, names = set(), set(), set()
            for code, g, name in ProductMapping.query.filter_by(supplier_id=supplier_id).with_entities(
                    ProductMapping.supplier_code, ProductMapping.supplier_gtin, ProductMapping.supplier_name_norm):
                if code is not None:
                    codes.add(_fold(code))
                if g is not None:
                    gtins.add(_fold(g))
                if name is not None and code is None and g is None:
                    names.add(name)
            return codes, gtins, names
        return self._cached(("mapping-keys", supplier_id), load)

    def product_for(self, supplier_id, supplier_code, gtin, name=None):
        return self._cached(("product", supplier_id, supplier_code, gtin, name),
                            lambda: self._product_for(supplier_id, supplier_code, gtin, name))

    def _product_for(self, supplier_id, supplier_code, gtin, name=None):
        if supplier_id:
            codes, gtins, names = self._mapping_keys(supplier_id)
            q = ProductMapping.query.filter_by(supplier_id=supplier_id)
            row = (q.filter_by(supplier_code=supplier_code).first()
                   if supplier_code and _fold(supplier_code) in codes else None)
            if row is None and gtin and _fold(gtin.zfill(14)) in gtins:
                row = q.filter_by(supplier_gtin=gtin.zfill(14)).first()
            name_key = norm_product_name(name) if not supplier_code and not gtin else None
            if row is None and name_key and name_key in names:  # pozycja bez kodu i GTIN (BE-3)
                row = q.filter(ProductMapping.supplier_code.is_(None), ProductMapping.supplier_gtin.is_(None),
                               ProductMapping.supplier_name_norm == name_key).order_by(ProductMapping.id).first()
            if row:
                return db.session.get(Product, row.product_id).code
        if gtin:
            if self._gtin_index is None:
                self._gtin_index = {}
                for p in Product.query.filter(Product.gtin.isnot(None)).order_by(Product.id):
                    self._gtin_index.setdefault(p.gtin.zfill(14), p.code)
            return self._gtin_index.get(gtin.zfill(14))
        return None

    def product_exists(self, code) -> bool:
        return self._cached(("product-exists", code),
                            lambda: Product.query.filter_by(code=code).first() is not None)

    def unit_exists(self, code) -> bool:
        return code in self._units

    def products_brief(self) -> list[dict]:
        return [{"code": p.code, "name": p.name, "gtin": p.gtin} for p in Product.query.order_by(Product.code)]

    def suppliers_brief(self) -> list[dict]:
        return [{"id": s.id, "name": s.name, "tax_id": s.tax_id} for s in Supplier.query.order_by(Supplier.name)]
