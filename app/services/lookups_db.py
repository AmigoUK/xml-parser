from decimal import Decimal

from app.engine.lookups import norm_alias
from app.extensions import db
from app.models import Product, ProductMapping, Supplier, Unit, UnitAlias, UnitConversion


class DbLookups:
    """Implementacja protokołu Lookups na bazie. Cache na czas życia obiektu (jedno przetworzenie)."""

    def __init__(self):
        self._units = {u.code: u for u in Unit.query.all()}
        self._units_by_id = {u.id: u for u in self._units.values()}

    def unit_codes(self) -> list[str]:
        return sorted(self._units)

    def unit_for_alias(self, alias, supplier_id):
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
        u = self._units.get(from_unit)
        if u is None:
            return None
        product = Product.query.filter_by(code=product_code).first() if product_code else None
        pid = product.id if product else None
        for sid, prid in ((supplier_id, pid), (supplier_id, None), (None, pid), (None, None)):
            q = UnitConversion.query.filter_by(from_unit_id=u.id)
            q = q.filter(UnitConversion.supplier_id.is_(None)) if sid is None else q.filter_by(supplier_id=sid)
            q = q.filter(UnitConversion.product_id.is_(None)) if prid is None else q.filter_by(product_id=prid)
            row = q.first()
            if row:
                return self._units_by_id[row.to_unit_id].code, Decimal(row.factor)
        return None

    def product_for(self, supplier_id, supplier_code, gtin):
        if supplier_id:
            q = ProductMapping.query.filter_by(supplier_id=supplier_id)
            row = q.filter_by(supplier_code=supplier_code).first() if supplier_code else None
            if row is None and gtin:
                row = q.filter_by(supplier_gtin=gtin.zfill(14)).first()
            if row:
                return db.session.get(Product, row.product_id).code
        if gtin:
            g14 = gtin.zfill(14)
            for p in Product.query.filter(Product.gtin.isnot(None)).all():
                if p.gtin.zfill(14) == g14:
                    return p.code
        return None

    def products_brief(self) -> list[dict]:
        return [{"code": p.code, "name": p.name, "gtin": p.gtin} for p in Product.query.order_by(Product.code)]

    def suppliers_brief(self) -> list[dict]:
        return [{"id": s.id, "name": s.name, "tax_id": s.tax_id} for s in Supplier.query.order_by(Supplier.name)]
