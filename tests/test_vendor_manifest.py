"""Manifest wendorowanych bibliotek (app/static/vendor/VERSIONS.md): każdy plik ma wpis z wersją, adresem źródła
i sumą SHA-256 zgodną z plikiem; nieużywanych bibliotek (htmx) nie ma; Alpine.js w buildzie CSP, więc CSP bez
'unsafe-eval'."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "app" / "static" / "vendor"
MANIFEST = VENDOR / "VERSIONS.md"
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`?([0-9][^|`]*?)`?\s*\|\s*<?(https://[^|>\s]+)>?\s*\|\s*`([0-9a-f]{64})`\s*\|$")


def _rows() -> dict[str, dict]:
    rows = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line.strip())
        if m:
            rows[m.group(1)] = {"library": m.group(2), "version": m.group(3), "source": m.group(4),
                                "sha256": m.group(5)}
    return rows


def test_manifest_lists_every_vendor_file_with_matching_checksum():
    rows = _rows()
    files = {p.name for p in VENDOR.iterdir() if p.name != "VERSIONS.md"}
    assert rows.keys() == files, (sorted(rows), sorted(files))
    for name, row in rows.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == row["sha256"], name
        assert row["source"].startswith("https://") and name in row["source"] or row["version"] in row["source"], name


def test_unused_htmx_removed_and_alpine_is_csp_build():
    files = {p.name for p in VENDOR.iterdir()}
    assert not any("htmx" in f for f in files)
    assert "alpine-csp.min.js" in files and "alpine.min.js" not in files
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "htmx" not in base and "vendor/alpine-csp.min.js" in base


def test_csp_has_no_unsafe_eval(client):
    csp = client.get("/login").headers["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp and "script-src 'self'" in csp
