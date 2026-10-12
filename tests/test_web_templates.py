from app.extensions import db
from app.models import Document, Template
from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def make_doc_with_template():
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    return d


def test_list_detail_and_diff(auth_client):
    d = make_doc_with_template()
    resolve(d, "map_field", {"field": "currency", "value": "PLN"}, True, "admin")
    t = Template.query.one()
    assert "Hurtownia Alfa" in auth_client.get("/szablony").get_data(as_text=True)
    v1, v2 = t.versions
    html = auth_client.get(f"/szablony/{t.id}?a={v1.id}&b={v2.id}").get_data(as_text=True)
    assert "+" in html and "PLN" in html and "v2" in html


def test_restore_creates_new_version(auth_client):
    d = make_doc_with_template()
    resolve(d, "map_field", {"field": "currency", "value": "PLN"}, True, "admin")
    t = Template.query.one()
    v1 = t.versions[0]
    auth_client.post(f"/szablony/{t.id}/przywroc/{v1.id}")
    db.session.refresh(t)
    assert t.active_version.version == 3 and t.active_version.rules == v1.rules
    assert "Przywrócono wersję 1" in t.active_version.comment


def test_editor_renders_full_screen_without_footer(auth_client):
    d = make_doc_with_template()
    html = auth_client.get(f"/szablony/dokument/{d.id}/edytor").get_data(as_text=True)
    assert "Edytor mapowań" in html and "TowarKodEan128" in html
    assert "Project &amp; Development" not in html


def test_preview_and_save(auth_client):
    d = make_doc_with_template()
    rules = Template.query.one().active_version.rules
    rules = {**rules, "defaults": {"currency": "EUR"}}
    r = auth_client.post(f"/szablony/dokument/{d.id}/podglad", json={"rules": rules})
    body = r.get_json()
    assert r.status_code == 200 and body["invoice"]["currency"] == "EUR"
    assert all(i["field"] != "currency" for i in body["issues"])
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": rules, "comment": "Waluta EUR"})
    assert r.get_json()["ok"] is True
    t = Template.query.one()
    assert t.active_version.version == 2 and t.active_version.comment == "Waluta EUR"
    assert db.session.get(Document, d.id).result["currency"] == "EUR"


def test_preview_rejects_bad_rules(auth_client):
    d = make_doc_with_template()
    r = auth_client.post(f"/szablony/dokument/{d.id}/podglad", json={"rules": "nie-słownik"})
    assert r.status_code == 400


def test_delete_blocked_when_documents(auth_client):
    make_doc_with_template()
    t = Template.query.one()
    r = auth_client.post(f"/szablony/{t.id}/usun", follow_redirects=True)
    assert "Nie można usunąć" in r.get_data(as_text=True)


def test_save_rejects_unknown_transform_and_bad_regex(auth_client):
    d = make_doc_with_template()
    rules = Template.query.one().active_version.rules
    for bad in (["__import__"], [{"regex_extract": {"pattern": "("}}], [{"regex_extract": {"pattern": "a" * 500}}],
                [{"trim": 1, "upper": 2}], "trim"):
        r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz",
                             json={"rules": {**rules, "header": {"currency": {"path": "x", "transforms": bad}}}})
        assert r.status_code == 400 and r.get_json()["error"]
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": {**rules, "header": "x"}, "comment": 5})
    assert r.status_code == 400
    assert Template.query.one().active_version.version == 1


def test_views_require_login(client):
    assert client.get("/szablony").status_code in (302, 401)
    assert client.post("/szablony/dokument/1/zapisz", json={}).status_code in (302, 400, 401)


def test_editor_config_json_is_escaped(auth_client):
    d = make_doc_with_template()
    html = auth_client.get(f"/szablony/dokument/{d.id}/edytor").get_data(as_text=True)
    # konfiguracja w bloku danych JSON (nie w atrybucie x-data): tojson ucieka „<”, więc „</script>” z wartości
    # dokumentu nie wybije się z bloku; komponent Alpine (build CSP) czyta blok po id
    assert 'x-data="editor"' in html
    block = html.split('<script type="application/json" id="editor-config">', 1)[1].split("</script>", 1)[0]
    assert '"docId"' in block and "<" not in block and ">" not in block


def test_save_rejects_bad_transform_args(auth_client):
    d = make_doc_with_template()
    rules = Template.query.one().active_version.rules
    for bad in ([{"map": 5}], [{"convert": "x"}], [{"split": {"index": "a"}}], [{"concat": 3}], [{"date": 4}]):
        r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz",
                             json={"rules": {**rules, "header": {"currency": {"path": "x", "transforms": bad}}}})
        assert r.status_code == 400, bad
    assert len(Template.query.one().versions) == 1


def test_csrf_enforced_on_json_endpoints(app, auth_client):
    d = make_doc_with_template()
    rules = Template.query.one().active_version.rules
    app.config["WTF_CSRF_ENABLED"] = True
    url = f"/szablony/dokument/{d.id}/podglad"
    assert auth_client.post(url, json={"rules": rules}).status_code == 400
    import re
    page = auth_client.get(f"/szablony/dokument/{d.id}/edytor").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    assert auth_client.post(url, json={"rules": rules}, headers={"X-CSRFToken": token}).status_code == 200


def test_editor_escapes_hostile_value(auth_client):
    hostile = "'</script><img src=x onerror=alert(1)>"
    raw = sample_bytes("alfa-1.xml").decode()
    import re
    m = re.search(r">([^<>\s][^<>]*)</", raw[raw.index("<", raw.index("?>") + 2):])
    raw = raw.replace(m.group(0), f">{hostile.replace('<', '&lt;').replace('>', '&gt;')}</", 1)
    d = ingest(raw.encode(), "alfa-x.xml")
    html = auth_client.get(f"/szablony/dokument/{d.id}/edytor").get_data(as_text=True)
    assert hostile not in html and "<img src=x" not in html
    assert "\\u003c/script\\u003e" in html


def test_detail_has_back_link_supplier_and_select_labels(auth_client):
    make_doc_with_template()
    t = Template.query.one()
    html = auth_client.get(f"/szablony/{t.id}").get_data(as_text=True)
    assert "← Szablony" in html and 'href="/szablony"' in html
    assert "Hurtownia Alfa" in html
    assert 'for="cmp-a"' in html and 'id="cmp-a"' in html
    assert 'for="cmp-b"' in html and 'id="cmp-b"' in html
    assert "table-responsive" in html and "<time " in html
    t.supplier_id = None
    t.supplier = None
    db.session.commit()
    assert auth_client.get(f"/szablony/{t.id}").status_code == 200


def test_restore_button_has_confirm(auth_client):
    d = make_doc_with_template()
    resolve(d, "map_field", {"field": "currency", "value": "PLN"}, True, "admin")
    t = Template.query.one()
    html = auth_client.get(f"/szablony/{t.id}").get_data(as_text=True)
    assert 'data-confirm="Przywrócić wersję 1' in html
