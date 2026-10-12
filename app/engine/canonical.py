"""Kontrakt dokumentu kanonicznego: definicje pól nagłówka i pozycji (`FieldDef`), typ dokumentu (`Invoice`,
`InvoiceLine`) oraz dostęp po ścieżkach kropkowych (`supplier.tax_id`)."""
from dataclasses import dataclass
from typing import TypedDict

TEXT, DATE, MONEY, PRICE, DECIMAL, GTIN, UNIT, LIST = (
    "text", "date", "money", "price", "decimal", "gtin", "unit", "list")


@dataclass(frozen=True)
class FieldDef:
    """Pole dokumentu kanonicznego: klucz (ścieżka kropkowa), etykieta po polsku, rodzaj wartości, czy wymagane."""
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


class Address(TypedDict):
    """Adres strony dokumentu."""
    street: str | None
    postcode: str | None
    city: str | None
    country: str | None


class Party(TypedDict):
    """Strona dokumentu (dostawca, nabywca)."""
    name: str | None
    tax_id: str | None
    address: Address


class Totals(TypedDict):
    """Sumy dokumentu jako tekst z kropką dziesiętną (2 miejsca)."""
    net: str | None
    vat: str | None
    gross: str | None


class InvoiceLine(TypedDict, total=False):
    """Pozycja dokumentu kanonicznego: kwoty i ilości jako tekst z kropką dziesiętną; `unit` to nasz kod jednostki
    (po przeliczeniu), `unit_source` — jednostka z pliku, `product_index` — indeks z kartoteki albo None."""
    line_no: int
    supplier_code: str | None
    gtin: str | None
    name: str | None
    qty: str | None
    unit: str | None
    unit_source: str | None
    unit_price_net: str | None
    net: str | None
    vat_rate: str | None
    vat: str | None
    gross: str | None
    batch: str | None
    expiry_date: str | None
    product_index: str | None
    conversion_factor: str


class Invoice(TypedDict):
    """Dokument kanoniczny — wynik `apply_template`, zapisywany w `Document.result` i zwracany przez API (`invoice`)."""
    doc_type: str | None
    number: str | None
    issue_date: str | None
    sale_date: str | None
    due_date: str | None
    payment_method: str | None
    currency: str | None
    supplier: Party
    buyer: Party
    totals: Totals
    delivery_notes: list[str]
    corrected_invoice_number: str | None
    lines: list[InvoiceLine]


def _address() -> Address:
    return {"street": None, "postcode": None, "city": None, "country": None}


def empty_invoice() -> Invoice:
    """Pusty dokument kanoniczny ze wszystkimi kluczami (typ dokumentu domyślnie `invoice`)."""
    return {
        "doc_type": "invoice", "number": None, "issue_date": None, "sale_date": None,
        "due_date": None, "payment_method": None, "currency": None,
        "supplier": {"name": None, "tax_id": None, "address": _address()},
        "buyer": {"name": None, "tax_id": None, "address": _address()},
        "totals": {"net": None, "vat": None, "gross": None},
        "delivery_notes": [], "corrected_invoice_number": None, "lines": [],
    }


def get_path(d: dict, dotted: str):
    """Wartość pod ścieżką kropkową (`supplier.tax_id`) albo None, gdy brakuje któregoś poziomu."""
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_path(d: dict, dotted: str, value) -> None:
    """Zapisuje wartość pod ścieżką kropkową, tworząc brakujące słowniki pośrednie."""
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
