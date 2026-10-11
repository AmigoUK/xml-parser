#!/usr/bin/env python
"""Eksport sekcji „Pomoc” z panelu do Markdown (docs/pomoc/), czytelnego na GitHubie.

Uruchomienie:  .venv/bin/python tools/export_help.py

Strony /pomoc i /pomoc/<slug> są renderowane klientem testowym Flask (SQLite w pamięci, domyślna
konfiguracja, bez .env), a ich <main> jest konwertowany prostym konwerterem HTML -> Markdown na lxml.
Dzięki temu wersja w repozytorium nie rozjeżdża się z panelem; pilnuje tego tests/test_help_export.py.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import lxml.html

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "pomoc"
BASE_URL = "http://localhost:18506"
HEADER = "<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->"

# Limity z konfiguracji domyślnej (app/config.py) — przypięte na stałe, żeby .env ani zmienne środowiska
# operatora nie zmieniały treści wygenerowanych plików.
DEFAULT_CONFIG = {
    "TESTING": True,
    "SECRET_KEY": "export-help",
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "WTF_CSRF_ENABLED": False,
    "DEMO_MODE": False,
    "MAX_DOCUMENT_BYTES": 10 * 1024 * 1024,
    "MAX_TREE_NODES": 200_000,
    "MAX_LINES": 5_000,
    "LOGIN_MAX_ATTEMPTS": 5,
    "LOGIN_LOCKOUT_MINUTES": 15,
    "LOGIN_MAX_ATTEMPTS_PER_IP": 20,
    "LOGIN_MAX_ATTEMPTS_PER_EMAIL": 50,
    "LOGIN_EMAIL_LOCKOUT_MINUTES": 5,
}

# ----------------------------------------------------------------------------------------------
# Konwerter HTML -> Markdown
# ----------------------------------------------------------------------------------------------

BR = " "  # znacznik łamania wiersza w tekście inline (zamieniany na końcu)
SKIP_TAGS = {"nav", "aside", "script", "style", "input", "form", "head", "template"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}
BLOCK_TAGS = {"p", "ul", "ol", "table", "pre", "dl", "div", "section", "article", "header", "footer",
              "blockquote", "li", "hr", *HEADINGS}
INTERNAL_HELP = re.compile(r"^/pomoc(?:/([\w-]+))?(#.*)?$")


def _is_block(el) -> bool:
    return isinstance(el.tag, str) and el.tag in BLOCK_TAGS


def _has_block(el) -> bool:
    return any(_is_block(d) for d in el.iterdescendants())


def _escape_text(s: str) -> str:
    s = s.replace("\\", "\\\\").replace("`", "\\`").replace("*", "\\*").replace("<", "&lt;")
    s = s.replace("[", "\\[").replace("]", "\\]")
    return re.sub(r"(?<![0-9A-Za-z])_|_(?![0-9A-Za-z])", r"\\_", s)


def _wrap(marker: str, inner: str) -> str:
    stripped = inner.strip()
    if not stripped:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()):]
    return f"{lead}{marker}{stripped}{marker}{trail}"


def _code_span(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    if not text.strip():
        return ""
    runs = re.findall(r"`+", text)
    fence = "`" * (max((len(r) for r in runs), default=0) + 1) if runs else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _link_target(href: str):
    """Zwraca ('md', url) dla linków do Markdown / zewnętrznych, ('code', path) dla ścieżek aplikacji."""
    href = (href or "").strip()
    m = INTERNAL_HELP.match(href)
    if m:
        slug, frag = m.group(1), m.group(2) or ""
        return "md", f"{slug or 'README'}.md{frag}"
    if href.startswith("#") or re.match(r"^(https?:|mailto:)", href):
        return "md", href
    if href.startswith("/"):
        return "code", href
    return "md", href


def inline(el, in_table: bool = False) -> str:
    """Treść elementu jako tekst inline (z markerem BR dla <br> i elementów blokowych)."""
    out = [_escape_text(el.text or "")] if el.text else []
    for ch in el:
        if isinstance(ch.tag, str):
            out.append(_inline_el(ch, in_table))
        if ch.tail:
            out.append(_escape_text(ch.tail))
    return "".join(out)


def _inline_el(el, in_table: bool) -> str:
    tag = el.tag
    if tag in SKIP_TAGS:
        return ""
    if tag == "br":
        return BR
    if tag == "code":
        return _code_span("".join(el.itertext()))
    if tag in ("strong", "b"):
        return _wrap("**", inline(el, in_table))
    if tag in ("em", "i"):
        return _wrap("*", inline(el, in_table))
    if tag == "a":
        inner = inline(el, in_table)
        kind, target = _link_target(el.get("href"))
        if kind == "code":
            if "`" in inner:  # tekst już jest kodem — wystarczy sam tekst
                return inner
            return f"{inner} ({_code_span(target)})" if inner.strip() else _code_span(target)
        return f"[{inner.strip()}]({target})" if inner.strip() else ""
    if tag in BLOCK_TAGS:
        sep = BR if in_table else " "
        return f"{sep}{inline(el, in_table)}{sep}" if tag != "li" else f"{sep}• {inline(el, in_table)}{sep}"
    return inline(el, in_table)  # span, button, small, ...


def finish_inline(s: str, in_table: bool = False) -> str:
    s = re.sub(r"[ \t\r\n\f\v ]+", " ", s)
    s = re.sub(r" ?" + BR + r" ?", BR, s)
    s = re.sub(BR + "{2,}", BR, s).strip(" " + BR)
    return s.replace(BR, "<br>" if in_table else "  \n")


def _anchor(el) -> str:
    i = el.get("id")
    return f'<a id="{i}"></a>' if i else ""


LANG_CLASS = re.compile(r"(?:^|\s)language-([\w+-]+)(?:\s|$)")


def _declared_lang(el) -> str:
    """Język z klasy `language-xxx` na <pre> albo na jego <code>."""
    for node in [el, *el.iterchildren("code")]:
        m = LANG_CLASS.search(node.get("class") or "")
        if m:
            return m.group(1)
    return ""


def _fence_block(el) -> str:
    text = "".join(el.itertext()).strip("\n").rstrip()
    runs = re.findall(r"`{3,}", text)
    fence = "`" * (max((len(r) for r in runs), default=2) + 1)
    first = text.lstrip()[:1]
    lang = _declared_lang(el) or ("bash" if text.lstrip().startswith("curl") else "json" if first in "{[" else "")
    return f"{fence}{lang}\n{text}\n{fence}"


def _cell(el) -> str:
    return finish_inline(inline(el, True), True).replace("|", "\\|")


def _table(el) -> str:
    rows = [tr for tr in el.iter("tr")]
    if not rows:
        return ""
    data = []
    for tr in rows:
        cells = [c for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
        texts = [_cell(c) for c in cells]
        if texts and tr.get("id"):
            texts[0] = f"{_anchor(tr)}{texts[0]}"
        data.append(texts)
    width = max(len(r) for r in data)
    data = [r + [""] * (width - len(r)) for r in data]
    lines = ["| " + " | ".join(data[0]) + " |", "|" + "|".join([" --- "] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in data[1:]]
    return "\n".join(lines)


def _list(el, depth: int = 0) -> str:
    ordered = el.tag == "ol"
    items = []
    n = 0
    for li in el:
        if not (isinstance(li.tag, str) and li.tag == "li"):
            continue
        n += 1
        marker = f"{n}. " if ordered else "- "
        parts = blocks(li)
        if not parts:
            continue
        body = ""
        for idx, (kind, text) in enumerate(parts):
            if idx == 0:
                body = text
            else:
                body += ("\n" if kind == "list" and parts[idx - 1][0] != "code" else "\n\n") + text
        pad = " " * len(marker)
        lines = body.split("\n")
        items.append(marker + lines[0] + "".join("\n" + (pad + ln if ln else "") for ln in lines[1:]))
    return "\n".join(items)


def _dl(el) -> str:
    out, term = [], None
    for ch in el:
        if not isinstance(ch.tag, str):
            continue
        if ch.tag == "dt":
            term = finish_inline(inline(ch))
        elif ch.tag == "dd":
            out.append(f"- **{term}** — {finish_inline(inline(ch))}" if term else f"- {finish_inline(inline(ch))}")
    return "\n".join(out)


def blocks(el) -> list[tuple[str, str]]:
    """Dzieci elementu jako lista bloków (rodzaj, markdown); ciągi inline scalane w akapity."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        text = finish_inline("".join(buf))
        buf.clear()
        if text:
            out.append(("p", text))

    if el.text:
        buf.append(_escape_text(el.text))
    for ch in el:
        if isinstance(ch.tag, str) and ch.tag not in SKIP_TAGS:
            if _is_block(ch) or (ch.tag == "a" and _has_block(ch)):
                flush()
                out.extend(_block(ch))
            else:
                buf.append(_inline_el(ch, False))
        if ch.tail:
            buf.append(_escape_text(ch.tail))
    flush()
    return out


