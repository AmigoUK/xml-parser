"""REST API: lista dostaw webhooków (GET /api/v1/webhook-deliveries) i schematy OpenAPI (v0.9.0, T6)."""
import os
from datetime import timedelta
from pathlib import Path

import yaml

from app.api.serializers import delivery_to_json
from app.extensions import db
from app.models import (
    EVENT_STATUS_CHANGED,
    WEBHOOK_FAILED,
    WEBHOOK_PENDING,
    WEBHOOK_SENT,
    ApiKey,
    Document,
    WebhookDelivery,
    utcnow,
)

KEY = {"X-API-Key": "xp_test_demo_key"}
URL = "/api/v1/webhook-deliveries"
SPEC = Path(__file__).resolve().parent.parent / "app" / "static" / "openapi.yaml"


def _demo_key():
    return ApiKey.query.filter_by(name="Klucz demo").one()


def _doc(key):
    d = Document(sha256=os.urandom(32).hex(), status="approved", api_key_id=key.id)
    db.session.add(d)
    db.session.flush()
    return d


def _delivery(key, *, status=WEBHOOK_PENDING, document_id=None, age=0, **kw):
    d = WebhookDelivery(api_key_id=key.id, document_id=document_id, event=EVENT_STATUS_CHANGED,
                        payload={"event": EVENT_STATUS_CHANGED, "id": document_id}, status=status,
                        created_at=utcnow() - timedelta(seconds=age), **kw)
    db.session.add(d)
    db.session.flush()
    return d


def test_list_deliveries_scoped_to_key(seeded, client):
    """Lista zawiera tylko dostawy klucza z nagłówka; bez klucza 401."""
    mine = _delivery(_demo_key())
    other = ApiKey(name="inny", prefix="xp_oth", key_hash=os.urandom(32).hex(), active=True)
    db.session.add(other)
    db.session.flush()
    _delivery(other)
    db.session.commit()
    assert client.get(URL).status_code == 401
    r = client.get(URL, headers=KEY)
    assert r.status_code == 200
    assert [i["uuid"] for i in r.get_json()["items"]] == [mine.uuid]
    assert r.get_json()["next_cursor"] is None


def test_list_filters_status_and_document_id(seeded, client):
    """Filtry status i document_id (łączone warunkiem „i”)."""
    key = _demo_key()
    d1, d2 = _doc(key), _doc(key)
    a = _delivery(key, status=WEBHOOK_SENT, document_id=d1.id, age=3)
    b = _delivery(key, status=WEBHOOK_FAILED, document_id=d1.id, age=2)
    c = _delivery(key, status=WEBHOOK_SENT, document_id=d2.id, age=1)
    db.session.commit()
    uuids = lambda q: {i["uuid"] for i in client.get(URL + q, headers=KEY).get_json()["items"]}  # noqa: E731
    assert uuids("?status=sent") == {a.uuid, c.uuid}
    assert uuids(f"?document_id={d1.id}") == {a.uuid, b.uuid}
    assert uuids(f"?status=sent&document_id={d1.id}") == {a.uuid}


def test_list_pagination_cursor_newest_first(seeded, client):
    """Od najnowszych po (created_at, id); kursor prowadzi przez strony bez powtórzeń."""
    key = _demo_key()
    rows = [_delivery(key, age=10 - i) for i in range(5)]  # rows[4] najnowsza
    same = utcnow()
    t1 = _delivery(key)
    t2 = _delivery(key)
    t1.created_at = t2.created_at = same + timedelta(seconds=5)
    db.session.commit()
    expected = [t2.uuid, t1.uuid] + [r.uuid for r in reversed(rows)]
    got, cursor = [], None
    for _ in range(10):
        q = "?limit=3" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(URL + q, headers=KEY).get_json()
        got += [i["uuid"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert got == expected


def test_bad_status_and_cursor_400(seeded, client):
    """Zły status, document_id, limit lub kursor → 400 bad_request."""
    for q in ("?status=zly", "?document_id=0", "?document_id=abc", "?document_id=-1", "?limit=x",
              "?cursor=%21%21", "?cursor="):
        r = client.get(URL + q, headers=KEY)
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request", q


def test_delivery_json_has_no_secret_and_times_in_api_format(seeded, client):
    """Brak api_key_id, sekretu i numerycznego id; czasy w formacie API (UTC, Z), brak wartości → null."""
    key = _demo_key()
    key.webhook_secret = "tajny-sekret-123"
    d = _delivery(key, status=WEBHOOK_SENT, attempts=2, last_status_code=200, sent_at=utcnow())
    db.session.commit()
    r = client.get(URL, headers=KEY)
    item = r.get_json()["items"][0]
    assert set(item) == {"uuid", "event", "status", "attempts", "document_id", "payload", "created_at",
                         "next_attempt_at", "sent_at", "last_status_code", "last_error"}
    assert item["uuid"] == d.uuid and item["next_attempt_at"] is None and item["last_error"] is None
    assert item["created_at"].endswith("Z") and item["sent_at"].endswith("Z") and "." in item["created_at"]
    assert "tajny-sekret-123" not in r.get_data(as_text=True)


def test_openapi_has_webhook_schemas_and_deliveries_path(seeded):
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    for name in ("WebhookEvent", "WebhookDelivery", "WebhookDeliveryList"):
        assert name in schemas
    assert set(schemas["WebhookEvent"]["properties"]) == {"event", "id", "status", "previous_status",
                                                          "updated_at", "document_url"}
    assert "callbacks" not in yaml.safe_dump(spec)
    op = spec["paths"]["/webhook-deliveries"]["get"]
    assert {p["name"] for p in op["parameters"]} == {"status", "document_id", "limit", "cursor"}
    assert {"200", "400", "401"} <= set(op["responses"])
    desc = spec["info"]["description"]
    assert "X-XP-Signature" in desc or "X-XP-Signature" in schemas["WebhookEvent"]["description"]


def test_openapi_matches_delivery_json_keys(seeded):
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    d = _delivery(_demo_key())
    db.session.commit()
    assert set(spec["components"]["schemas"]["WebhookDelivery"]["properties"]) == set(delivery_to_json(d))
