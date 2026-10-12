"""Poprawki niezawodności z audytu 2026-10-11 (znaleziska średnie): jawne importy blueprintów, podpowiedź
przelicznika przy liczbie poza zakresem w nazwie towaru, zapis przelicznika na liście bez notacji wykładniczej."""
import importlib
import sys
from decimal import Decimal

import pytest

from app.engine.suggest import conversion_guess

# --- app/web/__init__.py: brak blueprintu to błąd startu, nie cicha degradacja ---

def test_web_package_registers_blueprints_without_try_except():
    src = (importlib.resources.files("app.web") / "__init__.py").read_text(encoding="utf-8")
    assert "ModuleNotFoundError" not in src and "__import__" not in src
    for name in ("catalog", "templates_views", "apikeys", "history", "demo", "help"):
        assert f"from .{name} import bp as {name}_bp" in src, name


def test_all_panel_blueprints_registered(app):
    expected = {"auth", "docs", "catalog", "templates_views", "apikeys", "history", "demo", "help", "api"}
    assert expected <= set(app.blueprints)


def test_broken_blueprint_module_breaks_app_start(monkeypatch, tmp_path):
    """ModuleNotFoundError przy imporcie modułu panelu (brak zależności, literówka) ma wywrócić start aplikacji —
    sys.modules[nazwa] = None to standardowy sposób wymuszenia tego błędu przy imporcie."""
    from app import create_app
    monkeypatch.setitem(sys.modules, "app.web.history", None)
    with pytest.raises(ModuleNotFoundError):
        create_app({"TESTING": True, "SECRET_KEY": "t", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                    "STORAGE_DIR": str(tmp_path / "s"), "WTF_CSRF_ENABLED": False})


# --- suggest.conversion_guess: liczba poza zakresem w nazwie towaru nie przerywa podpowiedzi ---

@pytest.mark.parametrize("name", ["Worek 1234567890123456789 kg", "Worek " + "9" * 150 + " kg"])
def test_conversion_guess_ignores_out_of_range_quantity(name):
    g = conversion_guess(name, "worek")
    assert g == {"kind": "conversion", "from_unit": "worek", "to_unit": "szt", "factor": None, "confidence": 0.3}


def test_conversion_guess_still_reads_normal_quantity():
    assert conversion_guess("Mąka 25 kg", "worek")["factor"] == "25"


# --- lista przeliczników: 10 i 100 bez notacji wykładniczej ---

def test_conversion_list_shows_plain_factor(auth_client, app):
    from app.extensions import db
    from app.models import Unit, UnitConversion
    karton, worek = (Unit.query.filter_by(code=c).first() for c in ("karton", "worek"))  # z seeda, niebazowe
    szt = Unit.query.filter_by(code="szt").first()
    db.session.add(UnitConversion(from_unit_id=karton.id, to_unit_id=szt.id, factor=Decimal("10.000000")))
    db.session.add(UnitConversion(from_unit_id=worek.id, to_unit_id=szt.id, factor=Decimal("100")))
    db.session.commit()
    html = auth_client.get("/przeliczniki").get_data(as_text=True)
    assert "1 karton = 10 szt" in html and "1 worek = 100 szt" in html
    assert "1E+1" not in html and "1E+2" not in html
