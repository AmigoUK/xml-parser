from dataclasses import dataclass

TEXT, DATE, MONEY, PRICE, DECIMAL, GTIN, UNIT, LIST = (
    "text", "date", "money", "price", "decimal", "gtin", "unit", "list")


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str = TEXT
    required: bool = False


HEADER_FIELDS = [
    FieldDef("doc_type", "Typ dokumentu"),
    FieldDef("number", "Numer faktury", TEXT, True),
    FieldDef("issue_date", "Data wystawienia", DATE, True),
    FieldDef("sale_date", "Data sprzedaży", DATE),
    FieldDef("due_date", "Termin płatności", DATE),
    FieldDef("payment_method", "Forma płatności"),
    FieldDef("currency", "Waluta", TEXT, True),
    FieldDef("supplier.name", "Dostawca — nazwa"),
    FieldDef("supplier.tax_id", "Dostawca — NIP/VAT"),
    FieldDef("supplier.address.street", "Dostawca — ulica"),
    FieldDef("supplier.address.postcode", "Dostawca — kod pocztowy"),
    FieldDef("supplier.address.city", "Dostawca — miejscowość"),
    FieldDef("supplier.address.country", "Dostawca — kraj"),
    FieldDef("buyer.name", "Nabywca — nazwa"),
    FieldDef("buyer.tax_id", "Nabywca — NIP/VAT"),
    FieldDef("buyer.address.street", "Nabywca — ulica"),
    FieldDef("buyer.address.postcode", "Nabywca — kod pocztowy"),
    FieldDef("buyer.address.city", "Nabywca — miejscowość"),
    FieldDef("buyer.address.country", "Nabywca — kraj"),
    FieldDef("totals.net", "Suma netto", MONEY),
    FieldDef("totals.vat", "Suma VAT", MONEY),
    FieldDef("totals.gross", "Suma brutto", MONEY, True),
    FieldDef("delivery_notes", "Numery WZ", LIST),
    FieldDef("corrected_invoice_number", "Nr faktury korygowanej"),
]

LINE_FIELDS = [
    FieldDef("supplier_code", "Kod towaru dostawcy"),
    FieldDef("gtin", "GTIN/EAN", GTIN),
    FieldDef("name", "Nazwa towaru", TEXT, True),
    FieldDef("qty", "Ilość", DECIMAL, True),
    FieldDef("unit", "Jednostka miary", UNIT, True),
    FieldDef("unit_price_net", "Cena netto", PRICE),
    FieldDef("net", "Wartość netto", MONEY, True),
    FieldDef("vat_rate", "Stawka VAT %", DECIMAL),
    FieldDef("vat", "Wartość VAT", MONEY),
    FieldDef("gross", "Wartość brutto", MONEY),
    FieldDef("batch", "Partia / seria"),
    FieldDef("expiry_date", "Data ważności", DATE),
]

HEADER_KEYS = {f.key for f in HEADER_FIELDS}
LINE_KEYS = {f.key for f in LINE_FIELDS}
FIELD_LABELS = {f.key: f.label for f in HEADER_FIELDS + LINE_FIELDS}
FIELD_LABELS["line_path"] = "Element z pozycjami faktury"


def _address() -> dict:
    return {"street": None, "postcode": None, "city": None, "country": None}


def empty_invoice() -> dict:
    return {
        "doc_type": "invoice", "number": None, "issue_date": None, "sale_date": None,
        "due_date": None, "payment_method": None, "currency": None,
        "supplier": {"name": None, "tax_id": None, "address": _address()},
        "buyer": {"name": None, "tax_id": None, "address": _address()},
        "totals": {"net": None, "vat": None, "gross": None},
        "delivery_notes": [], "corrected_invoice_number": None, "lines": [],
    }


def get_path(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_path(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
