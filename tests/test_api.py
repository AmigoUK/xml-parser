import io

from tests.conftest import sample_bytes

KEY = {"X-API-Key": "xp_test_demo_key"}


def test_requires_key(seeded, client):
    r = client.get("/api/v1/documents")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/documents", headers={"X-API-Key": "zly"}).status_code == 401


def test_upload_multipart_and_get(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY,
                    data={"file": (io.BytesIO(sample_bytes("epsilon.json")), "epsilon.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "needs_review" and body["format"] == "json"
    assert body["invoice"]["number"] == "E-2026-0042"
    assert body["issues"][0]["code"] == "unknown_supplier"
    r2 = client.get(f"/api/v1/documents/{body['id']}", headers=KEY)
    assert r2.status_code == 200 and r2.get_json()["id"] == body["id"]


def test_upload_raw_body(seeded, client):
    r = client.post("/api/v1/documents", headers={**KEY, "X-Filename": "delta.csv", "Content-Type": "text/csv"},
                    data=sample_bytes("delta.csv"))
    assert r.status_code == 201 and r.get_json()["format"] == "csv"


def test_api_empty_body_400(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY, data=b"")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "empty_body"


def test_unreadable_returns_201_rejected(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a><b></a>")
    assert r.status_code == 201 and r.get_json()["status"] == "rejected"


def test_too_large(seeded, app, client):
    app.config["MAX_DOCUMENT_BYTES"] = 10
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a>" + b"x" * 50 + b"</a>")
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "too_large"


def test_list_filter_and_reprocess(seeded, client):
    client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml"))
    r = client.get("/api/v1/documents?status=needs_review", headers=KEY)
    items = r.get_json()["items"]
    assert len(items) == 1 and "invoice" not in items[0]
    r = client.post(f"/api/v1/documents/{items[0]['id']}/reprocess", headers=KEY)
    assert r.status_code == 200 and r.get_json()["status"] == "needs_review"
    assert client.get("/api/v1/documents?status=zly", headers=KEY).status_code == 400
    assert client.get("/api/v1/documents/9999", headers=KEY).status_code == 404


def test_suppliers_and_docs_page(seeded, client):
    assert client.get("/api/v1/suppliers", headers=KEY).get_json() == {"items": []}
    assert client.get("/api/docs").status_code == 200
    assert client.get("/static/openapi.yaml").status_code == 200


def test_too_large_http_limit_json(seeded, app, client):
    app.config["MAX_CONTENT_LENGTH"] = 100
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a>" + b"x" * 500 + b"</a>")
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "too_large"


def test_bad_limit_400(seeded, client):
    assert client.get("/api/v1/documents?limit=abc", headers=KEY).status_code == 400


def _second_key(app):
    from app.extensions import db
    from app.services.apikeys import create_key
    create_key("B", "xp_other_key_b")
    db.session.commit()
    return {"X-API-Key": "xp_other_key_b"}


def test_keys_are_isolated(seeded, app, client):
    b = _second_key(app)
    doc = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml")).get_json()
    assert client.get(f"/api/v1/documents/{doc['id']}", headers=b).status_code == 404
    r = client.post(f"/api/v1/documents/{doc['id']}/reprocess", headers=b)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    assert client.get("/api/v1/documents", headers=b).get_json() == {"items": []}
    assert len(client.get("/api/v1/documents", headers=KEY).get_json()["items"]) == 1


def test_panel_document_invisible_to_api(seeded, app, client):
    from app.services.pipeline import ingest
    with app.app_context():
        doc = ingest(sample_bytes("alfa-1.xml"), "a.xml", source="upload")
        doc_id = doc.id
    assert client.get(f"/api/v1/documents/{doc_id}", headers=KEY).status_code == 404
    assert client.get("/api/v1/documents", headers=KEY).get_json() == {"items": []}


def test_json_404_405(seeded, client):
    r = client.get("/api/v1/nic", headers=KEY)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    r = client.delete("/api/v1/suppliers", headers=KEY)
    assert r.status_code == 405 and r.get_json()["error"]["code"] == "method_not_allowed"
