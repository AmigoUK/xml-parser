"""Przykłady integracji z Pomocy (app/help_examples/) uruchamiane naprawdę — każdy język wobec serwera HTTP
z tego procesu (wątek werkzeug, świeża SQLite w pliku). Brak środowiska (node, php z curl, curl+jq, requests)
= skip tylko tego języka, nie cicha zieleń."""
import functools
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db
from app.services.pipeline import ingest
from app.services.seed import seed_base, seed_demo
from app.web.help import integration_examples
from tests.test_learning import resolve_with_top_suggestions

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "demo" / "samples"
KEY = "xp_test_demo_key"
SHUTDOWN_POLL = 0.05  # serve_forever sprawdza żądanie zatrzymania co tyle sekund (domyślne 0,5 s wydłuża każdy test)
# Klucz ze zmiennej środowiskowej (jak w Pomocy); bash odpytuje najpierw po 1 s i czeka na operatora najwyżej 10 s
# (dokument, który przestałby być zatwierdzany od razu, szybko kończy test); żądania do 127.0.0.1 z pominięciem proxy,
# jeśli otoczenie jakieś ustawia.
EXAMPLE_ENV = {"XP_API_KEY": KEY, "DELAY": "1", "MAX_WAIT": "10", "no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"}


def _php_has_curl() -> bool:
    if not shutil.which("php"):
        return False
    res = subprocess.run(["php", "-m"], capture_output=True, text=True, timeout=30)
    return "curl" in res.stdout.split()


# id → (plik przykładu, interpreter, warunek dostępności środowiska)
RUNTIMES = {
    "python": ("integracja.py", sys.executable, lambda: importlib.util.find_spec("requests") is not None),
    "bash": ("integracja.sh", "bash", lambda: bool(shutil.which("curl") and shutil.which("jq"))),
    "node": ("integracja.mjs", "node", lambda: bool(shutil.which("node"))),
    "php": ("integracja.php", "php", _php_has_curl),
}


@functools.cache
def _available(runtime: str) -> bool:
    return RUNTIMES[runtime][2]()


def require_runtime(runtime: str) -> None:
    if not _available(runtime):
        pytest.skip(f"brak środowiska dla {runtime}")


@pytest.fixture(params=list(RUNTIMES))
def runtime(request):
    require_runtime(request.param)
    return request.param


@pytest.fixture
def live_api(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "WTF_CSRF_ENABLED": False, "DEMO_MODE": True,
                      "DEMO_API_KEY": KEY, "ADMIN_EMAIL": "admin@example.com", "ADMIN_PASSWORD": "haslo123",
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'live.db'}",
                      "STORAGE_DIR": str(tmp_path / "storage")})
    with app.app_context():
        db.create_all()
        seed_base()
        seed_demo()
        db.session.remove()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": SHUTDOWN_POLL}, daemon=True)
    thread.start()
    try:
        yield app, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()  # gniazdo zamyka sam serve_forever werkzeuga (server_close w finally)
        thread.join(timeout=10)
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        assert not thread.is_alive(), "wątek serwera nie zakończył się w 10 s"


