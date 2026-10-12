"""Pakiet B audytu: limity wczytywania (SEC-1), agregacja problemów (EDGE-5),
wybór grupy pozycji (EDGE-4) i znaki sterujące w CSV (EDGE-12). Wyłącznie fikcyjne dane."""
import json
import re
import time

import pytest

from app.engine.tree import Node, SourceTree
from app.ingest import ReaderError, read_document
from tests.conftest import sample_bytes

API = {"X-API-Key": "xp_test_demo_key"}


def _post(client, body: bytes):
    return client.post("/api/v1/documents", data=body, headers=API)


# ---------------------------------------------------------------- SEC-1


def _many_groups(n: int) -> SourceTree:
    root = Node("root")
    for i in range(n):
        for _ in range(2):
            g = root.add(Node(f"k{i}"))
            g.add(Node("x", "1"))
    return SourceTree(root, "json")


def test_detect_line_group_is_not_quadratic():
    tree = _many_groups(20000)
    t = time.perf_counter()
    tree.detect_line_group()
    assert time.perf_counter() - t < 2.0


def test_wide_json_1mb_processed_under_5s(seeded, client):
    body = json.dumps({f"grupa_powtarzalna_{i:06d}": [{"pole_a": "wartosc", "pole_b": 1},
                                                       {"pole_a": "x", "pole_b": 2}] for i in range(12000)}).encode()
    assert len(body) > 1_000_000
    t = time.perf_counter()
    r = _post(client, body)
    assert time.perf_counter() - t < 5.0
    assert r.status_code == 201


def test_wide_xml_1mb_processed_under_5s(seeded, client):
    body = b"<a>" + b"".join(b"<g%d><v>1</v></g%d><g%d><v>2</v></g%d>" % (i, i, i, i)
                             for i in range(30000)) + b"</a>"
    assert len(body) > 1_000_000
    t = time.perf_counter()
    r = _post(client, body)
    assert time.perf_counter() - t < 5.0
    assert r.status_code == 201


@pytest.mark.parametrize("body", [
    b"[" + b",".join([b"0"] * 3000) + b"]",
    b"<a>" + b"<b>1</b>" * 3000 + b"</a>",
    b"<a>" + b'<b x="1" y="2"/>' * 1000 + b"</a>",
    b"kol1;kol2\n" + b"1;2\n" * 2000,
], ids=["json", "xml", "xml-attrs", "csv"])
def test_tree_node_limit_raises_reader_error(app, body):
    app.config["MAX_TREE_NODES"] = 2000
    with pytest.raises(ReaderError, match="zbyt wiele elementów"):
        read_document(body)


def test_tree_node_limit_default_is_200k(app):
    assert app.config["MAX_TREE_NODES"] == 200_000
    assert app.config["MAX_LINES"] == 5_000


def test_tree_node_limit_rejects_via_api_not_500(seeded, client):
    client.application.config["MAX_TREE_NODES"] = 1000
    r = _post(client, b"[" + b",".join([b"0"] * 5000) + b"]")
    assert r.status_code == 201
    js = r.get_json()
    assert js["status"] == "rejected"
    assert "zbyt wiele elementów" in js["issues"][0]["message"]


def _ksef(n_lines: int, tax_id: str = "9990000777") -> bytes:
    ksef = sample_bytes("beta-ksef.xml").decode()
    line = re.search(r"(<FaWiersz>.*?</FaWiersz>)", ksef, flags=re.S).group(1)
    lines = "".join(line.replace("<NrWierszaFa>1<", f"<NrWierszaFa>{i}<") for i in range(1, n_lines + 1))
    return re.sub(r"<FaWiersz>.*</FaWiersz>", lines, ksef, flags=re.S).replace("9990000022", tax_id).encode()


def test_too_many_lines_rejected_with_polish_message(seeded, client):
    client.application.config["MAX_LINES"] = 5
    r = _post(client, _ksef(6))
    assert r.status_code == 201
    js = r.get_json()
    assert js["status"] == "rejected"
    assert js["issues"][0]["code"] == "too_many_lines"
    assert "6" in js["issues"][0]["message"] and "5" in js["issues"][0]["message"]


def test_lines_at_limit_still_processed(seeded, client):
    client.application.config["MAX_LINES"] = 5
    js = _post(client, _ksef(5)).get_json()
    assert js["status"] != "rejected"
    assert len(js["invoice"]["lines"]) == 5


# ---------------------------------------------------------------- EDGE-5


def test_repeated_missing_conversion_aggregated(seeded, client):
    js = _post(client, _ksef(40)).get_json()
    conv = [i for i in js["issues"] if i["code"] == "missing_conversion"]
    assert len(conv) == 1
    assert conv[0]["count"] == 40
    assert conv[0]["line_no"] == 1
    assert conv[0]["line_nos"][:3] == [1, 2, 3]
    assert len(conv[0]["line_nos"]) <= 20
    assert "40 pozycji" in conv[0]["message"]


