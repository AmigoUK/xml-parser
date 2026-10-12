"""Stronicowanie list panelu: kursor po `id` (dokumenty, kolejka, historia, szablony) albo numer strony (CRUD).

Kursor panelu to zwykłe id z `?before=`/`?after=` (nie nieprzezroczysty kursor API z `app/api/cursor.py`);
zła wartość parametru (tekst, zero, liczba poza zakresem kolumny) oznacza pierwszą stronę, nigdy 500.
"""
from __future__ import annotations

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
    args = request.args.to_dict(flat=False)
    for key, value in overrides.items():
        args.pop(key, None)
        if value is not None:
            args[key] = value
    return url_for(request.endpoint, **(request.view_args or {}), **args)


def next_url(param: str, value) -> str:
    """Adres bieżącego widoku z `param=value`, z zachowaniem pozostałych parametrów (filtry, `q`)."""
    return _url(**{param: value})


def first_url(param: str) -> str:
    """Adres bieżącego widoku bez parametru `param` (pierwsza strona), z zachowaniem filtrów."""
    return _url(**{param: None})
