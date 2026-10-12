// Edytor mapowań — komponent Alpine.js. Alpine działa w buildzie CSP (bez 'unsafe-eval' w Content-Security-Policy),
// więc w atrybutach szablonu są tylko proste wyrażenia: odwołania do właściwości, wywołania metod z argumentami,
// porównania i negacja. Wszystko złożone (template literals, JSON/Math/Object, `?.`, przypisania do zagnieżdżonych
// właściwości) jest metodą komponentu. Konfigurację podaje blok <script type="application/json" id="editor-config">
// — to dane, nie kod, więc CSP go nie dotyczy, a filtr tojson chroni przed wybiciem się z bloku.
var SESSION_EXPIRED_MSG = 'Sesja wygasła albo serwer odpowiedział stroną zamiast danymi — odśwież stronę i zaloguj się ponownie.';

function editorComponent(cfg) {
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var rules = JSON.parse(JSON.stringify(cfg.rules || {}));
  for (var k of ['header', 'lines', 'defaults', 'line_defaults']) rules[k] = rules[k] || {};
  return {
    cfg: cfg,
    rules: rules,
    selected: null,
    preview: null,
    comment: '',
    saving: false,
    error: '',
    sections: [
      { key: 'header', label: 'Nagłówek', fields: cfg.header || [] },
      { key: 'lines', label: 'Pozycje (ścieżki względne)', fields: cfg.lines || [] },
    ],
    transformList: Object.entries(cfg.transforms || {}).map(function (e) { return { name: e[0], label: e[1] }; }),
    init() { this.runPreview(); },

    // --- drzewo pliku ---
    select(r) { this.selected = r.path; },
    isSelected(r) { return this.selected === r.path; },
    rowStyle(r) { return 'padding-left:' + (r.depth * 12) + 'px; cursor:pointer'; },
    rowClass(r) {
      return { 'bg-primary-subtle': this.selected === r.path, 'fw-semibold': this.cfg.groups.includes(r.path) };
    },
    canSetLinePath() { return !!this.selected && this.cfg.groups.includes(this.selected); },
    linePathLabel() { return this.rules.line_path || '— brak —'; },

    // --- pola i reguły ---
    ruleOf(section, key) { return this.rules[section][key] || null; },
    hasRule(section, key) { return !!this.ruleOf(section, key); },
    ruleSource(section, key) { var r = this.ruleOf(section, key); return r ? (r.path || r.constant || '') : ''; },
    transformsText(section, key) { var r = this.ruleOf(section, key); return JSON.stringify((r && r.transforms) || []); },
    defaultOf(section, key) {
      var v = this.rules[section === 'lines' ? 'line_defaults' : 'defaults'][key];
      return v === undefined || v === null ? '' : v;
    },
    fieldLabel(f) { return f.label + (f.required ? ' *' : ''); },
    candidatesFor(key) { return this.cfg.candidates[key] || []; },
    candidateLabel(c) {
      return c.path.split('/').slice(-2).join('/') + ' · ' + Math.round(c.confidence * 100) + '%';
    },
    relative(path) {
      var base = (this.rules.line_path || '') + '/';
      return path.startsWith(base) ? path.slice(base.length) : null;
    },
    assign(section, key) {
      this.error = '';
      var path = this.selected;
      if (section === 'lines') {
        path = this.relative(this.selected);
        if (!path) { this.error = 'Pole pozycji musi wskazywać element wewnątrz elementu z pozycjami.'; return; }
      }
      var old = this.rules[section][key] || {};
      this.rules[section][key] = { path: path, transforms: old.transforms || [] };
      this.runPreview();
    },
    applyCandidate(section, key, c) {
      this.rules[section][key] = { path: c.path, transforms: c.transforms || [] };
      this.runPreview();
    },
    clear(section, key) { delete this.rules[section][key]; this.runPreview(); },
    setLinePath() { this.rules.line_path = this.selected; this.runPreview(); },
    setTransforms(section, key, text) {
      this.error = '';
      try {
        var t = JSON.parse(text || '[]');
        if (!Array.isArray(t)) throw new Error();
        this.rules[section][key].transforms = t;
        this.runPreview();
      } catch (e) { this.error = 'Transformacje muszą być listą JSON, np. ["trim", {"gs1": "10"}].'; }
    },
    onTransformsChange(section, key, event) { this.setTransforms(section, key, event.target.value); },
    setDefault(section, key, value) {
      var bucket = this.rules[section === 'lines' ? 'line_defaults' : 'defaults'];
      if (value === '') delete bucket[key]; else bucket[key] = value;
      this.runPreview();
    },
    onDefaultChange(section, key, event) { this.setDefault(section, key, event.target.value); },

    // --- podgląd ---
    previewSummary() {
      return this.preview && this.preview.issues.length ? 'Problemy: ' + this.preview.issues.length : 'Brak problemów ✓';
    },
    issueClass(i) { return i.severity === 'blocking' ? 'border-danger' : 'border-warning'; },
    previewJson() { return this.preview ? JSON.stringify(this.preview.invoice, null, 1) : ''; },

    // --- serwer ---
    async post(url, body) {
      var r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                                 body: JSON.stringify(body) });
      var type = (r.headers.get('Content-Type') || '').toLowerCase();
      if (r.redirected || type.indexOf('application/json') === -1) {
        // przekierowanie na logowanie (sesja wygasła) albo strona błędu zamiast JSON — nie parsujemy HTML jako JSON
        throw new Error(r.redirected || r.ok ? SESSION_EXPIRED_MSG : 'Błąd serwera (' + r.status + ')');
      }
      var data = await r.json();
      if (!r.ok) { var err = new Error(data.error || 'Błąd serwera'); err.data = data; throw err; }
      return data;
    },
    async runPreview() {
      try { this.preview = await this.post(this.cfg.previewUrl, { rules: this.rules }); this.error = ''; }
      catch (e) { this.error = e.message; }
    },
    async save() {
      this.saving = true;
      try {
        // base_version_id — blokada optymistyczna: serwer odrzuci zapis (409), jeśli szablon zmienił się w międzyczasie
        var body = { rules: this.rules, comment: this.comment, base_version_id: this.cfg.baseVersionId ?? null };
        var res;
        try { res = await this.post(this.cfg.saveUrl, body); }
        catch (e) {
          // usunięcie mapowania pól wymaganych wymaga jawnego potwierdzenia (EDGE-15)
          if (!(e.data && e.data.needs_confirm && window.confirm(e.message))) throw e;
          res = await this.post(this.cfg.saveUrl, Object.assign({}, body, { confirm_incomplete: true }));
        }
        window.location = res.redirect;
      } catch (e) { this.error = e.message; } finally { this.saving = false; }
    },
  };
}

document.addEventListener('alpine:init', function () {
  Alpine.data('editor', function () {
    var node = document.getElementById('editor-config');
    return editorComponent(node ? JSON.parse(node.textContent) : {});
  });
});