class LegacyListHandler(BaseHTTPRequestHandler):
    """Serwer sprzed v0.5.0: lista dokumentów bez pola next_cursor (parametry synchronizacji ignoruje)."""

    def do_GET(self):
        if not self.path.startswith("/api/v1/documents"):
            self.send_error(404)
            return
        body = json.dumps({"items": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # bez dziennika żądań na stderr testów


@pytest.fixture
def legacy_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LegacyListHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": SHUTDOWN_POLL}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()  # serve_forever z biblioteki standardowej nie zamyka gniazda nasłuchującego
        assert not thread.is_alive(), "wątek serwera nie zakończył się w 10 s"


def example(tmp_path: Path, runtime: str, base: str) -> Path:
    """Przykład dokładnie w tej postaci, którą Pomoc pokazuje do skopiowania (adres serwera testowego w miejscu
    __API_BASE__), zapisany jako tmp_path/przyklady/<plik>."""
    name = RUNTIMES[runtime][0]
    code = next(ex["code"] for ex in integration_examples(base) if ex["file"] == name)
    assert f"{base}/api/v1" in code, name
    path = tmp_path / "przyklady" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def run(runtime: str, script: Path, cwd: Path, *args: str,
        extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Uruchamia przykład tak jak użytkownik; w katalogu cwd przykład zapisuje plik stanu i faktura-<id>.json.
    Interpreter jest szukany w PATH testu, więc extra_env (np. inny PATH) zmienia tylko to, co widzi sam przykład."""
    interpreter = RUNTIMES[runtime][1]
    cmd = [shutil.which(interpreter) or interpreter, str(script), *args]
    try:
        return subprocess.run(cmd, cwd=cwd, env={**os.environ, **EXAMPLE_ENV, **(extra_env or {})},
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
    except subprocess.TimeoutExpired as exc:  # wyjście sprzed przerwania przychodzi jako bajty, także przy text=True
        pytest.fail(f"przykład ({runtime}) nie zakończył się w {exc.timeout} s\n"
                    f"--- stdout ---\n{(exc.stdout or b'').decode('utf-8', 'replace')}\n"
                    f"--- stderr ---\n{(exc.stderr or b'').decode('utf-8', 'replace')}")


def output(res: subprocess.CompletedProcess) -> str:
    """Kod wyjścia i pełne wyjście przykładu — do komunikatów asercji."""
    return f"kod wyjścia {res.returncode}\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"


def sync_lines(res: subprocess.CompletedProcess) -> list[str]:
    """Linie przebiegu synchronizacji: jedna na dokument przetworzony w tym przebiegu."""
    return [line for line in res.stdout.splitlines() if line.startswith("#")]


def learn_alfa_template(app) -> None:
    """Szablon dostawcy Alfa nauczony na alfa-1.xml jak w testach uczenia: dokument z panelu (bez klucza API),
    operator wybiera pierwsze podpowiedzi z „zapamiętaj”. Kolejna faktura Alfy jest zatwierdzana bez operatora."""
    with app.app_context():
        doc = resolve_with_top_suggestions(ingest((SAMPLES / "alfa-1.xml").read_bytes(), "alfa-1.xml"))
        assert doc.status == "approved", doc.issues
        db.session.remove()


def api_get(app, path: str) -> dict:
    r = app.test_client().get(f"/api/v1{path}", headers={"X-API-Key": KEY})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def api_send(app, sample: str) -> dict:
    """Wysyłka próbki kluczem demo przez klient testowy (z pominięciem przykładu)."""
    r = app.test_client().post("/api/v1/documents", headers={"X-API-Key": KEY},
                               data={"file": (io.BytesIO((SAMPLES / sample).read_bytes()), sample)})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- sposób A: wysyłka, wynik, duplikat ----------------------------------------------------------------------------

def test_example_sends_invoice_and_reads_result(live_api, tmp_path, runtime):
    app, base = live_api
    learn_alfa_template(app)
    script = example(tmp_path, runtime, base)

    res = run(runtime, script, tmp_path, str(SAMPLES / "alfa-2.xml"))
    assert res.returncode == 0, output(res)
    items = api_get(app, "/documents")["items"]
    assert [item["status"] for item in items] == ["approved"], items
    doc_id = items[0]["id"]
    number = api_get(app, f"/documents/{doc_id}")["invoice"]["number"]
    assert f"Dokument #{doc_id}: approved" in res.stdout, output(res)
    if runtime == "bash":  # powłoka nie wypisuje numeru — wynik zapisuje do pliku i podaje jego nazwę
        assert f"Zapisano faktura-{doc_id}.json" in res.stdout, output(res)
        assert read_json(tmp_path / f"faktura-{doc_id}.json")["number"] == number
    else:
        assert number in res.stdout, output(res)

    res = run(runtime, script, tmp_path, str(SAMPLES / "alfa-2.xml"))  # ta sama faktura tym samym kluczem
    assert res.returncode == 0, output(res)
    assert re.search(rf"^Duplikat dokumentu #{doc_id}\b", res.stdout, re.M), output(res)
    # na serwerze nadal jedna zatwierdzona faktura; ponowna wysyłka to osobny dokument w statusie duplicate
    items = api_get(app, "/documents")["items"]  # od najnowszych
    assert [item["status"] for item in items] == ["duplicate", "approved"], items
    assert items[1]["id"] == doc_id, items


# --- sposób B: synchronizacja z plikiem stanu ----------------------------------------------------------------------

def test_example_sync_delivers_each_approved_document_once(live_api, tmp_path, runtime):
    app, base = live_api
    learn_alfa_template(app)
    script = example(tmp_path, runtime, base)
    state = tmp_path / "stan.json"

    a = api_send(app, "alfa-2.xml")
    assert a["status"] == "approved", a
    res = run(runtime, script, tmp_path, "--sync", "stan.json")
    assert res.returncode == 0, output(res)
    assert sync_lines(res) == [f"#{a['id']} approved {a['updated_at']} {a['invoice']['number']}"], output(res)
    if runtime == "bash":  # powłoka importuje zatwierdzony dokument do pliku
        assert read_json(tmp_path / f"faktura-{a['id']}.json")["number"] == a["invoice"]["number"]
    assert read_json(state) == {"last_sync": a["updated_at"], "seen": {str(a["id"]): a["updated_at"]}}

    # Faktura znana panelowi nie jest duplikatem dla klucza (duplikaty liczone w zakresie klucza API).
    b = api_send(app, "alfa-1.xml")
    assert b["status"] == "approved", b
    res = run(runtime, script, tmp_path, "--sync", "stan.json")
    assert res.returncode == 0, output(res)
    # dokument a wraca z API przez margines 5 min, ale jego para (id, updated_at) jest już w seen
    assert sync_lines(res) == [f"#{b['id']} approved {b['updated_at']} {b['invoice']['number']}"], output(res)
    if runtime == "bash":
        assert read_json(tmp_path / f"faktura-{b['id']}.json")["number"] == b["invoice"]["number"]
    both ={"last_sync": b["updated_at"], "seen": {str(a["id"]): a["updated_at"], str(b["id"]): b["updated_at"]}}
    assert read_json(state) == both

    res = run(runtime, script, tmp_path, "--sync", "stan.json")  # bez zmian w bazie
    assert res.returncode == 0, output(res)
    assert sync_lines(res) == [], output(res)
    assert read_json(state) == both


# --- błąd protokołu: serwer bez next_cursor ------------------------------------------------------------------------

def test_example_sync_fails_loudly_without_next_cursor(legacy_api, tmp_path, runtime):
    script = example(tmp_path, runtime, legacy_api)
    res = run(runtime, script, tmp_path, "--sync", "stan.json")
    assert res.returncode != 0, output(res)
    assert "Błąd protokołu" in res.stdout + res.stderr, output(res)
    state = tmp_path / "stan.json"
    if state.exists():  # bash zakłada domyślny plik stanu przed pierwszym żądaniem
        assert read_json(state)["last_sync"] is None  # stan nie został przesunięty


# --- bash: brak narzędzi i kształt pliku stanu ---------------------------------------------------------------------

def test_bash_example_reports_missing_curl_and_jq(live_api, tmp_path):
    """Bez curl i jq w PATH (np. cron z okrojonym PATH) przykład kończy się czytelnym komunikatem, zanim cokolwiek
    zapisze — a nie zakłada domyślnego pliku stanu, by potem nazwać go plikiem w złym formacie."""
    require_runtime("bash")
    _, base = live_api
    script = example(tmp_path, "bash", base)
    empty = tmp_path / "pusty-path"
    empty.mkdir()
    res = run("bash", script, tmp_path, "--sync", "stan.json", extra_env={"PATH": str(empty)})
    assert res.returncode == 1, output(res)
    assert "Brak programu curl" in res.stderr, output(res)  # curl sprawdzany jako pierwszy
    assert res.stdout == "", output(res)
    assert not (tmp_path / "stan.json").exists()


@pytest.mark.parametrize("bad_state, jq_diagnostics", [
    ("[]", []),
    # seen jako tablica (np. PHP bez JSON_FORCE_OBJECT) — dawniej błędy jq na stderr, kod 0 i stan bez zapisu
    ('{"last_sync": null, "seen": []}', []),
    ("{", ["parse error"]),  # niepoprawny JSON: komunikat jq zostaje widoczny przed wskazówką
], ids=["tablica", "seen-jako-tablica", "niepoprawny-json"])
def test_bash_sync_rejects_malformed_state_file(live_api, tmp_path, bad_state, jq_diagnostics):
    require_runtime("bash")
    _, base = live_api
    script = example(tmp_path, "bash", base)
    state = tmp_path / "stan.json"
    state.write_text(bad_state, encoding="utf-8")
    res = run("bash", script, tmp_path, "--sync", "stan.json")
    assert res.returncode == 1, output(res)
    assert res.stderr, output(res)
    *before, hint = res.stderr.splitlines()
    assert "zły format" in hint, output(res)  # wskazówka na końcu
    # przed nią tylko prawdziwa diagnostyka jq: przy niepoprawnym JSON-ie błąd składni, przy złym kształcie nic
    assert len(before) == len(jq_diagnostics), output(res)
    assert all(text in line for text, line in zip(jq_diagnostics, before)), output(res)
    assert res.stdout == "", output(res)  # nic nie przetworzono
    assert state.read_text(encoding="utf-8") == bad_state
