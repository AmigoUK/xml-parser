"""Czas w REST API: parsowanie parametrów (`parse_api_datetime`) i format odpowiedzi (`format_api_datetime`)."""
import io
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.api.timeutil import format_api_datetime, parse_api_datetime
from app.extensions import db
from app.models import Document
from tests.conftest import sample_bytes

KEY = {"X-API-Key": "xp_test_demo_key"}


@pytest.fixture
def local_time_plus_2h():
    """Strefa lokalna procesu = UTC+2 (zapis POSIX: `WAW-2` to 2 h na wschód od UTC, bez zmiany czasu).

    Ujawnia niejawne traktowanie czasu bez strefy jako lokalnego (`astimezone()` na naiwnym datetime):
    maszyna deweloperska bywa w UTC i taki błąd wychodzi dopiero na serwerze w innej strefie.
    """
    old = os.environ.get("TZ")
    os.environ["TZ"] = "WAW-2"
    time.tzset()
    try:
        # kontrola fixture'a: naiwne 06:00 „lokalne” to 04:00 UTC — inaczej test przechodziłby na pusto
        assert datetime(2026, 10, 11, 6).astimezone(timezone.utc).hour == 4
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


# --- parse_api_datetime ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    pytest.param("2026-10-11", datetime(2026, 10, 11), id="sama-data-polnoc-utc"),
    pytest.param("2026-10-11T06:00:00", datetime(2026, 10, 11, 6, 0, 0), id="bez-strefy-to-utc"),
    pytest.param("2026-10-11T06:00:00Z", datetime(2026, 10, 11, 6, 0, 0), id="Z"),
    pytest.param("2026-10-11T08:00:00+02:00", datetime(2026, 10, 11, 6, 0, 0), id="plus-2h"),
    pytest.param("2026-10-11T01:00:00-05:00", datetime(2026, 10, 11, 6, 0, 0), id="minus-5h"),
    pytest.param("2026-10-11T01:30:00+02:00", datetime(2026, 10, 10, 23, 30, 0), id="przeliczenie-cofa-date"),
    pytest.param("2026-10-11T06:00:00.312308Z", datetime(2026, 10, 11, 6, 0, 0, 312308), id="mikrosekundy-z-Z"),
    pytest.param("2026-10-11T08:00:00.312308+02:00", datetime(2026, 10, 11, 6, 0, 0, 312308),
                 id="mikrosekundy-ze-strefa"),
])
def test_parse_returns_naive_utc(text, expected):
    result = parse_api_datetime(text)
    assert result == expected
    assert result.tzinfo is None  # naiwny, jak Document.created_at / updated_at (app.models.utcnow)


@pytest.mark.parametrize("bad", [
    pytest.param("abc", id="smieci"),
    pytest.param("", id="pusty"),
    pytest.param("   ", id="same-spacje"),
    pytest.param("2026-13-45", id="miesiac-13"),
    pytest.param("2026-10-11T24:00:00", id="godzina-24"),
    pytest.param("2026-10-11T08:00:00 02:00", id="plus-zdekodowany-jako-spacja"),
    pytest.param("0001-01-01T00:00:00+05:00", id="po-przeliczeniu-przed-rokiem-1"),
    pytest.param("9999-12-31T23:59:59-05:00", id="po-przeliczeniu-po-roku-9999"),
    pytest.param(None, id="None"),
    pytest.param(123, id="liczba"),
    pytest.param(b"2026-10-11", id="bytes"),
])
def test_parse_rejects_bad_input_with_value_error(bad):
    """Zawsze ValueError: wywołujący łapią tylko ten wyjątek, a TypeError/OverflowError dałyby 500."""
    with pytest.raises(ValueError):
        parse_api_datetime(bad)


# --- format_api_datetime --------------------------------------------------------------------------------------

def test_format_none_is_none():
    assert format_api_datetime(None) is None


def test_format_naive_keeps_microseconds_and_adds_z():
    assert format_api_datetime(datetime(2026, 10, 11, 6, 4, 38, 312308)) == "2026-10-11T06:04:38.312308Z"


def test_format_always_six_digits_of_microseconds():
    assert format_api_datetime(datetime(2026, 10, 11, 6, 0, 0)) == "2026-10-11T06:00:00.000000Z"


def test_format_aware_is_converted_to_utc():
    plus_2h = timezone(timedelta(hours=2))
    assert format_api_datetime(datetime(2026, 10, 11, 8, 0, tzinfo=plus_2h)) == "2026-10-11T06:00:00.000000Z"


def test_format_aware_utc_has_single_z_suffix():
    """Bez zdjęcia strefy isoformat() dałby `+00:00` obok `Z`."""
    assert format_api_datetime(datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)) == "2026-10-11T06:00:00.000000Z"


