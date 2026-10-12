"""Sekcja „Pomoc” — publiczna (bez logowania), bez sekretów; limity wstrzykiwane z konfiguracji i stałych."""
from __future__ import annotations

import re
import struct
from functools import cache, lru_cache
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request

from app.api.routes import LIST_DEFAULT_LIMIT, LIST_MAX_LIMIT
from app.engine.issues import MAX_LINE_NOS
from app.engine.transforms import MAX_INPUT, MAX_PATTERN, REGEX_TIMEOUT, REGISTRY, TRANSFORM_LABELS
from app.engine.values import MAX_FACTOR_INTEGER_DIGITS, MAX_INTEGER_DIGITS, MAX_NUMBER_TEXT
from app.formatting import MIB, mib
from app.help_content import FAQ, ISSUE_HELP, STATUS_HELP, TOPICS, TOPICS_BY_SLUG, TRANSFORM_HELP
from app.models import STATUS_LABELS
from app.services.catalog import MAX_IMPORT_BYTES, MAX_IMPORT_ROWS
from app.services.pipeline import FINGERPRINT_MIN
from app.web.documents import ISSUE_CARDS_LIMIT

bp = Blueprint("help", __name__, url_prefix="/pomoc")

# Przykłady integracji: prawdziwe pliki (sprawdzane składniowo w testach), adres instancji wstawiany w miejsce
# API_BASE_MARK. Odpowiedź przykładowa to rzeczywisty wynik API dla próbki demo alfa-2.xml (skrócony do 1 pozycji).
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "help_examples"
API_BASE_MARK = "__API_BASE__"
INTEGRATION_EXAMPLES = [  # (język bloku kodu, tytuł, plik)
    ("python", "Python (requests)", "integracja.py"),
    ("php", "PHP (cURL)", "integracja.php"),
    ("javascript", "JavaScript — Node.js 18+ (fetch, FormData, Blob)", "integracja.mjs"),
    ("bash", "Powłoka — curl i jq", "integracja.sh"),
]
SAMPLE_RESPONSE_FILE = "odpowiedz-zatwierdzona.json"

# Zrzuty ekranu w tematach Pomocy (makro help/_shot.html) — te same pliki, co w README.
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "static" / "screenshots"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

QUICK_START = [
    ("Zaloguj się", "Panel wymaga konta; tryb demo pokazuje e-mail konta na stronie „O demo”."),
    ("Wgraj fakturę", "„Wgraj fakturę” w menu (XML, JSON lub CSV) albo wyślij ją przez REST API."),
    ("Rozwiąż problemy od góry", "Faktura nowego dostawcy trafia do „Kolejki” — wybieraj podpowiedzi, "
                                 "zaczynając od rozpoznania dostawcy."),
    ("Zdecyduj, co zapamiętać", "„Zapamiętaj w szablonie” uczy system; „tylko ta faktura” dotyczy jednego "
                                "dokumentu."),
    ("Kolejne faktury przejdą same", "Następna faktura tego dostawcy zostanie zatwierdzona automatycznie, "
                                     "jeśli nie pojawi się nic nowego."),
]


def fmt_int(n: int) -> str:
    """Liczba ze spacją jako separatorem tysięcy (jak w komunikatach aplikacji)."""
    return f"{int(n):,}".replace(",", " ")


def fmt_bytes(n: int) -> str:
    """Rozmiar po polsku: pełne MB, ułamek MB z przecinkiem, KB albo B."""
    kib = 1024
    if n >= MIB and n % MIB == 0:
        return f"{mib(n)} MB"
    if n >= MIB:
        return f"{n / MIB:.1f} MB".replace(".", ",")
    if n >= kib:
        return f"{n // kib} KB"
    return f"{n} B"


