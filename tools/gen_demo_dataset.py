#!/usr/bin/env python
"""Generator zestawu demo „Miesiąc faktur” (demo/dataset/): 24 fikcyjne faktury sześciu dostawców z października
2026, manifest z oczekiwanymi statusami (`manifest.json`) i opis zestawu (`README.md`).

Uruchomienie:
    .venv/bin/python tools/gen_demo_dataset.py            # zapisuje pliki do demo/dataset/
    .venv/bin/python tools/gen_demo_dataset.py --check    # kod 0 tylko, gdy regeneracja daje identyczne bajty

Generator jest deterministyczny i NIE importuje aplikacji (`app`): kwoty liczone na `Decimal`, cyfra kontrolna
GTIN liczona lokalnie, `random.Random(SEED)` losuje wyłącznie ilości (w stałej kolejności). Wszystkie dane (firmy,
NIP/VAT, adresy, numery, GTIN) są fikcyjne — w stylu próbek z demo/samples (te same tożsamości dostawców:
nazwa + NIP, więc szablon nauczony na próbce działa też na zestawie). Oczekiwane statusy w manifeście sprawdza
tests/test_demo_dataset_files.py::test_expected_statuses_on_fresh_db na prawdziwym silniku.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
import tempfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "demo" / "dataset"
SEED = 20261001
TOOL_PATH = "tools/gen_demo_dataset.py"
MANIFEST = "manifest.json"
README = "README.md"
CENT = Decimal("0.01")
BUYER = {"name": "Piekarnia Demo Sp. z o.o.", "nip": "9990000099", "street": "ul. Demonstracyjna 2",
         "postcode": "00-951", "city": "Przykładowo"}


def gtin_check_digit(body: str) -> str:
    """Cyfra kontrolna GTIN (GS1, modulo 10) dla numeru bez ostatniej cyfry."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def gtin(body: str) -> str:
    """Pełny GTIN z cyfrą kontrolną."""
    return body + gtin_check_digit(body)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------------------------------------------------------
# Świat zestawu: dostawcy i ich towary
# ------------------------------------------------------------------------------------------------------------------