@pytest.mark.parametrize("dt", [
    datetime(2026, 10, 11, 6, 4, 38, 312308),
    datetime(2026, 10, 11, 6, 0, 0),
    datetime(2026, 1, 1, 0, 0, 0, 1),
])
def test_round_trip(dt):
    assert parse_api_datetime(format_api_datetime(dt)) == dt


def test_naive_time_is_utc_regardless_of_process_timezone(local_time_plus_2h):
    """Czas bez strefy to UTC (jak w bazie), a nie czas lokalny serwera — przy parsowaniu i formatowaniu."""
    assert parse_api_datetime("2026-10-11T06:00:00") == datetime(2026, 10, 11, 6, 0, 0)
    assert parse_api_datetime("2026-10-11") == datetime(2026, 10, 11)
    assert format_api_datetime(datetime(2026, 10, 11, 6, 0, 0)) == "2026-10-11T06:00:00.000000Z"


# --- GET /api/v1/documents?since= -----------------------------------------------------------------------------

@pytest.fixture
def docs(seeded, client):
    """Trzy różne dokumenty klucza demo z czasem utworzenia ustawionym wprost w bazie (naiwny UTC).

    Zwraca id: `before` (05:59:59), `boundary` (dokładnie 06:00:00 — `since` jest włącznie), `after` (07:00:00).
    """
    ids = []
    for name in ("epsilon.json", "delta.csv", "alfa-1.xml"):
        r = client.post("/api/v1/documents", headers=KEY, content_type="multipart/form-data",
                        data={"file": (io.BytesIO(sample_bytes(name)), name)})
        assert r.status_code == 201
        ids.append(r.get_json()["id"])
    times = (datetime(2026, 10, 11, 5, 59, 59), datetime(2026, 10, 11, 6, 0, 0), datetime(2026, 10, 11, 7, 0, 0))
    for doc_id, created_at in zip(ids, times):
        db.session.get(Document, doc_id).created_at = created_at
    db.session.commit()
    return dict(zip(("before", "boundary", "after"), ids))


def _listed_ids(client, **params):
    # query_string koduje „+” jako %2B — gołe „+” w adresie serwer odczytałby jako spację
    r = client.get("/api/v1/documents", headers=KEY, query_string=params)
    assert r.status_code == 200
    return [d["id"] for d in r.get_json()["items"]]


@pytest.mark.parametrize("since, expected", [
    # 08:00+02:00 == 01:00-05:00 == 06:00Z, więc okno zaczyna się o 06:00 UTC
    # (kryterium planu: since=T+02:00 zwraca to samo co since=T-2h bez strefy)
    pytest.param("2026-10-11T08:00:00+02:00", ["after", "boundary"], id="plus-2h"),
    pytest.param("2026-10-11T01:00:00-05:00", ["after", "boundary"], id="minus-5h"),
    pytest.param("2026-10-11T06:00:00", ["after", "boundary"], id="bez-strefy"),
    pytest.param("2026-10-11T06:00:00Z", ["after", "boundary"], id="Z"),
    # naiwny = 08:00 UTC, czyli po ostatnim dokumencie: puste. W kontraście do plus-2h dowodzi, że przesunięcie
    # strefy jest uwzględniane, a nie pomijane (pominięte dałoby dla +02:00 też 08:00, czyli puste).
    pytest.param("2026-10-11T08:00:00", [], id="bez-strefy-08-utc-puste"),
    pytest.param("2026-10-11", ["after", "boundary", "before"], id="sama-data-polnoc-utc"),
])
def test_since_converts_zone_to_utc(docs, client, since, expected):
    # porównanie list (nie zbiorów) pilnuje też, że sortowanie malejąco po id zostało bez zmian
    assert _listed_ids(client, since=since) == [docs[k] for k in expected]


def test_since_combines_with_limit(docs, client):
    assert _listed_ids(client, since="2026-10-11T08:00:00+02:00", limit=1) == [docs["after"]]


@pytest.mark.parametrize("bad", [
    pytest.param("abc", id="smieci"),
    pytest.param("2026-13-45", id="miesiac-13"),
    pytest.param("0001-01-01T00:00:00+05:00", id="po-przeliczeniu-przed-rokiem-1"),
])
def test_since_bad_value_is_400(seeded, client, bad):
    r = client.get("/api/v1/documents", headers=KEY, query_string={"since": bad})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"


def test_since_unencoded_plus_is_rejected_not_shifted(docs, client):
    """Gołe „+” w adresie to po dekodowaniu spacja — ma być 400 (z podpowiedzią), a nie ciche przesunięcie okna."""
    r = client.get("/api/v1/documents?since=2026-10-11T08:00:00+02:00", headers=KEY)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"
