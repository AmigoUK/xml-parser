"""tools/screenshots.py — zrzuty ekranu z odizolowanej instancji. Testy nie uruchamiają przeglądarki: lista stron
odpowiada plikom w app/static/screenshots/, Playwright jest importowany leniwie, port żywego demo jest odrzucany,
środowisko serwera jest odizolowane od ustawień operatora, a błąd startu serwera albo przeglądarki kończy się
komunikatem (kod wyjścia 2), nie tracebackiem. Jeden test uruchamia prawdziwy podproces serwera (--serve) na wolnym
porcie, z bazą w katalogu tymczasowym."""
import importlib.util
import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

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


def test_samples_exist_and_resolve_modes_are_known(tool):
    """Próbki narzędzia istnieją w demo/samples; tryb to True/False albo kod problemu z rejestru Pomocy (operator
    zatrzymuje się na nim — dokument „w trakcie” negocjacji, np. karta „brak przelicznika” do FAQ)."""
    from app.help_content import ISSUE_HELP
    for name, mode in tool.SAMPLES:
        assert (ROOT / "demo" / "samples" / name).is_file(), name
        assert mode in (True, False) or mode in ISSUE_HELP, (name, mode)
    assert dict(tool.SAMPLES)["zeta.csv"] == "missing_conversion"
    faq = next(shot for shot in tool.PAGES if shot.name == "13-faq-worek")
    assert faq.path == f"/dokumenty/{tool.ZETA_ID}"


def test_dataset_first_phase_offsets_document_ids(tool):
    """Instancja zrzutów wczytuje pierwszą fazę zestawu demo przed próbkami, więc id próbek przesuwają się o liczbę
    wpisów „first” z prawdziwego manifestu (6); DOC_ID/ZETA_ID i adresy w PAGES odzwierciedlają przesunięcie."""
    from app.services.demo_dataset import load_manifest
    first = len(load_manifest().by_phase("pierwsze"))
    assert first == 6
    assert tool.dataset_offset() == first
    names = [name for name, _ in tool.SAMPLES]
    assert tool.DOC_ID == first + names.index("gamma-ubl.xml") + 1
    assert tool.ZETA_ID == first + names.index("zeta.csv") + 1
    paths = {shot.name: shot.path for shot in tool.PAGES}
    assert paths["04-dokument"] == f"/dokumenty/{tool.DOC_ID}"
    assert paths["05-edytor-mapowan"] == f"/szablony/dokument/{tool.DOC_ID}/edytor"
    assert paths["14-demo-zestaw"] == "/demo#zestaw"


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


