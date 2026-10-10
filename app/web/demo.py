from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.services.audit import audit
from app.services.pipeline import ingest
from app.services.seed import reset_demo

bp = Blueprint("demo", __name__, url_prefix="/demo")
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "demo" / "samples"

DEMO_SAMPLES = [
    {"file": "alfa-1.xml", "title": "Hurtownia Alfa — pierwsza faktura", "format": "XML (własny, PL)",
     "shows": "nowy dostawca, brak waluty, jednostka „pcs”, EAN z prefiksem AI 01, partia i data z kodu GS1-128"},
    {"file": "alfa-2.xml", "title": "Hurtownia Alfa — kolejna faktura", "format": "XML (własny, PL)",
     "shows": "po nauczeniu na pierwszej fakturze przechodzi automatycznie"},
    {"file": "beta-ksef.xml", "title": "Młyn Beta", "format": "KSeF FA(3)-podobny",
     "shows": "jednostka „worek” i przelicznik na kg odczytany z nazwy towaru"},
    {"file": "gamma-ubl.xml", "title": "Gamma Aromen", "format": "UBL 2.1",
     "shows": "kody jednostek UN/ECE (C62, H87) w atrybucie unitCode"},
    {"file": "delta.csv", "title": "Opakowania Delta", "format": "CSV",
     "shows": "przecinek dziesiętny, data DD.MM.RRRR, „kart.” → szt (×12)"},
    {"file": "epsilon.json", "title": "Epsilon Dairy", "format": "JSON",
     "shows": "jednostka „EA”, towary dopasowane po GTIN"},
]
_ALLOWED = {s["file"] for s in DEMO_SAMPLES}


@bp.before_request
def only_in_demo_mode():
    if not current_app.config.get("DEMO_MODE"):
        abort(404)


@bp.get("")
def index():
    # hasła admina nie pokazujemy nigdy; klucz API demo tylko zalogowanym (K-1)
    demo_key = current_app.config.get("DEMO_API_KEY") if current_user.is_authenticated else None
    return render_template("demo.html", samples=DEMO_SAMPLES, api_base=request.host_url.rstrip("/"),
                           demo_key=demo_key, admin_email=current_app.config.get("ADMIN_EMAIL"))


@bp.post("/wczytaj/<path:name>")
@login_required
def load_sample(name):
    if name not in _ALLOWED:
        abort(404)
    doc = ingest((SAMPLES_DIR / name).read_bytes(), name, source="demo")
    return redirect(url_for("docs.detail", doc_id=doc.id))


@bp.post("/reset")
@login_required
def reset():
    if current_user.role != "admin":
        abort(403)
    try:
        reset_demo()
    except RuntimeError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("demo.index"))
    audit("reset", "demo", None, {})
    db.session.commit()
    flash("Dane demo wyczyszczone — kartoteka towarów i jednostki przywrócone.", "success")
    return redirect(url_for("demo.index"))
