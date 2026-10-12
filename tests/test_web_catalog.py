import io

from app.extensions import db
from app.models import ApiKey, AuditLog, Product, Supplier, Unit, UnitAlias


def test_supplier_crud(auth_client):
    r = auth_client.post("/dostawcy/nowy", data={"name": "Testowy", "tax_id": "PL1", "notes": ""},
                         follow_redirects=True)
    assert "Testowy" in r.get_data(as_text=True)
    s = Supplier.query.one()
    auth_client.post(f"/dostawcy/{s.id}/edycja", data={"name": "Testowy 2", "tax_id": "PL1", "notes": "x"})
    assert Supplier.query.one().name == "Testowy 2"
    html = auth_client.get("/dostawcy").get_data(as_text=True)
    assert "Edytuj" in html and "Usuń" in html
    auth_client.post(f"/dostawcy/{s.id}/usun")
    assert Supplier.query.count() == 0


def test_alias_edit_updates_norm(auth_client):
    szt = Unit.query.filter_by(code="szt").one()
    auth_client.post("/aliasy-jednostek/nowy", data={"alias": "PCS", "unit_id": szt.id, "supplier_id": ""})
    a = UnitAlias.query.filter_by(alias="PCS").one()
    assert a.alias_norm == "pcs" and a.supplier_id is None
    auth_client.post(f"/aliasy-jednostek/{a.id}/edycja", data={"alias": "Pc", "unit_id": szt.id, "supplier_id": ""})
    assert db.session.get(UnitAlias, a.id).alias_norm == "pc"


def test_delete_blocked_when_in_use(auth_client):
    szt = Unit.query.filter_by(code="szt").one()
    r = auth_client.post(f"/jednostki/{szt.id}/usun", follow_redirects=True)
    assert "Nie można usunąć" in r.get_data(as_text=True)
    assert Unit.query.filter_by(code="szt").count() == 1