SUPPLIERS = {
    "alfa": {"name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "9990000011", "format": "xml"},
    "beta": {"name": "Młyn Beta Sp. z o.o.", "tax_id": "9990000022", "format": "xml"},
    "eta": {"name": "Eta Packaging Sp. z o.o.", "tax_id": "9990000077", "format": "xml"},
    "gamma": {"name": "Gamma Aromen GmbH", "tax_id": "DE999999999", "format": "xml"},
    "epsilon": {"name": "Epsilon Dairy Ltd", "tax_id": "GB999000044", "format": "json"},
    "zeta": {"name": "Hurtownia Zeta Sp. j.", "tax_id": "9990000066", "format": "csv"},
}


@dataclass(frozen=True)
class Item:
    """Towar dostawcy: kod, nazwa, GTIN, jednostka z faktury, cena netto, stawka VAT i zakres losowanej ilości."""
    code: str
    name: str
    gtin: str
    unit: str
    price: Decimal
    vat: int
    qty: tuple[int, int]


ITEMS = {
    # Alfa: kody A-100/A-200 mają GTIN z kartoteki demo; A-300 (GTIN spoza kartoteki) przypisuje się po kodzie
    "A-100": Item("A-100", "Posypka czekoladowa 1 kg", gtin("590999900001"), "pcs", Decimal("12.50"), 5, (2, 8)),
    "A-200": Item("A-200", "Mak niebieski 500 g", gtin("590999900002"), "pcs", Decimal("4.20"), 5, (4, 12)),
    "A-300": Item("A-300", "Masa marcepanowa 5 kg", gtin("590999900003"), "pcs", Decimal("31.75"), 5, (1, 4)),
    # Beta: mąka w workach 25 kg (przelicznik z nazwy)
    "M-450": Item("M-450", "Mąka pszenna typ 450 25 kg", gtin("590999900004"), "worek", Decimal("40.00"), 5,
                  (10, 30)),
    "M-750": Item("M-750", "Mąka żytnia typ 750 25 kg", gtin("590999900005"), "worek", Decimal("42.50"), 5,
                  (2, 8)),
    # Eta: opakowania, XML z angielskimi tagami
    "E-01": Item("E-01", "Pudełko na tort 30x30 cm", gtin("590999900006"), "pcs", Decimal("2.40"), 23, (50, 150)),
    "E-02": Item("E-02", "Podkład pod tort 28 cm", gtin("590999900007"), "pcs", Decimal("1.10"), 23, (50, 150)),
    "E-03": Item("E-03", "Taśma klejąca transparentna 48 mm", gtin("590999900014"), "pcs", Decimal("6.90"), 23,
                 (6, 24)),
    # Gamma: UBL 2.1, kody jednostek UN/ECE
    "G-01": Item("G-01", "Wanilia burbon laski 10 szt", gtin("400999900001"), "C62", Decimal("2.50"), 7, (6, 18)),
    "G-02": Item("G-02", "Aromat rumowy 100 ml", gtin("400999900002"), "H87", Decimal("2.00"), 7, (12, 36)),
    # Epsilon: JSON, towary rozpoznawane po GTIN z kartoteki
    "E-1": Item("E-1", "Masło 82% 1 kg", gtin("590999900008"), "EA", Decimal("5.10"), 0, (4, 12)),
    "E-2": Item("E-2", "Śmietanka 30% 1 l", gtin("590999900009"), "EA", Decimal("3.00"), 0, (3, 10)),
    # Zeta: CSV ze średnikiem, worki 25 kg i kartony po 20 szt; dostawca zapisuje jednostki na dwa sposoby
    # („wor.”/„worek”, „kart.”/„karton”) — skrót to nieznany alias, pełna nazwa to nasza jednostka bez przelicznika
    "Z-25": Item("Z-25", "Cukier kryształ 25 kg", gtin("590999900012"), "wor.", Decimal("75.00"), 5, (4, 20)),
    "Z-26": Item("Z-26", "Sól kamienna (worek 25kg)", gtin("590999900013"), "worek", Decimal("48.00"), 5, (1, 6)),
    "Z-40": Item("Z-40", "Kubek papierowy 250 ml karton 20 szt", gtin("590999900015"), "karton", Decimal("18.00"),
                 23, (2, 10)),
    "Z-50": Item("Z-50", "Pudełko na tort 30x30 cm", gtin("590999900006"), "kart.", Decimal("44.00"), 23, (1, 4)),
}


@dataclass
class Spec:
    """Jedna faktura zestawu (albo jej kopia bajt w bajt — `copy_of`) z opisem i oczekiwanym wynikiem."""
    supplier: str
    k: int
    number: str | None
    items: list[str]
    shows: str
    on_ingest: tuple
    after_resolve: tuple | None = None
    phase: str = "rest"
    suffix: str = ""
    copy_of: int | None = None  # order wcześniejszej faktury, której bajty powtarzamy
    no_currency: bool = False
    unit_overrides: dict[str, str] = field(default_factory=dict)
    mismatch_line: int | None = None  # numer pozycji (od 1), w której netto ≠ ilość × cena


APPROVED = ("approved", [], [])

# Kolejność = kolejność plików, dat wystawienia i wczytywania (pierwsza faktura każdego dostawcy na początku).
# Faza „pozostałe” (07–24) bywa wczytywana JEDNĄ partią zaraz po nauce na pierwszych fakturach — czyste faktury
# (07–12, 14, 19, 21–24) mogą więc używać wyłącznie towarów, jednostek, aliasów, przeliczników i waluty znanych po
# rozwiązaniu faktur 01–06 (plus kartoteka demo), nigdy nauki z pułapek 15–18.
SPECS: list[Spec] = [
    Spec("alfa", 1, "FA/2026/10/101", ["A-100", "A-200", "A-300"],
         "nowy dostawca, brak waluty, jednostka „pcs”, towar po kodzie dostawcy",
         ("needs_review", ["unknown_supplier", "unknown_unit", "unmapped_field", "unmapped_product"], []),
         APPROVED, phase="first"),
    Spec("beta", 1, "FV/B/1101/2026", ["M-450", "M-750"],
         "nowy dostawca (KSeF), „worek” → kg ×25 z nazwy towaru, towar po nazwie",
         ("needs_review", ["missing_conversion", "unknown_supplier", "unmapped_product"], []),
         APPROVED, phase="first"),
    Spec("eta", 1, "ETA/2026/10/0001", ["E-01", "E-02"],
         "nowy dostawca (XML z angielskimi tagami), jednostka „pcs”, towar po nazwie",
         ("needs_review", ["unknown_supplier", "unknown_unit", "unmapped_product"], []),
         APPROVED, phase="first"),
    Spec("gamma", 1, "GAM-2026-0401", ["G-01", "G-02"],
         "nowy dostawca (UBL 2.1), kody jednostek „C62”/„H87”, towar po nazwie",
         ("needs_review", ["unknown_supplier", "unknown_unit", "unmapped_product"], []),
         APPROVED, phase="first"),
    Spec("epsilon", 1, "E-2026-0101", ["E-1", "E-2"],
         "nowy dostawca (JSON), jednostka „EA”, towary rozpoznane po GTIN",
         ("needs_review", ["unknown_supplier", "unknown_unit"], []),
         APPROVED, phase="first"),
    Spec("zeta", 1, "Z/401/2026", ["Z-25", "Z-26"],
         "nowy dostawca (CSV), „wor.” → worek (obok pełnej nazwy „worek”), 1 worek = 25 kg z nazwy towaru, "
         "towary spoza kartoteki",
         ("needs_review", ["missing_conversion", "unknown_supplier", "unknown_unit", "unmapped_product"], []),
         APPROVED, phase="first"),
    Spec("alfa", 2, "FA/2026/10/102", ["A-100", "A-300"], "druga faktura — przechodzi automatycznie", APPROVED),
    Spec("beta", 2, "FV/B/1102/2026", ["M-450", "M-750"], "druga faktura — przechodzi automatycznie", APPROVED),
    Spec("eta", 2, "ETA/2026/10/0002", ["E-01", "E-02"], "druga faktura — przechodzi automatycznie", APPROVED),
    Spec("gamma", 2, "GAM-2026-0402", ["G-01", "G-02"], "druga faktura — przechodzi automatycznie", APPROVED),
    Spec("epsilon", 2, "E-2026-0102", ["E-1", "E-2"], "druga faktura — przechodzi automatycznie", APPROVED),
    Spec("zeta", 2, "Z/402/2026", ["Z-25", "Z-26"], "druga faktura — przechodzi automatycznie", APPROVED),
    Spec("alfa", 3, "FA/2026/10/103", ["A-100", "A-200", "A-300"],
         "niezgodność sumy w pozycji (ilość × cena ≠ netto) — ostrzeżenie, faktura zatwierdzona",
         ("approved", [], ["sum_mismatch_line"]), mismatch_line=2),
    Spec("beta", 3, "FV/B/1103/2026", ["M-450", "M-750"], "czysta faktura", APPROVED),
    Spec("eta", 3, "ETA/2026/10/0003", ["E-01", "E-03"],
         "towar spoza kartoteki (nowy GTIN) — „utwórz towar”",
         ("needs_review", ["unmapped_product"], []), APPROVED),
    Spec("gamma", 3, "GAM-2026-0403", ["G-01", "G-02"],
         "nowy alias jednostki „PCE” zamiast „C62”",
         ("needs_review", ["unknown_unit"], []), APPROVED, unit_overrides={"G-01": "PCE"}),
    Spec("epsilon", 3, "E-2026-0103", ["E-1", "E-2"],
         "brak klucza waluty — pierwsza podpowiedź to PLN, ale ten dostawca rozlicza się w GBP: wybierz GBP",
         ("needs_review", ["unmapped_field"], []), APPROVED, no_currency=True),
    Spec("zeta", 3, "Z/403/2026", ["Z-25", "Z-40", "Z-50"],
         "„kart.” → karton (obok pełnej nazwy „karton”), 1 karton = 20 szt z nazwy towaru, nowy towar",
         ("needs_review", ["missing_conversion", "unknown_unit", "unmapped_product"], []), APPROVED),
    Spec("alfa", 4, "FA/2026/10/104", ["A-200", "A-300"], "czysta faktura", APPROVED),
    Spec("beta", 3, None, [], "ten sam plik co 14-beta-3.xml wysłany drugi raz — duplikat",
         ("duplicate", ["duplicate"], []), suffix="-ponownie", copy_of=14),
    Spec("eta", 4, "ETA/2026/10/0004", ["E-01", "E-02"], "czysta faktura", APPROVED),
    Spec("gamma", 4, "GAM-2026-0404", ["G-01", "G-02"], "czysta faktura", APPROVED),
    Spec("epsilon", 4, "E-2026-0104", ["E-1", "E-2"], "czysta faktura", APPROVED),
    Spec("zeta", 4, "Z/404/2026", ["Z-25", "Z-26"], "czysta faktura", APPROVED),
]


# ------------------------------------------------------------------------------------------------------------------
# Wyliczenie faktury (kwoty na Decimal)
# ------------------------------------------------------------------------------------------------------------------

@dataclass
class Line:
    no: int
    item: Item
    unit: str
    qty: int
    net: Decimal
    vat: Decimal

    @property
    def gross(self) -> Decimal:
        return self.net + self.vat


@dataclass
class Invoice:
    spec: Spec
    number: str
    issue: dt.date
    lines: list[Line]

    @property
    def due(self) -> dt.date:
        return self.issue + dt.timedelta(days=30)

    @property
    def net(self) -> Decimal:
        return sum((ln.net for ln in self.lines), Decimal("0"))

    @property
    def vat(self) -> Decimal:
        return sum((ln.vat for ln in self.lines), Decimal("0"))

    @property
    def gross(self) -> Decimal:
        return self.net + self.vat


def build_invoice(spec: Spec, order: int, rng: random.Random) -> Invoice:
    lines = []
    for no, code in enumerate(spec.items, start=1):
        item = ITEMS[code]
        qty = rng.randint(*item.qty)
        net = money(item.price * qty)
        if spec.mismatch_line == no:
            net += Decimal("1.00")  # celowa niezgodność: ilość × cena ≠ netto (sumy faktury liczone z netto)
        vat = money(net * item.vat / Decimal(100))
        lines.append(Line(no, item, spec.unit_overrides.get(code, item.unit), qty, net, vat))
    return Invoice(spec, spec.number, dt.date(2026, 10, order + 1), lines)


# ------------------------------------------------------------------------------------------------------------------
# Renderery formatów (układ jak w próbkach demo/samples)
# ------------------------------------------------------------------------------------------------------------------

def _x(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _gs1(item: Item, inv: Invoice, line: Line) -> str:
    """Kod GS1-128: AI 01 (GTIN-14), AI 15 (najlepiej spożyć przed — +9 miesięcy), AI 10 (partia)."""
    best = inv.issue.replace(year=inv.issue.year + 1) - dt.timedelta(days=90)
    return f"010{item.gtin}15{best:%y%m%d}10L{inv.issue:%y%m}{line.no}"


def render_alfa(inv: Invoice) -> str:
    s = SUPPLIERS["alfa"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<Document>", "    <Type>Invoice</Type>",
           "    <Version>1</Version>", "    <Language>PL</Language>", "    <Faktura>", "        <Naglowek>"]
    head = [
        ("DostawcaNIP", "PL" + s["tax_id"]), ("DostawcaNazwa", s["name"]),
        ("DostawcaAdresKodPocztowy", "00-950"), ("DostawcaAdresMiejscowosc", "Przykładowo"),
        ("DostawcaAdresUlica", "ul. Testowa 1"), ("NabywcaNIP", "PL" + BUYER["nip"]), ("NabywcaNazwa", BUYER["name"]),
        ("NabywcaAdresKodPocztowy", BUYER["postcode"]), ("NabywcaAdresMiejscowosc", BUYER["city"]),
        ("NabywcaAdresUlica", BUYER["street"]), ("FakturaNumer", inv.number),
        ("FakturaDataWystawienia", inv.issue.isoformat()), ("FakturaDataPlatnosci", inv.due.isoformat()),
        ("FakturaTypPlatnosci", "Przelew"), ("FakturaWartoscNetto", inv.net), ("FakturaWartoscVat", inv.vat),
        ("FakturaWartoscBrutto", inv.gross), ("FakturaNumeryWZ", f"WZ-ALFA-{inv.number.rsplit('/', 1)[1]}"),
    ]
    out += [f"            <{t}>{_x(v)}</{t}>" for t, v in head]
    out += ["        </Naglowek>", "        <Pozycje>"]
    for ln in inv.lines:
        it = ln.item
        out += ["            <Pozycja>"]
        out += [f"                <{t}>{_x(v)}</{t}>" for t, v in [
            ("TowarKod", it.code), ("TowarKodEan", "010" + it.gtin), ("TowarKodEan128", _gs1(it, inv, ln)),
            ("TowarNazwa", it.name), ("TowarJm", ln.unit), ("Ilosc", ln.qty), ("CenaNetto", it.price),
            ("WartoscNetto", ln.net), ("StawkaVat", f"{it.vat}%"), ("WartoscVat", ln.vat),
            ("WartoscBrutto", ln.gross)]]
        out += ["            </Pozycja>"]
    out += ["        </Pozycje>", "    </Faktura>", "</Document>"]
    return "\n".join(out) + "\n"


def render_beta(inv: Invoice) -> str:
    s = SUPPLIERS["beta"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">',
        "  <Naglowek>",
        '    <KodFormularza kodSystemowy="FA (3)" wersjaSchemy="1-0E">FA</KodFormularza>',
        "    <WariantFormularza>3</WariantFormularza>",
        f"    <DataWytworzeniaFa>{inv.issue.isoformat()}T10:00:00Z</DataWytworzeniaFa>",
        "  </Naglowek>",
        "  <Podmiot1>",
        f"    <DaneIdentyfikacyjne><NIP>{s['tax_id']}</NIP><Nazwa>{_x(s['name'])}</Nazwa></DaneIdentyfikacyjne>",
        "    <Adres><KodKraju>PL</KodKraju><AdresL1>ul. Młyńska 5</AdresL1>"
        "<AdresL2>00-952 Przykładowo</AdresL2></Adres>",
        "  </Podmiot1>",
        "  <Podmiot2>",
        f"    <DaneIdentyfikacyjne><NIP>{BUYER['nip']}</NIP><Nazwa>{_x(BUYER['name'])}</Nazwa></DaneIdentyfikacyjne>",
        f"    <Adres><KodKraju>PL</KodKraju><AdresL1>{BUYER['street']}</AdresL1>"
        f"<AdresL2>{BUYER['postcode']} {BUYER['city']}</AdresL2></Adres>",
        "  </Podmiot2>",
        "  <Fa>",
        "    <KodWaluty>PLN</KodWaluty>",
        f"    <P_1>{inv.issue.isoformat()}</P_1>",
        f"    <P_2>{_x(inv.number)}</P_2>",
        f"    <P_13_1>{inv.net}</P_13_1>",
        f"    <P_14_1>{inv.vat}</P_14_1>",
        f"    <P_15>{inv.gross}</P_15>",
        "    <RodzajFaktury>VAT</RodzajFaktury>",
    ]
    for ln in inv.lines:
        it = ln.item
        out += ["    <FaWiersz>"]
        out += [f"      <{t}>{_x(v)}</{t}>" for t, v in [
            ("NrWierszaFa", ln.no), ("Indeks", it.code), ("GTIN", it.gtin), ("P_7", it.name), ("P_8A", ln.unit),
            ("P_8B", ln.qty), ("P_9A", it.price), ("P_11", ln.net), ("P_12", it.vat)]]
        out += ["    </FaWiersz>"]
    out += [
        "    <Platnosc>",
        f"      <TerminPlatnosci><Termin>{inv.due.isoformat()}</Termin></TerminPlatnosci>",
        "      <FormaPlatnosci>6</FormaPlatnosci>",
        "    </Platnosc>",
        "  </Fa>",
        "</Faktura>",
    ]
    return "\n".join(out) + "\n"


def render_eta(inv: Invoice) -> str:
    s = SUPPLIERS["eta"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<Invoice>",
        f"  <InvoiceNumber>{_x(inv.number)}</InvoiceNumber>",
        f"  <IssueDate>{inv.issue.isoformat()}</IssueDate>",
        f"  <DueDate>{inv.due.isoformat()}</DueDate>",
        "  <Currency>PLN</Currency>",
        "  <Seller>",
        f"    <SellerName>{_x(s['name'])}</SellerName>",
        f"    <SellerVAT>PL{s['tax_id']}</SellerVAT>",
        "    <Street>ul. Kartonowa 7</Street>",
        "    <City>Przykładowo</City>",
        "  </Seller>",
        "  <Buyer>",
        f"    <BuyerName>{_x(BUYER['name'])}</BuyerName>",
        f"    <BuyerVAT>PL{BUYER['nip']}</BuyerVAT>",
        "  </Buyer>",
        "  <Lines>",
    ]
    for ln in inv.lines:
        it = ln.item
        out += ["    <Line>"]
        out += [f"      <{t}>{_x(v)}</{t}>" for t, v in [
            ("ProductCode", it.code), ("GTIN", it.gtin), ("ProductName", it.name), ("Quantity", ln.qty),
            ("Unit", ln.unit), ("UnitPrice", it.price), ("NetAmount", ln.net), ("VatRate", it.vat)]]
        out += ["    </Line>"]
    out += [
        "  </Lines>",
        "  <Totals>",
        f"    <Net>{inv.net}</Net>",
        f"    <Vat>{inv.vat}</Vat>",
        f"    <Gross>{inv.gross}</Gross>",
        "  </Totals>",
        "</Invoice>",
    ]
    return "\n".join(out) + "\n"


def render_gamma(inv: Invoice) -> str:
    s = SUPPLIERS["gamma"]
    cur = "EUR"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"',
        '         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"',
        '         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">',
        "  <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID>",
        f"  <cbc:ID>{_x(inv.number)}</cbc:ID>",
        f"  <cbc:IssueDate>{inv.issue.isoformat()}</cbc:IssueDate>",
        f"  <cbc:DueDate>{inv.due.isoformat()}</cbc:DueDate>",
        "  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
        f"  <cbc:DocumentCurrencyCode>{cur}</cbc:DocumentCurrencyCode>",
        "  <cac:AccountingSupplierParty><cac:Party>",
        f"    <cac:PartyName><cbc:Name>{_x(s['name'])}</cbc:Name></cac:PartyName>",
        "    <cac:PostalAddress><cbc:StreetName>Beispielstraße 7</cbc:StreetName><cbc:CityName>Musterstadt"
        "</cbc:CityName><cbc:PostalZone>99999</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE"
        "</cbc:IdentificationCode></cac:Country></cac:PostalAddress>",
        f"    <cac:PartyTaxScheme><cbc:CompanyID>{s['tax_id']}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
        "</cac:TaxScheme></cac:PartyTaxScheme>",
        "  </cac:Party></cac:AccountingSupplierParty>",
        "  <cac:AccountingCustomerParty><cac:Party>",
        f"    <cac:PartyName><cbc:Name>{_x(BUYER['name'])}</cbc:Name></cac:PartyName>",
        f"    <cac:PostalAddress><cbc:StreetName>{BUYER['street']}</cbc:StreetName><cbc:CityName>{BUYER['city']}"
        f"</cbc:CityName><cbc:PostalZone>{BUYER['postcode']}</cbc:PostalZone><cac:Country><cbc:IdentificationCode>"
        "PL</cbc:IdentificationCode></cac:Country></cac:PostalAddress>",
        f"    <cac:PartyTaxScheme><cbc:CompanyID>PL{BUYER['nip']}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT"
        "</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>",
        "  </cac:Party></cac:AccountingCustomerParty>",
        f'  <cac:TaxTotal><cbc:TaxAmount currencyID="{cur}">{inv.vat}</cbc:TaxAmount></cac:TaxTotal>',
        "  <cac:LegalMonetaryTotal>",
        f'    <cbc:LineExtensionAmount currencyID="{cur}">{inv.net}</cbc:LineExtensionAmount>',
        f'    <cbc:TaxExclusiveAmount currencyID="{cur}">{inv.net}</cbc:TaxExclusiveAmount>',
        f'    <cbc:TaxInclusiveAmount currencyID="{cur}">{inv.gross}</cbc:TaxInclusiveAmount>',
        f'    <cbc:PayableAmount currencyID="{cur}">{inv.gross}</cbc:PayableAmount>',
        "  </cac:LegalMonetaryTotal>",
    ]
    for ln in inv.lines:
        it = ln.item
        out += [
            "  <cac:InvoiceLine>",
            f"    <cbc:ID>{ln.no}</cbc:ID>",
            f'    <cbc:InvoicedQuantity unitCode="{ln.unit}">{ln.qty}</cbc:InvoicedQuantity>',
            f'    <cbc:LineExtensionAmount currencyID="{cur}">{ln.net}</cbc:LineExtensionAmount>',
            "    <cac:Item>",
            f"      <cbc:Name>{_x(it.name)}</cbc:Name>",
            f"      <cac:SellersItemIdentification><cbc:ID>{it.code}</cbc:ID></cac:SellersItemIdentification>",
            f'      <cac:StandardItemIdentification><cbc:ID schemeID="0160">{it.gtin}</cbc:ID>'
            "</cac:StandardItemIdentification>",
            f"      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{it.vat}</cbc:Percent><cac:TaxScheme>"
            "<cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory>",
            "    </cac:Item>",
            f'    <cac:Price><cbc:PriceAmount currencyID="{cur}">{it.price}</cbc:PriceAmount></cac:Price>',
            "  </cac:InvoiceLine>",
        ]
    out += ["</Invoice>"]
    return "\n".join(out) + "\n"


def render_epsilon(inv: Invoice) -> str:
    s = SUPPLIERS["epsilon"]
    head = [f'    "number": "{inv.number}",', f'    "issue_date": "{inv.issue.isoformat()}",',
            f'    "due_date": "{inv.due.isoformat()}",']
    if not inv.spec.no_currency:
        head.append('    "currency": "GBP",')
    items = []
    for ln in inv.lines:
        it = ln.item
        items.append(
            f'      {{"sku": "{it.code}", "ean": "{it.gtin}", "description": "{it.name}", "quantity": {ln.qty}, '
            f'"uom": "{ln.unit}",\n       "unit_price": {it.price}, "net_amount": {ln.net}, "vat_rate": {it.vat}}}')
    out = ["{", '  "invoice": {', *head,
           '    "seller": {',
           f'      "name": "{s["name"]}",',
           f'      "vat_number": "{s["tax_id"]}",',
           '      "address": {"street": "1 Example Street", "city": "Testford", "postcode": "TF1 1AA"}',
           "    },",
           '    "buyer": {"name": "Piekarnia Demo Ltd", "vat_number": "GB999000055"},',
           f'    "totals": {{"net": {inv.net}, "vat": {inv.vat}, "gross": {inv.gross}}},',
           '    "items": [',
           ",\n".join(items),
           "    ]",
           "  }",
           "}"]
    return "\n".join(out) + "\n"


def _pl(value) -> str:
    return str(value).replace(".", ",")


def render_zeta(inv: Invoice) -> str:
    s = SUPPLIERS["zeta"]
    cols = ["NrFaktury", "DataWystawienia", "Waluta", "SprzedawcaNIP", "SprzedawcaNazwa", "Kod", "Nazwa", "EAN",
            "Ilosc", "JM", "CenaNetto", "WartoscNetto", "StawkaVAT", "WartoscVAT", "WartoscBrutto", "RazemNetto",
            "RazemVAT", "RazemBrutto"]
    rows = [";".join(cols)]
    for ln in inv.lines:
        it = ln.item
        rows.append(";".join(str(v) for v in [
            inv.number, f"{inv.issue:%d.%m.%Y}", "PLN", s["tax_id"], s["name"], it.code, it.name, it.gtin, ln.qty,
            ln.unit, _pl(it.price), _pl(ln.net), it.vat, _pl(ln.vat), _pl(ln.gross), _pl(inv.net), _pl(inv.vat),
            _pl(inv.gross)]))
    return "\n".join(rows) + "\n"


RENDERERS = {"alfa": render_alfa, "beta": render_beta, "eta": render_eta, "gamma": render_gamma,
             "epsilon": render_epsilon, "zeta": render_zeta}


# ------------------------------------------------------------------------------------------------------------------
# Zestaw: pliki, manifest, README
# ------------------------------------------------------------------------------------------------------------------

def filename(order: int, spec: Spec) -> str:
    return f"{order:02d}-{spec.supplier}-{spec.k}{spec.suffix}.{SUPPLIERS[spec.supplier]['format']}"


def _expected(t: tuple | None) -> dict | None:
    if t is None:
        return None
    status, blocking, warnings = t
    return {"status": status, "blocking": sorted(set(blocking)), "warnings": sorted(set(warnings))}


def build() -> tuple[dict[str, bytes], dict]:
    """Treść wszystkich plików zestawu (nazwa → bajty) i manifest. Bez zapisu na dysk."""
    rng = random.Random(SEED)
    files: dict[str, bytes] = {}
    entries = []
    by_order: dict[int, str] = {}
    for order, spec in enumerate(SPECS, start=1):
        name = filename(order, spec)
        if spec.copy_of is not None:
            original = by_order[spec.copy_of]
            data = files[original]
        else:
            original = None
            data = RENDERERS[spec.supplier](build_invoice(spec, order, rng)).encode("utf-8")
        files[name] = data
        by_order[order] = name
        entries.append({
            "order": order,
            "filename": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "supplier": spec.supplier,
            "format": SUPPLIERS[spec.supplier]["format"],
            "phase": spec.phase,
            "shows": spec.shows,
            "expected": {"on_ingest": _expected(spec.on_ingest), "after_resolve": _expected(spec.after_resolve)},
            "duplicate_of": original,
        })
    manifest = {
        "version": 1,
        "title": "Miesiąc faktur",
        "generator": {"tool": TOOL_PATH, "seed": SEED},
        "suppliers": {k: dict(v) for k, v in SUPPLIERS.items()},
        "files": entries,
    }
    files[MANIFEST] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    files[README] = render_readme(manifest).encode("utf-8")
    return files, manifest


STATUS_PL = {"approved": "zatwierdzona", "needs_review": "do przejrzenia", "duplicate": "duplikat"}


def _outcome(e: dict | None) -> str:
    if e is None:
        return "—"
    codes = [f"`{c}`" for c in e["blocking"]] + [f"`{c}` (ostrzeżenie)" for c in e["warnings"]]
    return STATUS_PL[e["status"]] + (": " + ", ".join(codes) if codes else "")


def render_readme(manifest: dict) -> str:
    sup = manifest["suppliers"]
    out = [
        "# Zestaw demo „Miesiąc faktur”",
        "",
        "<!-- Wygenerowano przez tools/gen_demo_dataset.py — nie edytuj ręcznie. -->",
        "",
        "Miesiąc pracy działu zakupów fikcyjnej „Piekarni Demo”: 24 faktury od sześciu dostawców z października "
        "2026 w trzech formatach (XML, JSON, CSV). Pierwsza faktura każdego dostawcy wymaga negocjacji, kolejne "
        "przechodzą automatycznie albo pokazują jedną nową pułapkę (nowa jednostka, nowy towar, brak waluty, "
        "niezgodność sumy, duplikat). Wszystkie dane (firmy, NIP/VAT, adresy, numery, GTIN) są **fikcyjne**.",
        "",
        "Plik `manifest.json` opisuje każdy plik i oczekiwany wynik: `on_ingest` — status i kody problemów zaraz "
        "po wczytaniu (w kolejności `order`, na świeżej bazie z kartoteką demo), `after_resolve` — po wybraniu "
        "pierwszej podpowiedzi przy każdym problemie (z „zapamiętaj w szablonie”). Zgodność manifestu z "
        "zachowaniem parsera sprawdza `tests/test_demo_dataset_files.py`.",
        "",
        "## Dostawcy",
        "",
        "| Klucz | Dostawca | NIP/VAT | Format |",
        "|---|---|---|---|",
    ]
    out += [f"| {k} | {s['name']} | {s['tax_id']} | {s['format'].upper()} |" for k, s in sup.items()]
    out += [
        "",
        "## Pliki",
        "",
        "| Nr | Plik | Dostawca | Co pokazuje | Po wczytaniu | Po pierwszych podpowiedziach |",
        "|---|---|---|---|---|---|",
    ]
    for f in manifest["files"]:
        out.append(f"| {f['order']} | {f['filename']} | {sup[f['supplier']]['name']} | {f['shows']} | "
                   f"{_outcome(f['expected']['on_ingest'])} | {_outcome(f['expected']['after_resolve'])} |")
    out += [
        "",
        "Wczytanie wszystkiego naraz bez nauki: pliki 01–19 i 21–24 trafiają do kolejki (nieznany dostawca), "
        "plik 20 jest duplikatem pliku 14.",
        "",
        "## Regeneracja",
        "",
        "```",
        ".venv/bin/python tools/gen_demo_dataset.py          # zapisuje pliki do demo/dataset/",
        ".venv/bin/python tools/gen_demo_dataset.py --check  # kod 0, gdy pliki są aktualne",
        "```",
        "",
        f"Generator jest deterministyczny (ziarno {manifest['generator']['seed']} losuje tylko ilości): ta sama "
        "wersja daje te same bajty, więc pliki są commitowane, a test pilnuje, że nikt ich nie zmienił ręcznie.",
    ]
    return "\n".join(out) + "\n"


def generate(out_dir: Path | str = DEFAULT_OUT) -> dict:
    """Zapisuje zestaw do `out_dir` (pliki faktur, manifest, README). Zwraca manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files, manifest = build()
    for name, data in files.items():
        (out / name).write_bytes(data)
    return manifest


def load(out_dir: Path | str = DEFAULT_OUT) -> dict:
    """Manifest zestawu z katalogu `out_dir`."""
    return json.loads((Path(out_dir) / MANIFEST).read_text(encoding="utf-8"))


def check(out_dir: Path | str = DEFAULT_OUT) -> list[str]:
    """Różnice między katalogiem a świeżą regeneracją (puste = aktualne)."""
    out = Path(out_dir)
    with tempfile.TemporaryDirectory() as tmp:
        generate(tmp)
        fresh = {p.name: p.read_bytes() for p in Path(tmp).iterdir() if p.is_file()}
    current = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} if out.is_dir() else {}
    problems = [f"brak pliku: {n}" for n in sorted(set(fresh) - set(current))]
    problems += [f"nadmiarowy plik: {n}" for n in sorted(set(current) - set(fresh))]
    problems += [f"inna treść: {n}" for n in sorted(set(fresh) & set(current)) if fresh[n] != current[n]]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generator zestawu demo „Miesiąc faktur”.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="katalog wyjściowy (domyślnie demo/dataset)")
    parser.add_argument("--check", action="store_true",
                        help="nie zapisuj — sprawdź, czy pliki w katalogu są identyczne z regeneracją")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print("Zestaw nieaktualny — uruchom: .venv/bin/python tools/gen_demo_dataset.py", file=sys.stderr)
            return 1
        print("Zestaw aktualny.")
        return 0
    manifest = generate(args.out)
    print(f"Zapisano {len(manifest['files'])} faktur, manifest i README do {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