def test_detail_page_renders_limited_issue_cards(auth_client):
    from app.extensions import db
    from app.models import Document
    js = _post(auth_client, _ksef(3)).get_json()
    doc = db.session.get(Document, js["id"])
    issue = {"code": "unmapped_product", "severity": "blocking", "message": "Pozycja X: brak towaru",
             "field": "product_index", "line_no": 1, "source_path": None, "source_value": None,
             "suggestions": [], "count": 1, "line_nos": [1]}
    doc.issues = [dict(issue, message=f"Pozycja {n}: brak towaru-znacznik") for n in range(1, 301)]
    db.session.commit()
    html = auth_client.get(f"/dokumenty/{doc.id}").get_data(as_text=True)
    assert html.count("brak towaru-znacznik") == 50
    assert "Pokazano 50 z 300" in html


def test_detail_page_size_bounded_for_many_lines(auth_client):
    auth_client.application.config["MAX_LINES"] = 2000
    js = _post(auth_client, _ksef(1500)).get_json()
    r = auth_client.get(f"/dokumenty/{js['id']}")
    assert r.status_code == 200
    assert len(r.data) < 3_000_000


# ---------------------------------------------------------------- EDGE-4


def _ksef_one_line() -> str:
    ksef = sample_bytes("beta-ksef.xml").decode()
    return re.sub(r"<FaWiersz>\s*<NrWierszaFa>2</NrWierszaFa>.*?</FaWiersz>", "", ksef, flags=re.S)


def test_ksef_one_line_with_two_payment_terms():
    one = _ksef_one_line()
    term = "<TerminPlatnosci><Termin>2026-10-22</Termin></TerminPlatnosci>"
    assert term in one
    two = one.replace(term, term + term.replace("2026-10-22", "2026-11-22"))
    assert read_document(two.encode()).detect_line_group().endswith("/FaWiersz")


def test_ubl_one_line_with_two_document_references():
    ubl = sample_bytes("gamma-ubl.xml").decode()
    parts = ubl.split("<cac:InvoiceLine>")
    ubl1 = parts[0] + "<cac:InvoiceLine>" + parts[1].split("</cac:InvoiceLine>")[0] + "</cac:InvoiceLine>\n</Invoice>"
    refs = ("<cac:AdditionalDocumentReference><cbc:ID>WZ/1</cbc:ID></cac:AdditionalDocumentReference>"
            "<cac:AdditionalDocumentReference><cbc:ID>WZ/2</cbc:ID></cac:AdditionalDocumentReference>")
    assert "<cac:TaxTotal>" in ubl1
    t = read_document(ubl1.replace("<cac:TaxTotal>", refs + "<cac:TaxTotal>", 1).encode())
    assert t.detect_line_group() == "Invoice/InvoiceLine"


def test_json_one_product_with_two_payments():
    js = (b'{"number":"X1","payments":[{"d":"2026-01-01","a":1},{"d":"2026-02-01","a":1}],'
          b'"products":[{"sku":"A","qty":1}]}')
    assert read_document(js).detect_line_group() == "root/products"


def test_json_single_product_under_unhinted_key():
    js = b'{"number":"X1","issue_date":"2026-01-01","currency":"PLN","products":[{"sku":"A","qty":1}]}'
    assert read_document(js).detect_line_group() == "root/products"


def test_learned_line_path_preferred():
    js = b'{"number":"X1","pay":[{"d":"1","a":1},{"d":"2","a":1}],"towary":[{"t":"A"}]}'
    t = read_document(js)
    assert t.detect_line_group(learned_paths={"root/towary"}) == "root/towary"


def test_pipeline_draft_uses_line_group_for_one_line(seeded):
    from app.services.pipeline import ingest
    one = _ksef_one_line()
    term = "<TerminPlatnosci><Termin>2026-10-22</Termin></TerminPlatnosci>"
    two = one.replace(term, term + term.replace("2026-10-22", "2026-11-22")).replace("9990000022", "9990000777")
    doc = ingest(two.encode(), "k1.xml")
    assert doc.draft_rules["line_path"].endswith("/FaWiersz")
    assert len(doc.result["lines"]) == 1


# ---------------------------------------------------------------- EDGE-12


@pytest.mark.parametrize("rows", [2, 3, 30])
def test_csv_with_gs1_group_separator_is_not_binary(rows):
    body = "NrFaktury;Kod;GS1\n" + "".join(f"F/1;A{i};0105909999000013\x1d10ABC\x1d17261231\n" for i in range(rows))
    t = read_document(body.encode())
    assert t.fmt == "csv"
    assert "\x1d" in t.values("csv/row/GS1")[0]


def test_real_binary_still_rejected():
    with pytest.raises(ReaderError, match="binarny"):
        read_document(bytes(range(1, 32)) * 50)
