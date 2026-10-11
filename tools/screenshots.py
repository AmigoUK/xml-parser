#!/usr/bin/env python
"""Zrzuty ekranu panelu do app/static/screenshots/ (tematy Pomocy w panelu i README) z odizolowanej instancji.

Uruchomienie (z katalogu repozytorium):

    .venv/bin/python tools/screenshots.py                             # wszystkie zrzuty
    .venv/bin/python tools/screenshots.py --only 08-pomoc 11-api-docs   # wybrane
    .venv/bin/python tools/screenshots.py --list                      # lista stron (bez Playwright)

Zrzuty odświeża się po każdym wydaniu — stopka pokazuje wersję aplikacji. Nigdy nie fotografuj żywego demo.

Instancja: osobny podproces z aplikacją z repozytorium na 127.0.0.1:<port> (domyślnie 18517; port żywego demo 18506
jest odrzucany, zajęty port też), świeża SQLite i storage w katalogu tymczasowym, bez lokalnego .env
(PYTHON_DOTENV_DISABLED=1, FLASK_SKIP_DOTENV=1) i bez zmiennych konfiguracji z otoczenia (ENV_PREFIXES), DEMO_MODE=1,
fikcyjne konto admin@example.com z hasłem losowanym przy każdym uruchomieniu i fikcyjny klucz API demo. Dane — tylko
próbki z demo/samples/ (SAMPLES): nauka na alfa-1.xml pętlą „pierwsza podpowiedź + zapamiętaj” z testów uczenia, potem
alfa-2 (zatwierdzona automatycznie), beta-ksef i delta (rozwiązane), gamma-ubl i epsilon (czekają do wyjaśnienia).
Przeglądarka: Chromium z Playwright, okno 1400×900, device_scale_factor=1, locale pl-PL. Pliki PNG w katalogu
wyjściowym są nadpisywane; na końcu narzędzie wypisuje listę plików i błędy konsoli przeglądarki, zatrzymuje serwer
(po PID własnego podprocesu) i usuwa katalog tymczasowy.

Playwright to zależność opcjonalna, tylko dla tego narzędzia (nie ma jej w requirements aplikacji):

    pip install playwright && playwright install chromium

Może leżeć w osobnym venv: serwer działa w podprocesie z .venv/bin/python repozytorium (albo z interpretera
z --app-python), więc venv z Playwright nie potrzebuje zależności aplikacji, np.

    /ścieżka/pw-venv/bin/python tools/screenshots.py

Serwer korzysta z tests/test_learning.py, więc interpreter aplikacji potrzebuje też pytest (requirements-dev.txt).

Kod wyjścia: 0 — wszystkie zrzuty bez błędów konsoli przeglądarki; 1 — część zrzutów nieudana albo błędy konsoli;
2 — błąd przygotowania (nieznany zrzut, port, brak Playwright, start serwera, logowanie).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "app" / "static" / "screenshots"
HOST = "127.0.0.1"
DEFAULT_PORT = 18517
LIVE_DEMO_PORT = 18506  # żywe demo — zrzuty tylko z odizolowanej instancji
ADMIN_EMAIL = "admin@example.com"
DEMO_API_KEY = "xp_demo_zrzuty_0000000000"  # fikcyjny i stały — widać go na zrzucie strony „O demo”
VIEWPORT = {"width": 1400, "height": 900}
SETTLE_MS = 600  # pauza po „networkidle” (Alpine.js, czcionki, przewinięcie do kotwicy)
READY = "SERWER GOTOWY"
SERVER_TIMEOUT = 180  # s na start instancji (seed i nauka na próbkach)
# Zmienne czytane przez app/config.py — usuwane ze środowiska serwera, żeby instancja nie przejęła bazy, sekretów ani
# limitów z otoczenia operatora (limity widać w Pomocy, SESSION_COOKIE_SECURE=1 zablokowałby logowanie po HTTP).
ENV_PREFIXES = ("DATABASE_", "MARIADB", "ADMIN_", "DEMO_", "SECRET", "STORAGE", "MAX_", "LOGIN_",
                "SESSION_COOKIE", "REMEMBER_COOKIE", "TRUSTED_PROXY")
INSTALL_HINT = ("Brak Playwright — zainstaluj (może być osobny venv, serwer i tak działa z .venv/bin/python):\n"
                "  pip install playwright && playwright install chromium")


class Shot(NamedTuple):
    name: str  # plik <name>.png
    path: str  # adres w panelu
    full_page: bool  # cała strona albo tylko okno 1400×900
    wait_for: str | None = None  # selektor, na który trzeba poczekać po załadowaniu


# Próbki demo w kolejności wgrywania; True = problemy rozwiązane pętlą „pierwsza podpowiedź + zapamiętaj”.
# Baza jest świeża, więc id dokumentu = pozycja na liście (sprawdzane w serve()).
SAMPLES = [("alfa-1.xml", True), ("alfa-2.xml", False), ("beta-ksef.xml", True), ("delta.csv", True),
           ("gamma-ubl.xml", False), ("epsilon.json", False)]
DOC_ID = [name for name, _ in SAMPLES].index("gamma-ubl.xml") + 1  # nowy dostawca z problemami do wyjaśnienia

PAGES = [
    Shot("01-demo", "/demo", True),
    Shot("02-pulpit", "/pulpit", True),
    Shot("03-kolejka", "/kolejka", True),
    Shot("04-dokument", f"/dokumenty/{DOC_ID}", True),
    Shot("05-edytor-mapowan", f"/szablony/dokument/{DOC_ID}/edytor", False),
    Shot("06-kartoteka", "/towary", True),
    Shot("07-przeliczniki", "/przeliczniki", True),
    Shot("08-pomoc", "/pomoc", True),
    Shot("09-pomoc-problemy", "/pomoc/statusy-i-problemy", False),
    Shot("10-szablony", "/szablony", True),
    Shot("11-api-docs", "/api/docs", False, wait_for=".opblock-summary-path"),  # Swagger UI wyrenderował specyfikację
    Shot("12-pomoc-integracja", "/pomoc/integracja#odbior", False),
]


class ToolError(Exception):
    """Błąd przygotowania lub uruchomienia instancji — komunikat dla użytkownika (kod wyjścia 2)."""


# ----------------------------------------------------------------------------------------------
# Serwer: podproces z odizolowaną instancją
# ----------------------------------------------------------------------------------------------

def serve(port: int, workdir: Path) -> None:
    """Tryb podprocesu (--serve): instancja ze stanem do zrzutów; ustawienia i hasło przychodzą w środowisku od
    procesu nadrzędnego (server_env), baza i storage — w `workdir`."""
    if os.environ.get("DEMO_MODE") != "1" or not os.environ.get("ADMIN_PASSWORD"):
        raise SystemExit("Tryb --serve uruchamia tools/screenshots.py — nie wywołuj go ręcznie.")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"  # przed importem app.config: lokalny .env nie jest wczytywany
    sys.path.insert(0, str(ROOT))
    from werkzeug.serving import make_server

    from app import create_app
    from app.extensions import db
    from app.services.pipeline import ingest
    from app.services.seed import seed_base, seed_demo
    # narzędzie deweloperskie: ta sama pętla „operatora” (pierwsza podpowiedź + zapamiętaj) co w testach uczenia
    from tests.test_learning import resolve_with_top_suggestions

    app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{workdir / 'zrzuty.db'}",
                      "STORAGE_DIR": str(workdir / "storage")})
    samples = ROOT / "demo" / "samples"
    with app.app_context():
        db.create_all()
        seed_base()
        seed_demo()
        for expected_id, (name, resolve) in enumerate(SAMPLES, start=1):
            doc = ingest((samples / name).read_bytes(), name, source="demo")
            if resolve:
                resolve_with_top_suggestions(doc)
            print(f"  dokument {doc.id}: {name} — {doc.status}", flush=True)
            if doc.id != expected_id:
                raise SystemExit(f"Oczekiwano dokumentu {expected_id}, jest {doc.id} — adresy w PAGES byłyby złe.")
    server = make_server(HOST, port, app, threaded=True)
    print(READY, flush=True)
    server.serve_forever()


def server_env(password: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(ENV_PREFIXES)}
    env.update({
        "PYTHON_DOTENV_DISABLED": "1",  # app/config.py nie woła load_dotenv()
        "FLASK_SKIP_DOTENV": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",  # log serwera (polskie znaki) niezależnie od locale
        "DEMO_MODE": "1",
        "ADMIN_EMAIL": ADMIN_EMAIL,
        "ADMIN_PASSWORD": password,  # w środowisku, nie w argumentach — nie widać go w liście procesów
        "SECRET_KEY": secrets.token_hex(32),
        "DEMO_API_KEY": DEMO_API_KEY,
    })
    return env


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # TIME_WAIT po poprzednim przebiegu nie blokuje
        try:
            s.bind((HOST, port))
        except OSError:
            return False
    return True


def _log_tail(log_path: Path, lines: int = 30) -> str:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return "\n".join(text.splitlines()[-lines:])


@contextmanager
def running_server(app_python: str, port: int, workdir: Path, password: str):
    """Uruchamia serwer w podprocesie i czeka na gotowość; na końcu zatrzymuje go po PID (bez pkill)."""
    log_path = workdir / "serwer.log"
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(
            [app_python, str(Path(__file__).resolve()), "--serve", "--port", str(port), "--workdir", str(workdir)],
            cwd=ROOT, env=server_env(password), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + SERVER_TIMEOUT
        while READY not in log_path.read_text(encoding="utf-8", errors="replace"):
            if proc.poll() is not None:
                raise ToolError(f"Serwer zakończył się z kodem {proc.returncode}:\n{_log_tail(log_path)}")
            if time.monotonic() > deadline:
                raise ToolError(f"Serwer nie wystartował w {SERVER_TIMEOUT} s:\n{_log_tail(log_path)}")
            time.sleep(0.2)
        base = f"http://{HOST}:{port}"
        no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # zmienne *_proxy nie dotyczą 127.0.0.1
        try:
            with no_proxy.open(f"{base}/healthz", timeout=10) as r:
                health = json.load(r)
        except (OSError, ValueError) as e:
            raise ToolError(f"Serwer nie odpowiada na {base}/healthz: {e}\n{_log_tail(log_path)}") from e
        if health.get("status") != "ok":
            raise ToolError(f"/healthz zwraca {health}")
        print(f"Instancja v{health.get('version')} na {base} (świeża SQLite w katalogu tymczasowym, "
              f"konto {ADMIN_EMAIL} z jednorazowym hasłem):")
        print("\n".join(ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.startswith("  dokument")))
        yield base
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


# ----------------------------------------------------------------------------------------------
# Przeglądarka
# ----------------------------------------------------------------------------------------------

def load_playwright():
    """(sync_playwright, Error) albo None — import leniwy, więc --list i testy działają bez Playwright."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return None
    return sync_playwright, Error


