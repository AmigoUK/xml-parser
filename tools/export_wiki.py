#!/usr/bin/env python
"""Strony Wiki GitHub z wyeksportowanej Pomocy (docs/pomoc/*.md, wynik tools/export_help.py).

Uruchomienie:  python tools/export_wiki.py --out /sciezka/do/klonu/xml-parser.wiki
               (opcje: --src docs/pomoc, --repo https://github.com/<owner>/<repo>, --branch main)

Wiki jest tylko lustrem: źródłem prawdy pozostaje Pomoc w panelu → docs/pomoc; akcja .github/workflows/wiki.yml
uruchamia ten skrypt po każdym pushu na main i wypycha wynik do repozytorium Wiki. Skrypt używa wyłącznie biblioteki
standardowej (w akcji nie instaluje się zależności aplikacji).

Reguły: README.md → Home.md; każdy temat → strona o nazwie z nagłówka H1 (spacje → „-”, jak w adresach Wiki);
linki `<slug>.md[#kotwica]` → nazwa strony Wiki; obrazki `../../ścieżka` → raw.githubusercontent.com (Wiki nie
serwuje plików repozytorium), inne pliki repo → `/blob/<gałąź>/`; `_Sidebar.md` z FAQ na górze i `_Footer.md`.
Strony wygenerowane wcześniej (z MARKER), których już nie ma w źródle, są usuwane — ręczne strony Wiki zostają.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "docs" / "pomoc"
DEFAULT_REPO = "https://github.com/AmigoUK/xml-parser"
MARKER = ("<!-- Strona generowana automatycznie z Pomocy w panelu (docs/pomoc w repozytorium) — nie edytuj w Wiki, "
          "zmiany zostaną nadpisane przy następnym wydaniu. -->")
HOME = "Home"
FAQ_SLUG = "faq"
H1 = re.compile(r"^# (.+?)\s*$", re.MULTILINE)
HTML_COMMENT = re.compile(r"^<!--.*?-->\s*", re.DOTALL)
TOPIC_IN_README = re.compile(r"^### \[([^\]]+)\]\(([\w-]+)\.md\)", re.MULTILINE)
# [tekst](cel) i ![alt](cel) — cel bez spacji i nawiasów (tak generuje export_help.py)
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^()\s]+)\)")


def page_name(title: str) -> str:
    """Nazwa strony Wiki z tytułu: spacje → „-” (GitHub pokazuje je znów jako spacje), bez znaków łamiących adres."""
    name = re.sub(r"\s+", "-", title.strip())
    return re.sub(r"[/\\#?%*:|\"<>\[\]]", "", name)


def _title(markdown: str, fallback: str) -> str:
    m = H1.search(markdown)
    return m.group(1).strip() if m else fallback


def _rewrite_links(markdown: str, pages: dict[str, str], repo: str, branch: str) -> str:
    raw_base = repo.replace("https://github.com/", "https://raw.githubusercontent.com/", 1) + f"/{branch}/"
    blob_base = repo.rstrip("/") + f"/blob/{branch}/"

    def sub(m: re.Match) -> str:
        bang, text, target = m.groups()
        path, frag = (target.split("#", 1) + [""])[:2]
        frag = f"#{frag}" if frag else ""
        if re.match(r"^(https?:|mailto:)", target) or target.startswith("#"):
            return m.group(0)
        if path.endswith(".md") and path[:-3] in pages:
            return f"{bang}[{text}]({pages[path[:-3]]}{frag})"
        if path.startswith("../../"):
            rel = path[len("../../"):]
            return f"{bang}[{text}]({(raw_base if bang else blob_base)}{rel}{frag})"
        return m.group(0)

    return LINK.sub(sub, markdown)


def export_wiki(src_dir: Path | str, out_dir: Path | str, repo: str = DEFAULT_REPO, branch: str = "main") -> list[Path]:
    """Zapisuje strony Wiki do `out_dir`; zwraca zapisane pliki."""
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = {p.stem: p.read_text(encoding="utf-8") for p in sorted(src_dir.glob("*.md"))}
    if "README" not in sources:
        raise SystemExit(f"Brak {src_dir / 'README.md'} — najpierw tools/export_help.py.")
    readme = sources["README"]
    order = [(title, slug) for title, slug in TOPIC_IN_README.findall(readme) if slug in sources]
    titles = {slug: _title(sources[slug], slug) for slug in sources}
    pages = {slug: (HOME if slug == "README" else page_name(titles[slug])) for slug in sources}
    for title, slug in order:  # tytuł z README ma pierwszeństwo (ten sam co H1 tematu, ale pewniej)
        pages[slug] = page_name(title)

    written = []
    for slug, text in sources.items():
        body = HTML_COMMENT.sub("", text, count=1)
        body = _rewrite_links(body, pages, repo, branch)
        target = out_dir / f"{pages[slug]}.md"
        target.write_text(f"{MARKER}\n\n{body.rstrip()}\n", encoding="utf-8", newline="\n")
        written.append(target)

    items = [f"- [{_title(readme, 'Pomoc')}]({HOME})"]
    if FAQ_SLUG in pages:
        items.append(f"- **[{titles[FAQ_SLUG]} (FAQ)]({pages[FAQ_SLUG]})**")
    items += [f"- [{title}]({pages[slug]})" for title, slug in order if slug != FAQ_SLUG]
    sidebar = out_dir / "_Sidebar.md"
    sidebar.write_text(f"{MARKER}\n\n**Pomoc**\n\n" + "\n".join(items) + "\n", encoding="utf-8", newline="\n")
    footer = out_dir / "_Footer.md"
    footer.write_text(f"{MARKER}\n\nTreść generowana z sekcji Pomoc w panelu — źródło w repozytorium: "
                      f"[docs/pomoc]({repo.rstrip('/')}/tree/{branch}/docs/pomoc). Poprawki zgłaszaj w "
                      f"[{repo.removeprefix('https://github.com/')}]({repo}).\n", encoding="utf-8", newline="\n")
    written += [sidebar, footer]

    for old in out_dir.glob("*.md"):  # strony po usuniętych tematach — tylko wygenerowane przez ten skrypt
        if old not in written and old.read_text(encoding="utf-8").startswith(MARKER):
            old.unlink()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strony Wiki GitHub z docs/pomoc (wynik tools/export_help.py).")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="katalog z Markdown Pomocy (domyślnie docs/pomoc)")
    parser.add_argument("--out", required=True, help="katalog klonu repozytorium Wiki (<repo>.wiki.git)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="adres repozytorium na GitHub (dla obrazków i plików)")
    parser.add_argument("--branch", default="main", help="gałąź, z której serwowane są obrazki (domyślnie main)")
    args = parser.parse_args(argv)
    files = export_wiki(args.src, args.out, args.repo, args.branch)
    print(f"Zapisano {len(files)} stron Wiki w {args.out}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
