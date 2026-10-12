"""Szkielet UI: zamykane flashe, wspólne klasy CSS, stan wysyłania formularza uploadu, pasek powrotu w /api/docs."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def _fail_reset(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("Reset niedostępny w tym teście")
    monkeypatch.setattr("app.web.demo.reset_demo", boom)


def test_flash_has_close_button_and_role_alert(auth_client, monkeypatch):
    _fail_reset(monkeypatch)
    r = auth_client.post("/demo/reset", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert 'role="alert"' in html
    assert "alert-dismissible fade show" in html
    assert 'data-bs-dismiss="alert"' in html
    assert 'aria-label="Zamknij"' in html


def test_demo_reset_error_uses_error_category(auth_client, monkeypatch):
    _fail_reset(monkeypatch)
    html = auth_client.post("/demo/reset", follow_redirects=True).get_data(as_text=True)
    assert "Reset niedostępny w tym teście" in html
    assert "alert-danger" in html
    assert 'flash(str(exc), "error")' in (STATIC.parent / "web" / "demo.py").read_text(encoding="utf-8")


def test_api_docs_has_back_to_panel_bar(client):
    html = client.get("/api/docs").get_data(as_text=True)
    assert "api-docs-bar" in html
    assert 'href="/"' in html and "Panel" in html
    assert "app.css" in html
    assert 'class="api-docs"' in html


def test_app_css_defines_shared_layout_classes():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for cls in (".w-form-narrow", ".w-form-key", ".scroll-pane", ".min-h-0", ".cell-truncate",
                ".api-docs-bar", "body.api-docs"):
        assert cls in css, cls


def test_upload_component_has_submitting_state():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "submitting" in js
    assert "submitted()" in js
    assert "submitLabel()" in js
    assert "Przetwarzanie…" in js


def test_no_inline_handlers_in_base_and_api_docs(client):
    for url in ("/login", "/api/docs"):
        html = client.get(url).get_data(as_text=True)
        assert not re.search(r"\son\w+=", html), url
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), url
