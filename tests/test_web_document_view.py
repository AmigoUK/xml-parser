"""Widok dokumentu i karty problemów (v0.7.1, T9): powrót do listy, formaty kwot, etykiety pól, potwierdzenie
odrzucenia. Wyłącznie fikcyjne dane."""
import re

from app.extensions import db
from app.models import Document


def _issue(code, **kw):
    base = {"code": code, "severity": "blocking", "message": f"Problem {code}", "field": None, "line_no": None,
            "source_path": None, "source_value": None, "suggestions": [], "count": 1, "line_nos": []}
    base.update(kw)
    return base


ALL_ISSUES = [
    _issue("unknown_supplier"),
    _issue("unmapped_field", field="currency", suggestions=[{"kind": "value", "value": "PLN", "confidence": 0.5,
                                                              "reason": "test"}]),
    _issue("unmapped_field", field="number"),
    _issue("unknown_unit", source_value="kar"),
    _issue("missing_conversion", source_value="kar", line_no=1),
    _issue("unmapped_product", line_no=1),
    _issue("duplicate"),
]


def _doc(status="needs_review", issues=None, **kw):
    totals = {"net": "1234567.5", "vat": "0", "gross": "1234567.5"}
    result = {"number": "FV/1/2026", "currency": "PLN", "totals": totals,
              "lines": [{"line_no": 1, "name": "Mleko", "qty": "12.5000", "unit": "szt", "unit_price_net": "3.1",
                         "net": "1234.5", "conversion_factor": "1.2500", "unit_source": "kar"}]}
    doc = Document(filename="faktura-alfa-z-bardzo-dlugą-nazwą.xml", sha256="a" * 64, fmt="xml", status=status,
                   issues=issues if issues is not None else [], result=result, **kw)
    db.session.add(doc)
    db.session.commit()
    return doc.id


def _page(auth_client, **kw):
    return auth_client.get(f"/dokumenty/{_doc(**kw)}").get_data(as_text=True)


def test_back_link_targets_queue_or_documents_by_status(auth_client):
    review = _page(auth_client, status="needs_review")
    assert "← Wróć do kolejki" in review and 'href="/kolejka"' in review
    approved = _page(auth_client, status="approved")
    assert "← Wróć do dokumentów" in approved and "Wróć do kolejki" not in approved


def test_money_and_qty_formatting_and_text_end(auth_client):
    html = _page(auth_client)
    assert "1 234 567,50" in html
    assert "12,5" in html and "12,5000" not in html
    assert re.search(r'<td class="text-end">1 234 567,50</td>', html)
    assert re.search(r'<th class="text-end">Wartość netto</th>', html)


def test_remember_checkboxes_have_unique_ids_with_labels(auth_client):
    html = _page(auth_client, issues=ALL_ISSUES)
    ids = re.findall(r'<input[^>]*type="checkbox"[^>]*\bid="([^"]+)"', html)
    assert len(ids) >= 4 and len(ids) == len(set(ids))
    for i in ids:
        assert f'for="{i}"' in html
    assert "remember-0-" not in html and re.search(r"remember-\d+-map_field", html)


def test_issue_controls_have_labels_or_aria_labels(auth_client):
    html = _page(auth_client, issues=ALL_ISSUES + [_issue("unmapped_product", line_no=2)])
    labelled = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    controls = [m for m in re.findall(r"<(?:input|select)\b[^>]*>", html) if 'type="hidden"' not in m]
    assert controls
    for tag in controls:
        m = re.search(r'\bid="([^"]+)"', tag)
        assert "aria-label=" in tag or (m and m.group(1) in labelled), tag


def test_factor_input_is_decimal_inputmode(auth_client):
    html = _page(auth_client, issues=ALL_ISSUES)
    tag = re.search(r'<input[^>]*name="factor"[^>]*>', html).group(0)
    assert 'inputmode="decimal"' in tag


def test_reject_form_has_confirm(auth_client):
    html = _page(auth_client, issues=[_issue("duplicate")])
    assert 'data-confirm="Odrzucić dokument? Cofnąć to może tylko „Przywróć”."' in html
    assert html.count("data-confirm=") == 1
    # ta sama próbka drugi raz: potwierdzenie nie zależy od stanu
    html2 = _page(auth_client, issues=[_issue("duplicate")])
    assert 'data-confirm="Odrzucić dokument? Cofnąć to może tylko „Przywróć”."' in html2


def test_scroll_pane_replaces_inline_style(auth_client):
    html = _page(auth_client)
    assert "max-height: 70vh" not in html and "scroll-pane" in html
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.scroll-pane\s*\{[^}]*max-height", css)


def test_no_inline_js_on_document_page(auth_client):
    html = _page(auth_client, issues=ALL_ISSUES)
    assert not re.search(r"<[^>]+\son[a-z]+\s*=", html)
    assert not re.search(r"<script\b(?![^>]*\bsrc=)", html)
