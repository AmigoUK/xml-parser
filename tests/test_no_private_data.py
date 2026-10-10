"""Strażnik: realne dane z prywatnych faktur nie mogą trafić do repo.

Zakazane tokeny (nazwy, NIP-y) trzymamy WYŁĄCZNIE w lokalnym, ignorowanym przez git
pliku private/forbidden-tokens.txt (jeden token na linię, małe litery, # = komentarz).
Brak pliku = test skanujący jest pomijany.
"""
import re
import subprocess
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TOKENS_FILE = ROOT / "private" / "forbidden-tokens.txt"
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)  # ciągi liter/cyfr Unicode (diakrytyki nie rozbijają tokenu)
MIN_SUBSTRING_LEN = 5


def _fold(text: str) -> str:
    """Małe litery, bez diakrytyków (NFKD) — wariant ASCII."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).replace("ł", "l")


def _squash(text: str) -> str:
    """Usuwa wszystko poza literami/cyframi (separatory, białe znaki, myślniki, kropki)."""
    return "".join(c for c in text.lower() if c.isalnum())


def _variants(text: str) -> set[str]:
    return {_squash(text), _squash(_fold(text))}


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
    forbidden = {f for f in (x.strip().lower() for x in forbidden) if f}
    hits = set()
    # 1) dokładne dopasowanie tokenów (także po zwinięciu diakrytyków)
    folded_forbidden = {_fold(f) for f in forbidden}
    for t in TOKEN_RE.findall(text.lower()):
        if t in forbidden or _fold(t) in folded_forbidden:
            hits.add(t[:2] + "…")
    # 2) dopasowanie podciągu w tekście ze zwiniętymi separatorami (PL-123-456…, „Za żółć” itd.)
    haystacks = _variants(text)
    for f in forbidden:
        for needle in _variants(f):
            if len(needle) >= MIN_SUBSTRING_LEN and any(needle in h for h in haystacks):
                hits.add(f[:2] + "…")
    return hits


def test_clean_text_has_no_violations():
    assert find_violations("Hurtownia Alfa FA/2026/10/001 PL9990000011", {"zzfaketoken"}) == set()


def test_detection_positive_control():
    assert find_violations("Faktura od ZZFakeToken sp. z o.o.", {"zzfaketoken"}) == {"zz…"}


@pytest.mark.parametrize("text", [
    "NIP: PL-zz-fake-token", "zz fake  token", "ZZ.Fake.Token sp. z o.o.", "xx_zzfaketoken_yy",
    "zzfake\ntoken",
])
def test_detection_separator_variants(text):
    assert find_violations(text, {"zzfaketoken"}) == {"zz…"}


def test_detection_numeric_id_variants():
    for text in ("PL1234567890", "123-456-78-90", "NIP 123 456 78 90", "PL 123.456.78.90"):
        assert find_violations(text, {"1234567890"}) == {"12…"}


def test_detection_diacritics():
    assert find_violations("Firma Zażółćtoken Sp.", {"zażółćtoken"}) == {"za…"}
    assert find_violations("ZAZOLCTOKEN", {"zażółćtoken"}) == {"za…"}
    assert find_violations("zażółć-token", {"zażółćtoken"}) == {"za…"}
    assert find_violations("zazolc token", {"zażółćtoken"}) == {"za…"}


def test_short_tokens_do_not_substring_match():
    assert find_violations("abcdefg", {"cde"}) == set()
    assert find_violations("cde", {"cde"}) == {"cd…"}


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
