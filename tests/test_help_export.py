"""Pilnuje, by docs/pomoc/ (Markdown) odpowiadał sekcji Pomoc w panelu."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "docs" / "pomoc"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_help", ROOT / "tools" / "export_help.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_pomoc_zgodne_z_panelem(tmp_path):
    out = tmp_path / "pomoc"
    _load_exporter().export_help(out)

    generated = {p.name: p.read_bytes() for p in out.glob("*.md")}
    committed = {p.name: p.read_bytes() for p in COMMITTED.glob("*.md")}
    hint = "docs/pomoc/ jest nieaktualne — uruchom tools/export_help.py i zacommituj wynik"

    assert "README.md" in generated and len(generated) > 1
    assert generated.keys() == committed.keys(), f"{hint} (różne pliki: {sorted(generated.keys() ^ committed.keys())})"
    for name, data in generated.items():
        assert data == committed[name], f"{hint} (różni się {name})"
