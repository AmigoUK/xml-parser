"""Pakiet C audytu — liczby w pipeline, negocjacji, edytorze i CRUD (fikcyjne dane)."""
from decimal import Decimal

from app.models import Template, Unit, UnitConversion
from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes

CSV = ("NrFaktury;DataWystawienia;Waluta;SprzedawcaNIP;SprzedawcaNazwa;Kod;Nazwa;Ilosc;JM;CenaNetto;"
       "WartoscNetto;StawkaVAT;WartoscVAT;WartoscBrutto;RazemNetto;RazemVAT;RazemBrutto\n"
       "T/1/2026;09.10.2026;PLN;9990000077;Testowa Hurtownia;T-1;Mąka testowa;1,234;kg;10;12;23;3;15;12;3;15\n")


def codes(doc):
    return [i["code"] for i in doc.issues]


def test_ambiguous_quantity_blocks_and_suggests_separator(seeded):
    d = ingest(CSV.encode(), "t.csv")
    resolve(d, "create_supplier", {"name": "Testowa Hurtownia", "tax_id": "9990000077"}, True, "admin")
    amb = [i for i in d.issues if i["code"] == "ambiguous_number"]
    assert len(amb) == 1 and amb[0]["severity"] == "blocking" and amb[0]["field"] == "qty"
    assert d.status == "needs_review"
    seps = [s["transforms"] for s in amb[0]["suggestions"]]
    assert [{"decimal": ","}] in seps and [{"decimal": "."}] in seps
    previews = {s["transforms"][0]["decimal"]: s["preview"] for s in amb[0]["suggestions"]}
    assert previews == {",": "1.234", ".": "1234"}
    choice = next(s for s in amb[0]["suggestions"] if s["transforms"] == [{"decimal": ","}])
    resolve(d, "map_field", {"field": "qty", "path": choice["path"], "transforms": choice["transforms"]},
            True, "admin")
    assert "ambiguous_number" not in codes(d)
    assert d.result["lines"][0]["qty"] == "1.234"


def test_ambiguous_issue_renders_resolution_form(auth_client):
    d = ingest(CSV.encode(), "t.csv")
    resolve(d, "create_supplier", {"name": "Testowa Hurtownia", "tax_id": "9990000077"}, True, "admin")
    html = auth_client.get(f"/dokumenty/{d.id}").get_data(as_text=True)
    assert "Niejednoznaczna liczba" in html
    assert 'value="map_field"' in html and "separator dziesiętny: przecinek" in html


def test_demo_samples_have_no_new_number_problems(seeded):
    for name in ("alfa-1.xml", "alfa-2.xml", "beta-ksef.xml", "gamma-ubl.xml", "delta.csv", "epsilon.json"):
        d = ingest(sample_bytes(name), name)
        bad = [c for c in codes(d) if c in ("ambiguous_number", "vat_rate_fraction")]
        bad += [i["code"] for i in d.issues if i.get("field") == "currency" and i["code"] == "invalid_value"]
        assert bad == [], (name, bad)


def _editor_save(auth_client, transforms):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    rules = Template.query.one().active_version.rules
    lines = {**rules["lines"], "qty": {"path": rules["lines"]["qty"]["path"], "transforms": transforms}}
    return auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": {**rules, "lines": lines}})


def test_editor_rejects_non_positive_convert(auth_client):
    for bad in ([{"convert": "0"}], [{"convert": 0}], [{"convert": -1}], [{"convert": "-2"}],
                [{"convert": "1,000"}], [{"decimal": ";"}], [{"decimal": 5}]):
        r = _editor_save(auth_client, bad)
        assert r.status_code == 400, bad
        # szablon zostaje jeden: ten sam plik i dostawca → _attach_supplier używa istniejącego; bulk DELETE szablonów
        # naruszałby klucze obce dokumentów i wersji (SQLite z PRAGMA foreign_keys=ON odrzuca go jak MariaDB)


def test_editor_accepts_exponent_convert_and_decimal_separator(auth_client):
    r = _editor_save(auth_client, [{"decimal": ","}, {"convert": "1e3"}])
    assert r.status_code == 200, r.get_data(as_text=True)


def test_crud_conversion_factor_exponent(auth_client):
    kg, szt = Unit.query.filter_by(code="kg").one(), Unit.query.filter_by(code="szt").one()
    r = auth_client.post("/przeliczniki/nowy", data={"from_unit_id": szt.id, "factor": "1e3",
                                                     "to_unit_id": kg.id, "supplier_id": "", "product_id": ""})
    assert r.status_code == 302
    assert UnitConversion.query.order_by(UnitConversion.id.desc()).first().factor == Decimal("1000")
