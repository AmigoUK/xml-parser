"""tools/screenshots.py — zrzuty ekranu z odizolowanej instancji. Testy nie uruchamiają przeglądarki ani serwera:
lista stron odpowiada plikom w app/static/screenshots/, Playwright jest importowany leniwie, port żywego demo
jest odrzucany."""
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "screenshots.py"
SCREENSHOTS = ROOT / "app" / "static" / "screenshots"
# diagramy renderowane z Mermaid (docs/screenshots/*.mmd), nie zrzuty ekranu
NOT_SCREENSHOTS = {"diagram-przetwarzania", "diagram-przetwarzania-td"}


@pytest.fixture
def tool(monkeypatch):
    """Moduł narzędzia przy zablokowanym Playwright (import playwright kończy się ImportError)."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    spec = importlib.util.spec_from_file_location("screenshots_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_pages_match_screenshot_files(tool):
    names = [shot.name for shot in tool.PAGES]
    assert len(names) == len(set(names))
    assert set(names) == {p.stem for p in SCREENSHOTS.glob("*.png")} - NOT_SCREENSHOTS


def test_list_without_playwright(tool, capsys):
    assert tool.main(["--list"]) == 0
    out = capsys.readouterr().out
    for shot in tool.PAGES:
        assert shot.name in out and shot.path in out


def test_list_from_command_line():
    r = subprocess.run([sys.executable, str(TOOL), "--list"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "12-pomoc-integracja" in r.stdout and "/pomoc/integracja#odbior" in r.stdout


def test_refuses_live_demo_port(tool, capsys):
    assert tool.main(["--port", "18506"]) == 2
    assert "18506" in capsys.readouterr().err


def test_unknown_page_name(tool, capsys):
    assert tool.main(["--only", "99-nie-ma"]) == 2
    assert "99-nie-ma" in capsys.readouterr().err


def test_missing_playwright_explains_install_before_starting_server(tool, capsys, monkeypatch):
    monkeypatch.setattr(tool.subprocess, "Popen", lambda *a, **k: pytest.fail("serwer nie powinien startować"))
    assert tool.main(["--port", str(_free_port())]) == 2
    assert "pip install playwright" in capsys.readouterr().err