def _block(el) -> list[tuple[str, str]]:
    tag = el.tag
    if tag in HEADINGS:
        text = finish_inline(inline(el))
        anchor = _anchor(el) if el.get("id") and not el.get("id").startswith("faq-h") else ""
        res = []
        if anchor:
            res.append(("a", anchor))
        res.append(("h", f"{'#' * HEADINGS[tag]} {text}"))
        return res
    if tag == "p":
        text = finish_inline(inline(el))
        return [("p", text)] if text else []
    if tag in ("ul", "ol"):
        text = _list(el)
        return [("list", text)] if text else []
    if tag == "table":
        text = _table(el)
        return [("table", text)] if text else []
    if tag == "pre":
        return [("code", _fence_block(el))]
    if tag == "dl":
        text = _dl(el)
        return [("list", text)] if text else []
    if tag == "hr":
        return [("p", "---")]
    if tag == "a":  # link blokowy (karta): nagłówek staje się linkiem, reszta zostaje bez zmian
        kind, target = _link_target(el.get("href"))
        res = blocks(el)
        if kind == "md":
            res = [(k, re.sub(r"^(#+) (.*)$", lambda m: f"{m.group(1)} [{m.group(2)}]({target})", t, count=1))
                   if k == "h" else (k, t) for k, t in res]
        return res
    return blocks(el)  # div, section, li, blockquote, ... — przezroczyste