def log_in(page, base: str, password: str) -> None:
    page.goto(f"{base}/login")
    page.fill("input[name=email]", ADMIN_EMAIL)
    page.fill("input[name=password]", password)
    page.click("form button")
    page.wait_for_load_state("networkidle")
    if page.url.rstrip("/").endswith("/login") or "Wyloguj" not in page.content():
        raise ToolError(f"Logowanie kontem {ADMIN_EMAIL} nie powiodło się ({page.url}).")


def take_screenshots(playwright, base: str, shots: list[Shot], out: Path, password: str):
    """Zrzuty kolejnych stron po zalogowaniu; zwraca (zapisane pliki z adresem i tytułem, błędy przeglądarki)."""
    sync_playwright, playwright_error = playwright
    out.mkdir(parents=True, exist_ok=True)
    written, errors = [], []
    current = {"name": "logowanie"}

    def on_console(message):
        if message.type == "error":
            errors.append(f"{current['name']}: {message.text}")

    def on_page_error(error):
        errors.append(f"{current['name']}: {error}")

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except playwright_error as e:
            raise ToolError(f"Nie udało się uruchomić Chromium — playwright install chromium.\n{e}") from e
        try:
            page = browser.new_context(viewport=VIEWPORT, device_scale_factor=1, locale="pl-PL").new_page()
            page.on("console", on_console)
            page.on("pageerror", on_page_error)
            log_in(page, base, password)
            for shot in shots:
                current["name"] = shot.name
                print(f"  {shot.name} ← {shot.path}", flush=True)
                try:
                    page.goto(base + shot.path)
                    page.wait_for_load_state("networkidle")
                    if shot.wait_for:
                        page.wait_for_selector(shot.wait_for)
                    page.wait_for_timeout(SETTLE_MS)
                    target = out / f"{shot.name}.png"
                    page.screenshot(path=str(target), full_page=shot.full_page)
                except playwright_error as e:
                    errors.append(f"{shot.name}: zrzut nieudany — {e}")
                    continue
                written.append((target, page.url, page.title()))
        finally:
            browser.close()
    return written, errors


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        header = fh.read(24)
    return struct.unpack(">II", header[16:24])  # IHDR: szerokość, wysokość


