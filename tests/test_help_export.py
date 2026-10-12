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


def test_faq_heading_with_slug_keeps_anchor_numbered_does_not():
    """Nagłówek akordeonu FAQ ze slugiem (id=worek-na-kg) dostaje kotwicę w Markdown — link /pomoc/faq#worek-na-kg
    z Pomocy i Wiki działa; nagłówki numerowane (faq-h3) kotwicy nie mają, bo numer zmienia się przy każdym wpisie."""
    html = ('<div class="accordion"><div class="accordion-item"><h2 class="accordion-header" id="faq-h3">'
            '<button type="button">Jak zmienić hasło?</button></h2><div class="accordion-body">Tak.</div></div>'
            '<div class="accordion-item"><h2 class="accordion-header" id="worek-na-kg">'
            '<button type="button">Worki a kilogramy?</button></h2><div class="accordion-body">Krok.</div></div></div>')
    assert _markdown(html) == ('## Jak zmienić hasło?\n\nTak.\n\n<a id="worek-na-kg"></a>\n\n## Worki a kilogramy?'
                               '\n\nKrok.\n')