def html_to_markdown(root) -> str:
    parts = [text for _, text in blocks(root)]
    return "\n\n".join(parts).strip() + "\n"


# ----------------------------------------------------------------------------------------------
# Eksport
# ----------------------------------------------------------------------------------------------

def _build_client():
    """Aplikacja w pamięci z konfiguracją domyślną; .env nie jest wczytywany."""
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"  # przed pierwszym importem app.config (pomija wtedy load_dotenv)
    from app import create_app
    from app.extensions import db

    app = create_app(dict(DEFAULT_CONFIG))
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    return app, db, ctx


def render_page(client, path: str) -> str:
    resp = client.get(path, base_url=BASE_URL)
    if resp.status_code != 200:
        raise RuntimeError(f"{path}: HTTP {resp.status_code}")
    doc = lxml.html.fromstring(resp.data.decode("utf-8"))
    mains = doc.xpath("//main")
    if not mains:
        raise RuntimeError(f"{path}: brak <main>")
    return HEADER + "\n\n" + html_to_markdown(mains[0])


def export_help(out_dir: Path | str = DEFAULT_OUT) -> list[Path]:
    """Generuje README.md i <slug>.md do `out_dir`; zwraca zapisane pliki."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    app, db, ctx = _build_client()
    try:
        from app.help_content import TOPICS
        client = app.test_client()
        pages = {"README.md": "/pomoc", **{f"{t['slug']}.md": f"/pomoc/{t['slug']}" for t in TOPICS}}
        written = []
        for name, path in pages.items():
            target = out_dir / name
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(render_page(client, path))
            written.append(target)
        for old in out_dir.glob("*.md"):  # pliki po usuniętych tematach
            if old not in written and old.read_text(encoding="utf-8").startswith(HEADER):
                old.unlink()
        return written
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def main() -> int:
    files = export_help(DEFAULT_OUT)
    print(f"Zapisano {len(files)} plików w {DEFAULT_OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
