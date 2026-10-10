function editor(cfg) {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  return {
    cfg,
    rules: JSON.parse(JSON.stringify(cfg.rules || {})),
    selected: null,
    preview: null,
    comment: '',
    saving: false,
    error: '',
    init() {
      for (const k of ['header', 'lines', 'defaults', 'line_defaults']) this.rules[k] = this.rules[k] || {};
      this.runPreview();
    },
    ruleOf(section, key) { return this.rules[section][key] || null; },
    defaultOf(section, key) {
      return (this.rules[section === 'lines' ? 'line_defaults' : 'defaults'][key]) ?? '';
    },
    relative(path) {
      const base = (this.rules.line_path || '') + '/';
      return path.startsWith(base) ? path.slice(base.length) : null;
    },
    assign(section, key) {
      this.error = '';
      let path = this.selected;
      if (section === 'lines') {
        path = this.relative(this.selected);
        if (!path) { this.error = 'Pole pozycji musi wskazywać element wewnątrz elementu z pozycjami.'; return; }
      }
      const old = this.rules[section][key] || {};
      this.rules[section][key] = { path, transforms: old.transforms || [] };
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
        const t = JSON.parse(text || '[]');
        if (!Array.isArray(t)) throw new Error();
        this.rules[section][key].transforms = t;
        this.runPreview();
      } catch (e) { this.error = 'Transformacje muszą być listą JSON, np. ["trim", {"gs1": "10"}].'; }
    },
    setDefault(section, key, value) {
      const bucket = this.rules[section === 'lines' ? 'line_defaults' : 'defaults'];
      if (value === '') delete bucket[key]; else bucket[key] = value;
      this.runPreview();
    },
    async post(url, body) {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                                   body: JSON.stringify(body) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Błąd serwera');
      return data;
    },
    async runPreview() {
      try { this.preview = await this.post(cfg.previewUrl, { rules: this.rules }); this.error = ''; }
      catch (e) { this.error = e.message; }
    },
    async save() {
      this.saving = true;
      try {
        const res = await this.post(cfg.saveUrl, { rules: this.rules, comment: this.comment });
        window.location = res.redirect;
      } catch (e) { this.error = e.message; } finally { this.saving = false; }
    },
  };
}
