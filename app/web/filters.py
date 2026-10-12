"""Filtry Jinja panelu: czas lokalny (`dt`/`dts`), kwoty i ilości po polsku, rozmiar w MiB."""
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from zoneinfo import ZoneInfo

from flask import Flask, current_app
from markupsafe import Markup, escape

from .. import formatting
from ..engine.values import fmt_money, fmt_price, fmt_qty

log = logging.getLogger(__name__)
DASH = "—"
NBSP = "\xa0"


@lru_cache(maxsize=32)
def _zone(name: str) -> tuple[ZoneInfo, str]:
    """Strefa o podanej nazwie; nieznana → UTC z ostrzeżeniem (wynik w cache, więc ostrzeżenie raz)."""
    try:
        return ZoneInfo(name), name
    except Exception:  # ZoneInfoNotFoundError, ValueError (zła nazwa), OSError
        log.warning("Nieznana strefa DISPLAY_TZ %r — używam UTC", name)
        return ZoneInfo("UTC"), "UTC"


def _time_tag(value, fmt: str) -> Markup | str:
    if value is None:
        return DASH
    if value.tzinfo is None:  # utcnow() w modelach jest naiwne i oznacza UTC
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    zone, zone_name = _zone(str(current_app.config.get("DISPLAY_TZ") or "UTC"))
    iso = value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return Markup('<time datetime="{}" title="{}">{}</time>').format(
        iso, f"Czas lokalny {zone_name}", value.astimezone(zone).strftime(fmt))


def dt(value: datetime | None) -> Markup | str:
    """Data i godzina (DD.MM.RRRR GG:MM) w DISPLAY_TZ jako element <time>; None → „—”."""
    return _time_tag(value, "%d.%m.%Y %H:%M")


def dts(value: datetime | None) -> Markup | str:
    """Jak `dt`, z sekundami."""
    return _time_tag(value, "%d.%m.%Y %H:%M:%S")


def _decimal(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _group(plain: str) -> str:
    """„1234567.89” → „1 234 567,89” (twarda spacja jako separator tysięcy, przecinek dziesiętny)."""
    sign = "-" if plain.startswith("-") else ""
    whole, _, frac = plain.lstrip("-").partition(".")
    whole = f"{int(whole):,}".replace(",", NBSP)
    return sign + whole + ("," + frac if frac else "")


def money(value) -> str:
    """Kwota „1 234,56”; None → pusty tekst, wartość nienumeryczna bez zmian."""
    if value is None:
        return ""
    d = _decimal(value)
    return escape(value) if d is None else _group(fmt_money(d))


def price(value) -> str:
    """Cena jednostkowa „1 234,5678”: do 4 miejsc, co najmniej 2; None → pusty tekst, nienumeryczna bez zmian."""
    if value is None:
        return ""
    d = _decimal(value)
    return escape(value) if d is None else _group(fmt_price(d))


def qty(value) -> str:
    """Ilość do 4 miejsc po przecinku bez zer końcowych; None → pusty tekst, nienumeryczne bez zmian."""
    if value is None:
        return ""
    d = _decimal(value)
    if d is None:
        return escape(value)
    return _group(fmt_qty(d.quantize(Decimal("0.0001"))))


def register_filters(app: Flask) -> None:
    app.jinja_env.filters.update(dt=dt, dts=dts, money=money, price=price, qty=qty, mib=formatting.mib)