def _shown(path: Path) -> str:
    path = path.resolve()
    return f"{path.relative_to(ROOT)}/" if path.is_relative_to(ROOT) else f"{path}/"


# ----------------------------------------------------------------------------------------------
# Wiersz poleceń
# ----------------------------------------------------------------------------------------------

def _default_app_python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zrzuty ekranu panelu z odizolowanej instancji (świeża SQLite, próbki demo, Playwright).")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="katalog wyjściowy; pliki są nadpisywane (domyślnie app/static/screenshots)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"wolny port instancji na {HOST} (domyślnie {DEFAULT_PORT}; nigdy {LIVE_DEMO_PORT})")
    parser.add_argument("--only", nargs="+", metavar="NAZWA", help="tylko wybrane zrzuty, np. 08-pomoc 11-api-docs")
    parser.add_argument("--app-python", default=_default_app_python(),
                        help="interpreter z zależnościami aplikacji dla serwera "
                             "(domyślnie .venv/bin/python repozytorium, a bez niego bieżący)")
    parser.add_argument("--list", action="store_true", help="wypisz strony i zakończ (bez Playwright)")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)  # tryb podprocesu serwera
    parser.add_argument("--workdir", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve and not args.workdir:
        parser.error("--serve wymaga --workdir")
    return args


def select_shots(only: list[str] | None) -> list[Shot]:
    if not only:
        return list(PAGES)
    wanted = [name.removesuffix(".png") for name in only]
    unknown = sorted(set(wanted) - {shot.name for shot in PAGES})
    if unknown:
        raise ToolError(f"Nieznane zrzuty: {', '.join(unknown)} (lista: --list).")
    return [shot for shot in PAGES if shot.name in wanted]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.serve:
        serve(args.port, Path(args.workdir))
        return 0
    if args.list:
        window = f"okno {VIEWPORT['width']}×{VIEWPORT['height']}"
        for shot in PAGES:
            print(f"{shot.name:22} {shot.path:36} {'cała strona' if shot.full_page else window}")
        return 0
    try:
        shots = select_shots(args.only)
        if args.port == LIVE_DEMO_PORT:
            raise ToolError(f"Port {LIVE_DEMO_PORT} to żywe demo — zrzuty wyłącznie z odizolowanej instancji "
                            "(wybierz inny --port).")
        if not port_free(args.port):
            raise ToolError(f"Port {args.port} na {HOST} jest zajęty — wybierz wolny (--port).")
        playwright = load_playwright()
        if playwright is None:
            raise ToolError(INSTALL_HINT)
        out = Path(args.out)
        with tempfile.TemporaryDirectory(prefix="xml-parser-zrzuty-") as tmp:
            password = secrets.token_urlsafe(18)
            with running_server(args.app_python, args.port, Path(tmp), password) as base:
                written, errors = take_screenshots(playwright, base, shots, out, password)
    except ToolError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"Zapisano {len(written)} z {len(shots)} zrzutów w {_shown(out)}:")
    for path, url, title in written:
        width, height = png_size(path)
        print(f"  {path.name:26} {width}×{height:<5} {url}  „{title}”")
    print("Błędy konsoli przeglądarki:" if errors else "Błędy konsoli przeglądarki: brak")
    for error in errors:
        print(f"  {error}")
    return 1 if errors or len(written) != len(shots) else 0


if __name__ == "__main__":
    raise SystemExit(main())
