"""Skrypt app/help_examples/zestaw-demo.sh uruchamiany naprawdę wobec serwera HTTP (fixture live_api) —
fazy zestawu demo „Miesiąc faktur” wczytywane przez API zgodnie z manifestem."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.extensions import db
from app.services.pipeline import ingest
from tests.test_help_examples_run import EXAMPLE_ENV, ROOT, live_api, require_runtime  # noqa: F401
from tests.test_learning import resolve_with_top_suggestions

SCRIPT = ROOT / "app" / "help_examples" / "zestaw-demo.sh"
DATASET = ROOT / "demo" / "dataset"
MANIFEST = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
# Manifest opisuje wczytywanie z operatorem po drodze: 21 (eta-4) i 24 (zeta-4) są „approved” dopiero po rozwiązaniu
# w panelu 15 (towar) i 18 (zeta-3). Skrypt wysyła wszystko jednym ciągiem, więc te dwie czekają na operatora.
AWAIT_OPERATOR = {21, 24}
FILES = sorted(MANIFEST["files"], key=lambda f: f["order"])


def run_script(tmp_path: Path, base: str, *args: str, extra_env: dict | None = None):
    """Skrypt w postaci z Pomocy (adres serwera testowego w miejscu __API_BASE__), uruchomiony w tmp_path."""
    path = tmp_path / "zestaw-demo.sh"
    path.write_text(SCRIPT.read_text(encoding="utf-8").replace("__API_BASE__", base), encoding="utf-8")
    env = {**os.environ, **EXAMPLE_ENV, **(extra_env or {})}
    return subprocess.run([shutil.which("bash") or "bash", str(path), *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def lines_of(res) -> list[str]:
    return [ln for ln in res.stdout.splitlines() if ln.startswith("#")]


def test_script_is_valid_bash():
    require_runtime("bash")
    res = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_script_loads_first_phase_all_needs_review(live_api, tmp_path):
    require_runtime("bash")
    _, base = live_api
    res = run_script(tmp_path, base, "pierwsze")
    assert res.returncode == 0, res.stderr
    lines = lines_of(res)
    assert len(lines) == 6, res.stdout
    for line, f in zip(lines, [f for f in FILES if f["phase"] == "first"]):
        assert line.endswith(f" needs_review {f['filename']}"), line
    assert "needs_review: 6" in res.stdout


def test_script_rest_after_panel_learning_follows_manifest(live_api, tmp_path):
    require_runtime("bash")
    app, base = live_api
    with app.app_context():  # operator w panelu uczy się na sześciu pierwszych fakturach
        for f in FILES:
            if f["phase"] == "first":
                doc = ingest((DATASET / f["filename"]).read_bytes(), f["filename"])
                assert resolve_with_top_suggestions(doc).status == "approved", f["filename"]
        db.session.remove()
    res = run_script(tmp_path, base, "pozostale")
    assert res.returncode == 0, res.stderr
    rest = [f for f in FILES if f["phase"] == "rest"]
    lines = lines_of(res)
    assert len(lines) == len(rest) == 18, res.stdout
    for line, f in zip(lines, rest):
        expected = "needs_review" if f["order"] in AWAIT_OPERATOR else f["expected"]["on_ingest"]["status"]
        assert line.endswith(f" {expected} {f['filename']}"), line
    assert " duplicate 20-beta-3-ponownie.xml" in res.stdout


def test_script_reports_missing_jq(tmp_path):
    require_runtime("bash")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("curl", "dirname", "env"):
        if shutil.which(tool):
            (bindir / tool).symlink_to(shutil.which(tool))
    res = run_script(tmp_path, "http://127.0.0.1:9", "pierwsze", extra_env={"PATH": str(bindir)})
    assert res.returncode == 1
    assert "jq" in res.stderr and "Brak programu" in res.stderr


def test_script_unknown_phase_exits_1(tmp_path):
    require_runtime("bash")
    res = run_script(tmp_path, "http://127.0.0.1:9", "bzdura")
    assert res.returncode == 1
    assert "Użycie" in res.stderr
