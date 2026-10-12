"""Edytor mapowań po stronie przeglądarki (app/static/editor.js) i build CSP Alpine.js.

Logika komponentu jest sprawdzana w Node (bez przeglądarki): `editorComponent(cfg)` to zwykła funkcja, a `fetch`
i `document` są atrapami. Szablony z Alpine mogą zawierać tylko wyrażenia obsługiwane przez build CSP — bez
template literals, globali (JSON, Math, Object), `?.` i funkcji strzałkowych; wszystko złożone jest metodą
komponentu."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EDITOR_JS = ROOT / "app" / "static" / "editor.js"
ALPINE_ATTR = re.compile(r"""\s(?:x-[a-z-]+|:[a-z-]+|@[a-z.-]+)=(?:"([^"]*)"|'([^']*)')""")
FORBIDDEN = ("`", "JSON.", "Math.", "Object.", "?.", "=>", "window.", "document.")

HARNESS = r"""
const vm = require('node:vm'); const fs = require('node:fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
global.document = { querySelector: () => ({content: 'csrf-token'}), getElementById: () => null,
                    addEventListener: () => {} };
global.window = { location: '', confirm: () => true };
let responses = [];
global.fetch = async (url, opts) => {
  global.lastOpts = opts; const r = responses.shift(); r.url = r.url || url; return r;
};
function resp({ok = true, status = 200, redirected = false, type = 'application/json', body = '{}', url} = {}) {
  return { ok, status, redirected, url, headers: { get: (h) => h.toLowerCase() === 'content-type' ? type : null },
           json: async () => JSON.parse(body), text: async () => body };
}
vm.runInThisContext(src);
(async () => {
  const cfg = JSON.parse(process.argv[3]);
  const out = {};
  const c = editorComponent(cfg);
  responses = [resp({redirected: true, type: 'text/html; charset=utf-8', body: '<html>login</html>',
                     url: 'http://x/login?next=%2F'})];
  try { await c.post('/p', {}); out.redirect = 'no error'; } catch (e) { out.redirect = e.message; }
  responses = [resp({ok: false, status: 500, type: 'text/html', body: '<h1>500</h1>'})];
  try { await c.post('/p', {}); out.html500 = 'no error'; } catch (e) { out.html500 = e.message; }
  responses = [resp({ok: false, status: 400, body: JSON.stringify({error: 'Zła reguła', needs_confirm: true})})];
  try { await c.post('/p', {}); }
  catch (e) { out.json400 = {message: e.message, needs_confirm: !!(e.data && e.data.needs_confirm)}; }
  responses = [resp({body: JSON.stringify({invoice: {}, issues: []})})];
  out.ok = await c.post('/p', {rules: {}});
  out.csrf = global.lastOpts.headers['X-CSRFToken'];
  out.candidateLabel = c.candidateLabel(cfg.candidates.number[0]);
  out.rowStyle = c.rowStyle(cfg.rows[1]);
  c.select(cfg.rows[1]);
  out.selected = c.selected; out.isSelected = c.isSelected(cfg.rows[1]); out.canSetLinePath = c.canSetLinePath();
  out.ruleSource = c.ruleSource('header', 'number'); out.transformsText = c.transformsText('header', 'number');
  out.hasRule = [c.hasRule('header', 'number'), c.hasRule('lines', 'qty')];
  out.sections = c.sections.map(s => [s.key, s.fields.length]);
  out.transformList = c.transformList;
  out.fieldLabel = c.fieldLabel(cfg.header[0]);
  c.preview = {issues: [{severity: 'blocking', message: 'm'}], invoice: {number: 'X'}};
  out.previewSummary = c.previewSummary(); out.issueClass = c.issueClass(c.preview.issues[0]);
  out.previewJson = c.previewJson();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.stack); process.exit(1); });
"""

CFG = {
    "rules": {"line_path": "a/b", "header": {"number": {"path": "a/n", "transforms": ["trim"]}}},
    "rows": [{"path": "a", "name": "a", "value": None, "depth": 0},
             {"path": "a/b", "name": "b", "value": "x", "depth": 1}],
    "groups": ["a", "a/b"],
    "header": [{"key": "number", "label": "Numer", "required": True}],
    "lines": [{"key": "qty", "label": "Ilość", "required": True}],
    "candidates": {"number": [{"path": "a/x/n", "confidence": 0.456, "reason": "r", "transforms": []}]},
    "transforms": {"trim": "Usuń spacje"},
    "previewUrl": "/p", "saveUrl": "/s", "backUrl": "/d", "baseVersionId": 7,
}


@pytest.fixture(scope="module")
def component_output(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("wymaga node")
    harness = tmp_path_factory.mktemp("js") / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(harness), str(EDITOR_JS), json.dumps(CFG)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_post_detects_session_expiry_and_non_json_responses(component_output):
    out = component_output
    assert "Sesja wygasła" in out["redirect"] and "zaloguj" in out["redirect"].lower()
    assert out["html500"] == "Błąd serwera (500)"
    assert out["json400"] == {"message": "Zła reguła", "needs_confirm": True}
    assert out["ok"] == {"invoice": {}, "issues": []}
    assert out["csrf"] == "csrf-token"


def test_csp_helper_methods_replace_inline_expressions(component_output):
    out = component_output
    assert out["candidateLabel"] == "x/n · 46%"
    assert out["rowStyle"] == "padding-left:12px; cursor:pointer"
    assert out["selected"] == "a/b" and out["isSelected"] is True and out["canSetLinePath"] is True
    assert out["ruleSource"] == "a/n" and out["transformsText"] == '["trim"]' and out["hasRule"] == [True, False]
    assert out["sections"] == [["header", 1], ["lines", 1]]
    assert out["transformList"] == [{"name": "trim", "label": "Usuń spacje"}]
    assert out["fieldLabel"] == "Numer *"
    assert out["previewSummary"] == "Problemy: 1" and out["issueClass"] == "border-danger"
    assert json.loads(out["previewJson"]) == {"number": "X"}


@pytest.mark.parametrize("template", ["editor.html", "upload.html"])
def test_alpine_attributes_are_csp_safe(template):
    html = (ROOT / "app" / "templates" / template).read_text(encoding="utf-8")
    exprs = [a or b for a, b in ALPINE_ATTR.findall(html)]
    assert exprs, template
    for expr in exprs:
        for bad in FORBIDDEN:
            assert bad not in expr, f"{template}: {expr!r} zawiera {bad!r} (nieobsługiwane w buildzie CSP)"


def test_editor_config_passed_as_json_data_block_not_expression():
    html = (ROOT / "app" / "templates" / "editor.html").read_text(encoding="utf-8")
    assert 'x-data="editor"' in html
    assert '<script type="application/json" id="editor-config">' in html
