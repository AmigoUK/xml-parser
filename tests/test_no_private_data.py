"""Strażnik: realne dane z prywatnych faktur nie mogą trafić do repo.

Zakazane tokeny (nazwy, NIP-y) trzymamy WYŁĄCZNIE w lokalnym, ignorowanym przez git
pliku private/forbidden-tokens.txt (jeden token na linię, małe litery, # = komentarz).
Brak pliku = test skanujący jest pomijany.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TOKENS_FILE = ROOT / "private" / "forbidden-tokens.txt"
TOKEN_RE = re.compile(r"[a-z0-9]+")


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [ROOT / p for p in out.split("\0") if p]


def load_forbidden_tokens() -> set[str]:
    if not TOKENS_FILE.is_file():
        return set()
    lines = TOKENS_FILE.read_text(encoding="utf-8").splitlines()
    return {l.strip().lower() for l in lines if l.strip() and not l.lstrip().startswith("#")}


def find_violations(text: str, forbidden: set[str] | None = None) -> set[str]:
    if forbidden is None:
        forbidden = load_forbidden_tokens()
    return {t[:2] + "…" for t in TOKEN_RE.findall(text.lower()) if t in forbidden}


def test_clean_text_has_no_violations():
    assert find_violations("Hurtownia Alfa FA/2026/10/001 PL9990000011", {"zzfaketoken"}) == set()


def test_detection_positive_control():
    assert find_violations("Faktura od ZZFakeToken sp. z o.o.", {"zzfaketoken"}) == {"zz…"}


def test_private_dir_is_ignored():
    res = subprocess.run(
        ["git", "check-ignore", "private/samples/x.xml"], cwd=ROOT, capture_output=True
    )
    assert res.returncode == 0, "katalog private/ musi być w .gitignore"


def test_forbidden_tokens_file_is_ignored():
    res = subprocess.run(
        ["git", "check-ignore", "private/forbidden-tokens.txt"], cwd=ROOT, capture_output=True
    )
    assert res.returncode == 0, "private/forbidden-tokens.txt musi być w .gitignore"


def test_no_private_data_in_tracked_files():
    forbidden = load_forbidden_tokens()
    if not forbidden:
        pytest.skip("Brak private/forbidden-tokens.txt — skan danych prywatnych pominięty")
    problems = {}
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = find_violations(text, forbidden)
        if hits:
            problems[str(path.relative_to(ROOT))] = sorted(hits)
    assert not problems, f"Prywatne dane w śledzonych plikach: {problems}"