def help_limits() -> dict:
    cfg = current_app.config
    lifetime = cfg.get("PERMANENT_SESSION_LIFETIME")
    hours = int(lifetime.total_seconds() // 3600) if hasattr(lifetime, "total_seconds") else int(lifetime) // 3600
    return {
        "max_document": fmt_bytes(int(cfg["MAX_DOCUMENT_BYTES"])),
        "max_tree_nodes": fmt_int(cfg["MAX_TREE_NODES"]),
        "max_lines": fmt_int(cfg["MAX_LINES"]),
        "max_import": fmt_bytes(MAX_IMPORT_BYTES),
        "max_import_rows": fmt_int(MAX_IMPORT_ROWS),
        "max_line_nos": MAX_LINE_NOS,
        "issue_cards": ISSUE_CARDS_LIMIT,
        "list_default": LIST_DEFAULT_LIMIT,
        "list_max": LIST_MAX_LIMIT,
        "max_pattern": MAX_PATTERN,
        "max_input": fmt_int(MAX_INPUT),
        "regex_timeout": str(REGEX_TIMEOUT).replace(".", ","),
        "max_number_text": MAX_NUMBER_TEXT,
        "max_integer_digits": MAX_INTEGER_DIGITS,
        "max_factor_digits": MAX_FACTOR_INTEGER_DIGITS,
        "fingerprint_pct": int(round(FINGERPRINT_MIN * 100)),
        "session_hours": hours,
        "login_max": cfg.get("LOGIN_MAX_ATTEMPTS"),
        "login_minutes": cfg.get("LOGIN_LOCKOUT_MINUTES"),
        "login_per_ip": cfg.get("LOGIN_MAX_ATTEMPTS_PER_IP"),
        "login_per_email": cfg.get("LOGIN_MAX_ATTEMPTS_PER_EMAIL"),
        "login_email_minutes": cfg.get("LOGIN_EMAIL_LOCKOUT_MINUTES"),
    }


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def fill(text: str, values: dict) -> str:
    """Podstawia {nazwa} znanymi limitami; inne nawiasy (np. {"decimal": ","}) zostają bez zmian."""
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def _transforms(limits: dict) -> list[dict]:
    out = []
    for name in REGISTRY:
        h = TRANSFORM_HELP.get(name, {})
        out.append({"name": name, "label": TRANSFORM_LABELS.get(name, ""), **h,
                    "note": fill(h.get("note", ""), limits)})
    return out


@cache
def _example_text(name: str) -> str:
    return (EXAMPLES_DIR / name).read_text(encoding="utf-8")


def integration_examples(api_base: str) -> list[dict]:
    return [{"lang": lang, "title": title, "file": name,
             "code": _example_text(name).replace(API_BASE_MARK, api_base).rstrip("\n")}
            for lang, title, name in INTEGRATION_EXAMPLES]


# Globalna funkcja szablonów, a nie zmienna z context processora: makro help/_shot.html jest importowane bez
# „with context”, a taki import widzi tylko globale Jinja.
@bp.app_template_global()
@lru_cache(maxsize=64)
def screenshot_size(file: str) -> tuple[int, int] | None:
    """(szerokość, wysokość) pliku PNG z app/static/screenshots/ odczytane z nagłówka IHDR — atrybuty width/height
    obrazka rezerwują miejsce przed doczytaniem (loading="lazy") i układ nie skacze. None, gdy pliku nie ma
    albo nie jest PNG (strona ma się wyrenderować bez wymiarów, nie wywrócić)."""
    try:
        header = (SCREENSHOTS_DIR / file).read_bytes()[:24]
    except OSError:
        return None
    if len(header) < 24 or not header.startswith(PNG_SIGNATURE) or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def _neighbours(slug: str):
    idx = next(i for i, t in enumerate(TOPICS) if t["slug"] == slug)
    prev = TOPICS[idx - 1] if idx > 0 else None
    nxt = TOPICS[idx + 1] if idx + 1 < len(TOPICS) else None
    return prev, nxt


@bp.app_context_processor
def inject_help_codes():
    # kody z rejestru — _issues.html dodaje przy nich link „?” do tabeli problemów
    return {"help_issue_codes": ISSUE_HELP}


@bp.get("")
def index():
    return render_template("help/index.html", topics=TOPICS, quick_start=QUICK_START, limits=help_limits())


@bp.get("/<slug>")
def topic(slug):
    t = TOPICS_BY_SLUG.get(slug)
    if t is None:
        abort(404)
    limits = help_limits()
    prev, nxt = _neighbours(slug)
    api_base = request.host_url.rstrip("/")
    extra = {}
    if slug == "integracja":
        extra = {"examples": integration_examples(api_base),
                 "sample_response": _example_text(SAMPLE_RESPONSE_FILE).rstrip("\n")}
    return render_template(
        f"help/{slug}.html", topic=t, topics=TOPICS, prev=prev, next=nxt, limits=limits,
        issues=ISSUE_HELP, statuses=[(k, STATUS_LABELS[k], STATUS_HELP.get(k, "")) for k in STATUS_LABELS],
        transforms=_transforms(limits), faq=[{**f, "a": fill(f["a"], limits)} for f in FAQ],
        api_base=api_base, **extra)
