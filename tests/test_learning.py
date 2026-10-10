"""Kryterium sukcesu specu: pierwsza faktura → negocjacja, kolejna tego dostawcy → automatycznie."""
import pytest

from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def resolve_with_top_suggestions(doc, fallback_factor="12", max_steps=25):
    """Symuluje operatora, który zawsze wybiera pierwszą podpowiedź i „zapamiętaj”."""
    for _ in range(max_steps):
        blocking = [i for i in doc.issues if i["severity"] == "blocking"]
        if not blocking:
            return doc
        i = blocking[0]
        sug = i["suggestions"]
        code = i["code"]
        if code == "unknown_supplier":
            s = next(x for x in sug if x["kind"] == "create_supplier")
            resolve(doc, "create_supplier", {"name": s["name"], "tax_id": s["tax_id"]}, True, "test")
        elif code in ("unmapped_field", "transform_error", "invalid_value"):
            s = sug[0]
            data = ({"field": i["field"], "path": s["path"], "transforms": s.get("transforms", [])}
                    if s["kind"] in ("path", "line_path") else {"field": i["field"], "value": s["value"]})
            resolve(doc, "map_field", data, True, "test")
        elif code == "unknown_unit":
            resolve(doc, "map_unit", {"alias": i["source_value"], "unit": sug[0]["unit"]}, True, "test")
        elif code == "missing_conversion":
            g = sug[0]
            resolve(doc, "add_conversion", {"from_unit": g["from_unit"], "to_unit": g["to_unit"],
                                            "factor": g["factor"] or fallback_factor, "scope": "supplier"},
                    True, "test")
        elif code == "unmapped_product":
            s = sug[0]
            if s["kind"] == "product":
                resolve(doc, "map_product", {"line_no": i["line_no"], "product_code": s["code"]}, True, "test")
            else:
                resolve(doc, "create_product", {"line_no": i["line_no"], "code": s["code"], "name": s["name"],
                                                "unit": s["unit"] or "szt"}, True, "test")
        else:
            pytest.fail(f"Nieobsłużony problem: {i}")
    pytest.fail(f"Nie udało się rozwiązać problemów: {doc.issues}")


@pytest.mark.parametrize("name,second", [
    ("alfa-1.xml", None),
    ("beta-ksef.xml", (b"FV/B/1024/2026", b"FV/B/1025/2026")),
    ("gamma-ubl.xml", (b"GAM-2026-0315", b"GAM-2026-0316")),
    ("delta.csv", (b"D/77/2026", b"D/78/2026")),
    ("epsilon.json", (b"E-2026-0042", b"E-2026-0043")),
])
def test_first_invoice_negotiated_next_one_automatic(seeded, name, second):
    first = ingest(sample_bytes(name), name)
    assert first.status == "needs_review"
    resolve_with_top_suggestions(first)
    assert first.status == "approved", first.issues

    data = sample_bytes("alfa-2.xml") if second is None else sample_bytes(name).replace(*second)
    nxt = ingest(data, "kolejna-" + name)
    assert nxt.status == "approved", nxt.issues
    assert nxt.supplier_id == first.supplier_id
    assert nxt.template_id == first.template_id
    assert not [i for i in nxt.issues if i["severity"] == "blocking"]


def test_learning_alfa_details(seeded):
    d1 = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve_with_top_suggestions(d1)
    d2 = ingest(sample_bytes("alfa-2.xml"), "alfa-2.xml")
    l1 = d2.result["lines"][0]
    assert (l1["product_index"], l1["unit"], l1["unit_source"], l1["batch"], l1["expiry_date"]) == \
        ("TOW-0001", "szt", "pcs", "L2607", "2027-07-15")
    assert d2.result["currency"] == "PLN"


def test_conversions_applied(seeded):
    beta = ingest(sample_bytes("beta-ksef.xml"), "b.xml")
    resolve_with_top_suggestions(beta)
    l1 = beta.result["lines"][0]
    assert (l1["qty"], l1["unit"], l1["unit_price_net"], l1["conversion_factor"]) == ("500", "kg", "1.60", "25")
    delta = ingest(sample_bytes("delta.csv"), "d.csv")
    resolve_with_top_suggestions(delta)
    l1 = delta.result["lines"][0]
    assert (l1["qty"], l1["unit"], l1["unit_price_net"]) == ("24", "szt", "8.00")
