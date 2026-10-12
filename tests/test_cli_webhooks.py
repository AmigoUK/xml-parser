"""Komendy CLI webhooków (v0.9.0): `flask webhooks-worker --once` (jednorazowa wysyłka zaległych dostaw, np. z crona)
i `flask prune-webhooks [--days N]` (retencja wysłanych/nieudanych dostaw, domyślnie WEBHOOK_RETENTION_DAYS)."""
from datetime import timedelta

from app.extensions import db
from app.models import WEBHOOK_FAILED, WEBHOOK_PENDING, WEBHOOK_SENT, WebhookDelivery, utcnow
from tests.webhook_helpers import make_delivery, make_key


def test_webhooks_worker_once_delivers_and_exits_0(app, receiver):
    key = make_key(receiver.url)
    ids = [make_delivery(key, doc_id=1).id, make_delivery(key, doc_id=2).id]
    result = app.test_cli_runner().invoke(args=["webhooks-worker", "--once"])
    assert result.exit_code == 0, result.output
    assert "Wysłano 2" in result.output
    assert len(receiver.requests) == 2
    db.session.expire_all()
    assert {db.session.get(WebhookDelivery, i).status for i in ids} == {WEBHOOK_SENT}
    # druga runda: nic do wysłania, nadal kod 0
    result = app.test_cli_runner().invoke(args=["webhooks-worker", "--once"])
    assert result.exit_code == 0 and "Wysłano 0" in result.output


def test_prune_webhooks_cli_uses_config_default(app):
    app.config["WEBHOOK_RETENTION_DAYS"] = 10
    key = make_key("https://hooks.example.test/x")
    now = utcnow()
    make_delivery(key, status=WEBHOOK_SENT, created_at=now - timedelta(days=11))
    make_delivery(key, status=WEBHOOK_FAILED, created_at=now - timedelta(days=11))
    old_pending = make_delivery(key, status=WEBHOOK_PENDING, created_at=now - timedelta(days=11)).id
    recent = make_delivery(key, status=WEBHOOK_SENT, created_at=now - timedelta(days=9)).id
    runner = app.test_cli_runner()
    result = runner.invoke(args=["prune-webhooks"])
    assert result.exit_code == 0, result.output
    assert "Usunięto 2" in result.output and "10 dni" in result.output
    db.session.expire_all()
    assert {d.id for d in WebhookDelivery.query.all()} == {old_pending, recent}
    # jawne --days nadpisuje konfigurację
    result = runner.invoke(args=["prune-webhooks", "--days", "5"])
    assert result.exit_code == 0 and "Usunięto 1" in result.output
    result = runner.invoke(args=["prune-webhooks", "--days", "0"])
    assert result.exit_code == 2
