"""Czas w REST API v1: jedno miejsce na parsowanie parametrów i formatowanie odpowiedzi.

W bazie czas jest naiwnym UTC (`app.models.utcnow`). W API czas ze strefą jest przeliczany na UTC, czas bez strefy
oznacza UTC, a odpowiedzi zawsze niosą jawne UTC (`…Z`). Czysty moduł pomocniczy — bez modeli i bez bazy.
"""
from datetime import datetime, timezone

DATE_TIME_SEPARATORS = "Tt "  # po dacie YYYY-MM-DD: T (także t) albo spacja, a za nim czas


def _to_naive_utc(dt: datetime) -> datetime:
    # Naiwnego czasu nie przeliczamy: astimezone() uznałoby go za czas lokalny serwera, a naiwny znaczy tu UTC.
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_api_datetime(text: str) -> datetime:
    """Czas z parametru API → naiwny datetime w UTC (tak jak zapisany w bazie).

    Przyjmuje: samą datę `YYYY-MM-DD` (= północ UTC), ISO 8601 bez strefy (= UTC),
    ISO 8601 ze strefą (`+02:00`, `-05:00`, `Z`) — przeliczane na UTC. Datę od czasu oddziela `T` (także `t`)
    albo spacja.

    ValueError dla:
    - błędnego formatu, pustego tekstu i nie-stringa;
    - daty `YYYY-MM-DD`, po której stoi inny znak niż `T`, `t` lub spacja — w tym daty ze strefą bez godziny
      (`2026-10-11+02:00`, `2026-10-11-05:00`, forma xs:date z UBL): `datetime.fromisoformat` przyjmuje dowolny
      znak jako separator daty i czasu, więc przeczytałby strefę jako godzinę (02:00 UTC zamiast północy w +02:00);
    - separatora spacją bez pełnego czasu `HH:MM:SS` (`2026-10-11 02:00` — tak wygląda `2026-10-11+02:00`
      wklejone do adresu URL z surowym `+`, który po dekodowaniu jest spacją);
    - czasu, który po przeliczeniu na UTC wypada poza zakres dat (przed rokiem 1 albo po roku 9999).

    Pozostały zakres akceptowanych zapisów (np. format podstawowy `20261011T080000+0200`) wyznacza
    `datetime.fromisoformat` (Python 3.11+).
    """
    if not isinstance(text, str):
        raise ValueError(f"Czas musi być tekstem ISO 8601, a nie {type(text).__name__}.")
    if len(text) > 10 and text[4] == "-":  # format rozszerzony: po dacie YYYY-MM-DD coś jeszcze stoi
        if text[10] not in DATE_TIME_SEPARATORS:
            raise ValueError("Po dacie musi stać „T” albo spacja i czas — sama data nie może mieć strefy.")
        if text[10] == " " and len(text) < 19:  # 19 = len("2026-10-11 06:00:00")
            raise ValueError("Po spacji musi stać pełny czas HH:MM:SS (surowy „+” w adresie URL to spacja).")
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
