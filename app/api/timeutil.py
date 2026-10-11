"""Czas w REST API v1: jedno miejsce na parsowanie parametrów i formatowanie odpowiedzi.

W bazie czas jest naiwnym UTC (`app.models.utcnow`). W API czas ze strefą jest przeliczany na UTC, czas bez strefy
oznacza UTC, a odpowiedzi zawsze niosą jawne UTC (`…Z`). Czysty moduł pomocniczy — bez modeli i bez bazy.
"""
from datetime import datetime, timezone


def _to_naive_utc(dt: datetime) -> datetime:
    # Naiwnego czasu nie przeliczamy: astimezone() uznałoby go za czas lokalny serwera, a naiwny znaczy tu UTC.
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_api_datetime(text: str) -> datetime:
    """Czas z parametru API → naiwny datetime w UTC (tak jak zapisany w bazie).

    Przyjmuje: samą datę `YYYY-MM-DD` (= północ UTC), ISO 8601 bez strefy (= UTC),
    ISO 8601 ze strefą (`+02:00`, `-05:00`, `Z`) — przeliczane na UTC.
    Błędny format, pusty tekst lub nie-string → ValueError.

    Zakres akceptowanych zapisów wyznacza `datetime.fromisoformat` (Python 3.11+).
    """
    if not isinstance(text, str):
        raise ValueError(f"Czas musi być tekstem ISO 8601, a nie {type(text).__name__}.")
    parsed = datetime.fromisoformat(text)  # ValueError: zły format, pusty tekst, data spoza kalendarza
    try:
        return _to_naive_utc(parsed)
    except OverflowError as exc:  # np. 0001-01-01T00:00:00+05:00 wypada po przeliczeniu na UTC przed rokiem 1
        raise ValueError("Czas po przeliczeniu na UTC wykracza poza obsługiwany zakres dat.") from exc


def format_api_datetime(dt: datetime | None) -> str | None:
    """Naiwny UTC z bazy → ISO 8601 z jawnym UTC: `2026-10-11T06:04:38.312308Z`.

    Zawsze 6 cyfr mikrosekund (`isoformat(timespec="microseconds")`), zawsze `Z`.
    Czas ze strefą jest przeliczany na UTC. `None` → `None`.
    """
    if dt is None:
        return None
    return _to_naive_utc(dt).isoformat(timespec="microseconds") + "Z"
