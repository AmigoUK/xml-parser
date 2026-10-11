"""Obrazki i odnośniki w README i docs/pomoc/ (Markdown na GitHubie) wskazują istniejące pliki w repozytorium.

Zrzuty ekranu leżą w app/static/screenshots/ — jedno źródło dla Pomocy w panelu i README (docs/ nie trafia do obrazu
Docker); w docs/screenshots/ zostają grafika repozytorium (social preview) i źródło diagramu (Mermaid)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN = [ROOT / "README.md", *sorted((ROOT / "docs" / "pomoc").glob("*.md"))]
# ![alt](cel) lub [tekst](cel), opcjonalnie z tytułem; w tekście dozwolone escapowane \[ \]
LINK = re.compile(r"(!?)\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
EXTERNAL = re.compile(r"^(?:https?:|mailto:|#)")


def _targets(md: Path) -> list[tuple[bool, str]]:
    """(czy obrazek, cel) dla każdego obrazka i odnośnika w pliku Markdown."""
    return [(bang == "!", target) for bang, target in LINK.findall(md.read_text(encoding="utf-8"))]


@pytest.mark.parametrize("md", MARKDOWN, ids=lambda p: str(p.relative_to(ROOT)))
def test_markdown_images_and_links_point_to_repo_files(md):
    broken = []
    for is_image, target in _targets(md):
        if EXTERNAL.match(target):
            continue  # odznaki CI/wydania, strony WWW, kotwice w tym samym pliku
        path = (md.parent / target.split("#", 1)[0]).resolve()
        if not (path.is_relative_to(ROOT) and (path.is_file() if is_image else path.exists())):
            broken.append(("obrazek " if is_image else "odnośnik ") + target)
    assert not broken, f"{md.relative_to(ROOT)}: {broken}"


def test_screenshots_have_single_source():
    """README i eksport Pomocy pokazują zrzuty z app/static/screenshots/ (to samo źródło co Pomoc w panelu)."""
    readme = [t for is_image, t in _targets(ROOT / "README.md") if is_image and not EXTERNAL.match(t)]
    assert readme and all(t.startswith("app/static/screenshots/") for t in readme), readme
    help_images = [t for md in MARKDOWN[1:] for is_image, t in _targets(md) if is_image]
    assert help_images and all(t.startswith("../../app/static/screenshots/") for t in help_images), help_images
