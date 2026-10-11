"""Pilnuje, by docs/pomoc/ (Markdown) odpowiadał sekcji Pomoc w panelu."""
import importlib.util
from pathlib import Path

import lxml.html

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


def _markdown(html: str) -> str:
    return _load_exporter().html_to_markdown(lxml.html.fromstring(f"<main>{html}</main>"))


def test_figure_exported_as_repo_image_with_caption():
    """Zrzut z Pomocy (HTML jak w help/_shot.html): obrazek z atrybutu alt (innego niż podpis) ze ścieżką względną do
    pliku w repo (GitHub ją renderuje) i podpis kursywą pod nim; link wokół obrazka (pełny rozmiar w panelu) nie powiela
    adresu, a wskazówka „w nowej karcie” dla czytnika ekranu (span.visually-hidden) nie trafia do Markdown."""
    src = "/static/screenshots/02-pulpit.png"
    md = _markdown(f'<p>Tekst.</p><figure class="help-shot"><a href="{src}" target="_blank" rel="noopener" '
                   'title="Pełny rozmiar — otwiera się w nowej karcie">'
                   f'<img src="{src}" alt="Pulpit: liczniki statusów" width="1400" height="900" class="img-fluid">'
                   '<span class="visually-hidden"> (pełny rozmiar otwiera się w nowej karcie)</span></a>'
                   '<figcaption class="small">Pulpit po nauczeniu [alfa]</figcaption></figure><p>Dalej.</p>')
    assert md == ("Tekst.\n\n![Pulpit: liczniki statusów](../../app/static/screenshots/02-pulpit.png)\n\n"
                  "*Pulpit po nauczeniu \\[alfa\\]*\n\nDalej.\n")
    assert (COMMITTED / "../../app/static/screenshots/02-pulpit.png").resolve().is_file()


def test_static_links_point_to_repo_files():
    """Pliki aplikacji spod /static/ (np. openapi.yaml) prowadzą do pliku w repo, a nie do ścieżki w panelu."""
    assert _markdown('<p>Plik <a href="/static/openapi.yaml">openapi.yaml</a>.</p>') == \
        "Plik [openapi.yaml](../../app/static/openapi.yaml).\n"
    assert _markdown('<p><a href="/api/docs">Swagger</a></p>') == "Swagger (`/api/docs`)\n"  # bez zmian
