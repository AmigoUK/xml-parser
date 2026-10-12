"""tools/export_wiki.py — strony Wiki GitHub z wyeksportowanej Pomocy (docs/pomoc). Czysta biblioteka standardowa
(uruchamiane w akcji GitHub bez instalowania zależności aplikacji): nazwy stron z nagłówków H1, linki między tematami
na nazwy stron, obrazki na raw.githubusercontent.com, inne pliki repo na /blob/, pasek boczny z FAQ na górze."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/AmigoUK/xml-parser"


def _load():
    spec = importlib.util.spec_from_file_location("export_wiki", ROOT / "tools" / "export_wiki.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "pomoc"
    d.mkdir()
    (d / "README.md").write_text(
        "<!-- Wygenerowano przez tools/export_help.py -->\n\n# Pomoc\n\nWstęp.\n\n## Tematy\n\n"
        "### [Jak to działa](jak-to-dziala.md)\n\nOpis.\n\n### [Jednostki, aliasy i przeliczniki](jednostki.md)\n\n"
        "Opis.\n\n### [Najczęstsze pytania](faq.md)\n\nOpis.\n", encoding="utf-8")
    (d / "jak-to-dziala.md").write_text(
        "<!-- Wygenerowano -->\n\n# Jak to działa\n\n![Pulpit](../../app/static/screenshots/02-pulpit.png)\n\n"
        "*Podpis*\n\nZobacz [FAQ](faq.md#worek-na-kg) i [jednostki](jednostki.md), plik "
        "[openapi.yaml](../../app/static/openapi.yaml), [zewnętrzny](https://example.com/x.md) oraz "
        "[kotwicę](#dalej).\n", encoding="utf-8")
    (d / "jednostki.md").write_text("<!-- Wygenerowano -->\n\n# Jednostki, aliasy i przeliczniki\n\nTreść.\n",
                                    encoding="utf-8")
    (d / "faq.md").write_text("<!-- Wygenerowano -->\n\n# Najczęstsze pytania\n\n<a id=\"worek-na-kg\"></a>\n\n"
                              "## Worki?\n\nTak.\n", encoding="utf-8")
    return d


def test_pages_named_after_h1_and_home(src, tmp_path):
    out = tmp_path / "wiki"
    written = _load().export_wiki(src, out, REPO, "main")
    names = sorted(p.name for p in written)
    assert names == sorted(["Home.md", "Jak-to-działa.md", "Jednostki,-aliasy-i-przeliczniki.md",
                            "Najczęstsze-pytania.md", "_Sidebar.md", "_Footer.md"])
    home = (out / "Home.md").read_text(encoding="utf-8")
    assert "export_help" not in home and "nie edytuj" in home.lower()  # własny nagłówek Wiki zamiast komentarza
    assert "### [Jak to działa](Jak-to-działa)" in home  # linki z README na strony Wiki


def test_links_rewritten(src, tmp_path):
    out = tmp_path / "wiki"
    _load().export_wiki(src, out, REPO, "main")
    md = (out / "Jak-to-działa.md").read_text(encoding="utf-8")
    raw = "https://raw.githubusercontent.com/AmigoUK/xml-parser/main/app/static/screenshots/02-pulpit.png"
    assert f"![Pulpit]({raw})" in md
    assert "[FAQ](Najczęstsze-pytania#worek-na-kg)" in md and "[jednostki](Jednostki,-aliasy-i-przeliczniki)" in md
    assert "[openapi.yaml](https://github.com/AmigoUK/xml-parser/blob/main/app/static/openapi.yaml)" in md
    assert "[zewnętrzny](https://example.com/x.md)" in md and "[kotwicę](#dalej)" in md
    assert '<a id="worek-na-kg"></a>' in (out / "Najczęstsze-pytania.md").read_text(encoding="utf-8")


def test_sidebar_faq_first_then_topics_in_readme_order(src, tmp_path):
    out = tmp_path / "wiki"
    _load().export_wiki(src, out, REPO, "main")
    sidebar = (out / "_Sidebar.md").read_text(encoding="utf-8")
    lines = [ln for ln in sidebar.splitlines() if ln.startswith("- ")]
    assert lines == ["- [Pomoc](Home)", "- **[Najczęstsze pytania (FAQ)](Najczęstsze-pytania)**",
                     "- [Jak to działa](Jak-to-działa)",
                     "- [Jednostki, aliasy i przeliczniki](Jednostki,-aliasy-i-przeliczniki)"]
    footer = (out / "_Footer.md").read_text(encoding="utf-8")
    assert REPO in footer and "docs/pomoc" in footer


def test_stale_generated_pages_removed_manual_kept(src, tmp_path):
    out = tmp_path / "wiki"
    out.mkdir()
    mod = _load()
    (out / "Stara.md").write_text(mod.MARKER + "\n# Stara\n", encoding="utf-8")
    (out / "Reczna.md").write_text("# Ręczna strona\n", encoding="utf-8")
    mod.export_wiki(src, out, REPO, "main")
    assert not (out / "Stara.md").exists() and (out / "Reczna.md").exists()


def test_real_docs_export_round_trip(tmp_path):
    """Prawdziwy docs/pomoc: każda strona ma nazwę, żaden link nie prowadzi już do pliku .md ani do ../../."""
    out = tmp_path / "wiki"
    written = _load().export_wiki(ROOT / "docs" / "pomoc", out, REPO, "main")
    assert {"Home.md", "_Sidebar.md", "Najczęstsze-pytania.md"} <= {p.name for p in written}
    for p in written:
        text = p.read_text(encoding="utf-8")
        assert "](../../" not in text and ".md)" not in text and ".md#" not in text, p.name


def test_cli_writes_out_dir(src, tmp_path, monkeypatch):
    mod = _load()
    out = tmp_path / "w"
    assert mod.main(["--src", str(src), "--out", str(out), "--repo", REPO, "--branch", "main"]) == 0
    assert (out / "Home.md").is_file()