def test_server_env_isolates_instance_from_operator_settings(tool, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    monkeypatch.setenv("MAX_CONTENT_LENGTH", "5")
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    env = tool.server_env("haslo-jednorazowe")
    for name in ("DATABASE_URL", "SESSION_COOKIE_SECURE", "MAX_CONTENT_LENGTH", "TRUSTED_PROXY_COUNT"):
        assert name not in env
    assert env["PATH"] == os.environ["PATH"]  # reszta środowiska zostaje (interpreter, locale)
    assert env["DEMO_MODE"] == "1" and env["ADMIN_PASSWORD"] == "haslo-jednorazowe"
    assert env["PYTHON_DOTENV_DISABLED"] == "1" and env["FLASK_SKIP_DOTENV"] == "1"
    assert env["DEMO_API_KEY"] == tool.DEMO_API_KEY and len(env["SECRET_KEY"]) == 64


def test_serve_requires_workdir(tool):
    with pytest.raises(SystemExit) as exc:
        tool.main(["--serve"])
    assert exc.value.code == 2


def test_running_server_reports_unstartable_interpreter(tool, tmp_path):
    with pytest.raises(tool.ToolError, match="nie-ma-takiego-pythona"):
        with tool.running_server(str(tmp_path / "nie-ma-takiego-pythona"), _free_port(), tmp_path, "x"):
            pytest.fail("serwer nie powinien wystartować")


def test_running_server_reports_early_exit_with_log(tool, tmp_path):
    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/sh\necho 'brak modulu flask' >&2\nexit 3\n", encoding="utf-8")
    fake.chmod(0o755)
    with pytest.raises(tool.ToolError, match=r"kodem 3[\s\S]*brak modulu flask"):
        with tool.running_server(str(fake), _free_port(), tmp_path, "x"):
            pytest.fail("serwer nie powinien wystartować")


@pytest.mark.parametrize("fail_at", ["new_context", "log_in"])
def test_browser_error_before_shots_is_tool_error(tool, tmp_path, fail_at):
    """Błąd Playwright przed pierwszym zrzutem (kontekst przeglądarki albo logowanie) to ToolError — kod wyjścia 2,
    nie traceback — a przeglądarka i tak jest zamykana. Fałszywy Playwright: testy nie uruchamiają przeglądarki."""
    class FakeError(Exception):
        pass

    def boom(*args, **kwargs):
        raise FakeError("przeglądarka padła")

    closed = []
    page = SimpleNamespace(on=lambda *args: None, goto=boom if fail_at == "log_in" else lambda url: None)
    context = SimpleNamespace(new_page=lambda: page)
    browser = SimpleNamespace(new_context=boom if fail_at == "new_context" else lambda **kwargs: context,
                              close=lambda: closed.append(True))
    pw = SimpleNamespace(chromium=SimpleNamespace(launch=lambda: browser))

    @contextmanager
    def fake_sync_playwright():
        yield pw

    with pytest.raises(tool.ToolError, match=r"Błąd przeglądarki przed zrzutami: przeglądarka padła"):
        tool.take_screenshots((fake_sync_playwright, FakeError), "http://127.0.0.1:1", tool.PAGES[:1], tmp_path, "x")
    assert closed == [True]


def test_serve_mode_starts_isolated_instance(tool, tmp_path):
    """Prawdziwy podproces --serve (świeża SQLite w tmp, seed i nauka na próbkach): /healthz z wersją aplikacji,
    /demo dostępne; serwer zatrzymany po PID. Najwolniejszy test tego modułu (kilkanaście sekund)."""
    import urllib.request

    from app.version import __version__
    with tool.running_server(sys.executable, _free_port(), tmp_path, "haslo-testowe-123") as base:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base + "/healthz", timeout=10) as r:
            health = json.load(r)
        assert health["status"] == "ok" and health["version"] == __version__
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base + "/demo", timeout=10) as r:
            assert r.status == 200
        # TODO (kontroler, po scaleniu karty zestawu z T3): dodać assert "Zestaw demo" w treści /demo
        # (tu: /dokumenty wymaga logowania, więc sprawdzamy log startu — sześć plików zestawu wczytanych przed próbkami)
    from app.services.demo_dataset import load_manifest
    log = (tmp_path / "serwer.log").read_text(encoding="utf-8")
    for entry in load_manifest().by_phase("pierwsze"):
        assert f": {entry.filename} — " in log, entry.filename
    assert "dokument 7: alfa-1.xml" in log
    assert (tmp_path / "serwer.log").read_text(encoding="utf-8").count(tool.READY) == 1


def test_refuses_app_port_from_environment_and_env_file(tool, capsys, monkeypatch, tmp_path):
    """Strażnik „nie fotografuj żywego demo” zna port z APP_PORT (środowisko i .env), nie tylko domyślny 18506."""
    monkeypatch.setenv("APP_PORT", "18599")
    assert tool.main(["--port", "18599"]) == 2
    assert "18599" in capsys.readouterr().err
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=x\nAPP_PORT=18777\n", encoding="utf-8")
    assert tool.live_demo_ports(env_file) == {18506, 18599, 18777}
    monkeypatch.delenv("APP_PORT")
    env_file.write_text("APP_PORT=nie-liczba\n", encoding="utf-8")
    assert tool.live_demo_ports(env_file) == {18506}
    assert tool.live_demo_ports(tmp_path / "nie-ma") == {18506}
