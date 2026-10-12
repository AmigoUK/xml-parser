"""Stronicowanie list panelu: kursor po `id` (dokumenty, kolejka, historia, szablony) albo numer strony (CRUD).

Kursor panelu to zwykłe id z `?before=`/`?after=` (nie nieprzezroczysty kursor API z `app/api/cursor.py`);
zła wartość parametru (tekst, zero, liczba poza zakresem kolumny) oznacza pierwszą stronę, nigdy 500.
"""
from __future__ import annotations

from urllib.parse import urlencode

from flask import request, url_for

from app.ids import parse_id

SEARCH_MAX = 100  # maks. długość frazy `?q=` — dłuższa jest obcinana


def cursor_arg(name: str) -> int | None:
    """Id z parametru zapytania `name` albo None (pierwsza strona)."""
    return parse_id(request.args.get(name))


def search_arg(name: str = "q") -> str:
    """Fraza wyszukiwania z parametru zapytania — przycięta, maks. SEARCH_MAX znaków."""
    return (request.args.get(name) or "").strip()[:SEARCH_MAX]


def like_pattern(text: str) -> str:
    """Wzorzec `%text%` dla ilike(…, escape="\\") — %, _ i \\ z frazy traktowane dosłownie."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def page_by_id(query, id_col, per_page: int, *, before: int | None = None, after: int | None = None):
    """Strona wyników po kluczu `id_col`; zwraca (wiersze, kursor następnej strony albo None).

    Bez `after` — malejąco (najnowsze najpierw), `before` = id ostatniego wiersza poprzedniej strony.
    Z `after` — rosnąco (FIFO), `after=0` oznacza pierwszą stronę od najstarszych.
    Pobiera `per_page + 1` wierszy: kursor jest tylko wtedy, gdy naprawdę istnieje dalsza strona.
    """
    if after is not None:
        query = query.filter(id_col > after).order_by(id_col.asc())
    else:
        if before is not None:
            query = query.filter(id_col < before)
        query = query.order_by(id_col.desc())
    rows = query.limit(per_page + 1).all()
    if len(rows) <= per_page:
        return rows, None
    rows = rows[:per_page]
    return rows, getattr(rows[-1], id_col.key)


def page_by_number(query, per_page: int, page: int | None):
    """Strona numerowana (offset) z zachowaniem porządku zapytania; zwraca (wiersze, strona, stron, razem).

    Brak/zły numer = strona 1, numer za ostatnią stroną = ostatnia strona.
    """
    total = query.order_by(None).count()
    pages = max(1, -(-total // per_page))
    page = min(max(page or 1, 1), pages)
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return rows, page, pages, total


def _url(**overrides) -> str:
    """Adres bieżącego widoku z parametrami zapytania zmienionymi przez `overrides` (None = usuń).

    Query string budujemy sami (urlencode), a do url_for idą tylko view_args: parametry zaczynające się od `_`
    (zastrzeżone w url_for: _anchor, _external, _scheme, _method) i nazwy kolidujące z view_args są pomijane —
    złe wejście nie może dać 500 ani linku absolutnego z nagłówka Host.
    """
    view_args = request.view_args or {}
    pairs = [(k, v) for k, v in request.args.items(multi=True)
             if not k.startswith("_") and k not in view_args and k not in overrides]
    pairs += [(k, v) for k, v in overrides.items() if v is not None]
    base = url_for(request.endpoint, **view_args)
    return f"{base}?{urlencode(pairs)}" if pairs else base


def next_url(param: str, value) -> str:
    """Adres bieżącego widoku z `param=value`, z zachowaniem pozostałych parametrów (filtry, `q`)."""
    return _url(**{param: value})


def first_url(param: str) -> str:
    """Adres bieżącego widoku bez parametru `param` (pierwsza strona), z zachowaniem filtrów."""
    return _url(**{param: None})


def page_context(rows: list, cursor: int | None, param: str) -> dict:
    """Wspólne klucze stronicowania kursorem: `shown`, `next_url` (None na ostatniej stronie) i `first_url`
    (None na pierwszej stronie)."""
    return {"shown": len(rows),
            "next_url": next_url(param, cursor) if cursor else None,
            "first_url": first_url(param) if cursor_arg(param) else None}