def test_product_validation_and_import(auth_client):
    r = auth_client.post("/towary/nowy", data={"code": "X-1", "name": "Zły GTIN", "gtin": "123", "unit_id": ""},
                         follow_redirects=True)
    assert "Niepoprawny GTIN" in r.get_data(as_text=True)
    csv_data = ("indeks;nazwa;gtin;jednostka\nTOW-0001;Posypka (zmiana);5909999000013;szt\nNOWY-1;Cukier puder;;kg\n"
                "ZLY;Zły;111;szt\n")
    r = auth_client.post("/towary/import", data={"file": (io.BytesIO(csv_data.encode()), "t.csv")},
                         content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Dodano: 1" in html and "Zaktualizowano: 1" in html and "Błędy: 1" in html
    assert Product.query.filter_by(code="TOW-0001").one().name == "Posypka (zmiana)"
    assert Product.query.filter_by(code="NOWY-1").one().unit.code == "kg"


def test_api_keys_page(auth_client):
    r = auth_client.post("/klucze-api/nowy", data={"name": "ERP"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    key = ApiKey.query.filter_by(name="ERP").one()
    assert "xp_" in html and "Skopiuj teraz" in html
    auth_client.post(f"/klucze-api/{key.id}/przelacz")
    assert db.session.get(ApiKey, key.id).active is False
    auth_client.post(f"/klucze-api/{key.id}/nazwa", data={"name": "ERP 2"})
    assert db.session.get(ApiKey, key.id).name == "ERP 2"
    auth_client.post(f"/klucze-api/{key.id}/usun")
    assert ApiKey.query.filter_by(name="ERP 2").count() == 0


def test_history_lists_audit(auth_client):
    auth_client.post("/dostawcy/nowy", data={"name": "Audytowany", "tax_id": "", "notes": ""})
    assert AuditLog.query.filter_by(action="create", entity="suppliers").count() == 1
    assert "Audytowany" in auth_client.get("/historia").get_data(as_text=True)


def _unit(code):
    return Unit.query.filter_by(code=code).one()


def test_conversion_invalid_factor_is_form_error(auth_client):
    from app.models import UnitConversion
    kg, szt = _unit("kg"), _unit("szt")
    before = UnitConversion.query.count()
    for bad in ("0", "-2", "0,0000001", "abc", "1" + "0" * 13):
        r = auth_client.post("/przeliczniki/nowy", data={"from_unit_id": szt.id, "factor": bad,
                                                         "to_unit_id": kg.id, "supplier_id": "", "product_id": ""},
                             follow_redirects=True)
        assert r.status_code == 200, bad
        assert "alert-danger" in r.get_data(as_text=True), bad
    assert UnitConversion.query.count() == before
    r = auth_client.post("/przeliczniki/nowy", data={"from_unit_id": szt.id, "factor": "0,5",
                                                     "to_unit_id": kg.id, "supplier_id": "", "product_id": ""})
    assert r.status_code == 302 and UnitConversion.query.count() == before + 1


def test_global_alias_duplicate_rejected(auth_client):
    szt = _unit("szt")
    data = {"alias": "Sztuki", "unit_id": szt.id, "supplier_id": ""}
    auth_client.post("/aliasy-jednostek/nowy", data=data)
    r = auth_client.post("/aliasy-jednostek/nowy", data={**data, "alias": " sztuki "}, follow_redirects=True)
    assert "już istnieje" in r.get_data(as_text=True)
    assert UnitAlias.query.filter_by(alias_norm="sztuki").count() == 1
    # edycja istniejącego aliasu bez zmiany nie koliduje sama ze sobą
    a = UnitAlias.query.filter_by(alias_norm="sztuki").one()
    r = auth_client.post(f"/aliasy-jednostek/{a.id}/edycja", data=data)
    assert r.status_code == 302


def test_mapping_gtin_normalised_and_validated(auth_client):
    from app.models import ProductMapping
    s = Supplier(name="Map")
    db.session.add(s)
    db.session.commit()
    p = Product.query.first()
    r = auth_client.post("/mapowania-towarow/nowy", data={"supplier_id": s.id, "supplier_code": "",
                                                          "supplier_gtin": "5909999000013", "product_id": p.id})
    assert r.status_code == 302
    assert ProductMapping.query.one().supplier_gtin == "05909999000013"
    r = auth_client.post("/mapowania-towarow/nowy", data={"supplier_id": s.id, "supplier_code": "",
                                                          "supplier_gtin": "12", "product_id": p.id},
                         follow_redirects=True)
    assert "Niepoprawny GTIN" in r.get_data(as_text=True)


def test_delete_supplier_with_mapping_blocked(auth_client):
    from app.models import ProductMapping
    s = Supplier(name="Powiązany")
    db.session.add(s)
    db.session.flush()
    db.session.add(ProductMapping(supplier_id=s.id, supplier_code="A", product_id=Product.query.first().id))
    db.session.commit()
    r = auth_client.post(f"/dostawcy/{s.id}/usun", follow_redirects=True)
    assert "Nie można usunąć" in r.get_data(as_text=True)
    assert db.session.get(Supplier, s.id) is not None


def test_import_bad_inputs_never_500(auth_client):
    def post(b, name="t.csv"):
        return auth_client.post("/towary/import", data={"file": (io.BytesIO(b), name)},
                                content_type="multipart/form-data", follow_redirects=True)
    r = post("indeks;nazwa\nK1;Żółć\n".encode("cp1250"))
    assert r.status_code == 200 and "Dodano: 1" in r.get_data(as_text=True)
    assert Product.query.filter_by(code="K1").one().name == "Żółć"
    r = post(b"\xff\xfe\x00garbage\x00\x00")
    assert r.status_code == 200
    r = post(b"foo;bar\n1;2\n")
    assert "Brak kolumn" in r.get_data(as_text=True)
    r = post(b"")
    assert r.status_code == 200 and "niepusty" in r.get_data(as_text=True)
    r = post(b"indeks;nazwa\n" + b"A;" + b"x" * (2 * 1024 * 1024))
    assert r.status_code == 200 and "za duży" in r.get_data(as_text=True)
    r = post(b"indeks;nazwa;jednostka\nU1;Nazwa;xyz\n")
    assert "nieznana jednostka" in r.get_data(as_text=True)


def test_csrf_and_login_required(app, client):
    for url in ("/dostawcy", "/towary", "/klucze-api", "/historia", "/towary/import"):
        assert client.get(url).status_code == 302
    assert client.post("/dostawcy/1/usun").status_code == 302
    assert client.post("/klucze-api/nowy", data={"name": "x"}).status_code == 302
