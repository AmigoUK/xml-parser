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
    pytest.param("2026-10-11 06:00:00", datetime(2026, 10, 11, 6, 0, 0), id="separator-spacja"),
    pytest.param("2026-10-11 08:00:00+02:00", datetime(2026, 10, 11, 6, 0, 0), id="separator-spacja-ze-strefa"),
    pytest.param("2026-10-11t06:00:00", datetime(2026, 10, 11, 6, 0, 0), id="separator-male-t"),
    pytest.param("2026-10-11T06:00", datetime(2026, 10, 11, 6, 0, 0), id="T-bez-sekund"),
    pytest.param("20261011T080000+0200", datetime(2026, 10, 11, 6, 0, 0), id="format-podstawowy-z-T"),
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
    # data ze strefą bez godziny (forma xs:date z UBL): fromisoformat przyjmuje dowolny znak jako separator daty
    # i czasu, więc przeczytałby strefę jako godzinę — 02:00 / 05:00 UTC zamiast północy w tej strefie
    pytest.param("2026-10-11+02:00", id="data-ze-strefa-plus"),
    pytest.param("2026-10-11-05:00", id="data-ze-strefa-minus"),
    pytest.param("2026-10-11+0200", id="data-ze-strefa-bez-dwukropka"),
    pytest.param("2026-10-11Z", id="data-z-Z"),
    pytest.param("2026-10-11X06:00:00", id="separator-spoza-T-t-spacji"),
    # surowy „+” w adresie URL to po dekodowaniu spacja: 2026-10-11+02:00 → „2026-10-11 02:00”
    pytest.param("2026-10-11 02:00", id="data-ze-strefa-plus-zdekodowany-jako-spacja"),
    pytest.param("2026-10-11 0200", id="spacja-bez-pelnego-czasu"),
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


@pytest.mark.parametrize("text", [
    pytest.param("20261011+0200", id="podstawowy-data-ze-strefa-bez-godziny"),
    pytest.param("20261011 0200", id="podstawowy-spacja-bez-pelnego-czasu"),
])
def test_basic_format_date_with_zone_or_short_time_is_rejected(text):
    """Format podstawowy ISO (bez myślników) podlega tym samym zasadom co rozszerzony: po dacie T albo spacja
    i pełny czas — inaczej fromisoformat przeczytałby strefę `+0200` jako godzinę 02:00 UTC."""
    with pytest.raises(ValueError):
        parse_api_datetime(text)


def test_basic_format_with_time_and_zone_still_accepted():
    assert parse_api_datetime("20261011T080000+0200") == datetime(2026, 10, 11, 6, 0, 0)
    assert parse_api_datetime("20261011") == datetime(2026, 10, 11, 0, 0, 0)


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
    pytest.param("2026-10-11T08:00:00+02:00", ["after", "boundary"], id="strefa-plus-2h"),
    pytest.param("2026-10-11T01:00:00-05:00", ["after", "boundary"], id="strefa-minus-5h"),
    pytest.param("2026-10-11T06:00:00", ["after", "boundary"], id="bez-strefy"),
    pytest.param("2026-10-11T06:00:00Z", ["after", "boundary"], id="strefa-z"),
    # naiwny = 08:00 UTC, czyli po ostatnim dokumencie: puste. W kontraście do plus-2h dowodzi, że przesunięcie
    # strefy jest uwzględniane, a nie pomijane (pominięte dałoby dla +02:00 też 08:00, czyli puste).
    pytest.param("2026-10-11T08:00:00", [], id="bez-strefy-08-utc-puste"),
    pytest.param("2026-10-11", ["after", "boundary", "before"], id="sama-data-polnoc-utc"),
])
def test_since_converts_zone_to_utc(docs, client, since, expected):
    # listy, nie zbiory: porównanie sprawdza też kolejność — jak w trybie zwykłym listy, czyli malejąco po id
    # (order_by(Document.id.desc()) w list_documents; w fixture `docs` id rosną razem z created_at)
    assert _listed_ids(client, since=since) == [docs[k] for k in expected]


def test_since_basic_format_date_with_zone_is_400(seeded, client):
    """`20261011+0200` (format podstawowy, poprawnie zakodowane %2B) to data ze strefą bez godziny — 400, a nie okno
    od 02:00 UTC."""
    r = client.get("/api/v1/documents?since=20261011%2B0200", headers=KEY)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"


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


@pytest.mark.parametrize("query", [
    pytest.param("since=2026-10-11T08:00:00+02:00", id="czas"),
    pytest.param("since=2026-10-11+02:00", id="sama-data-ze-strefa"),
])
def test_since_unencoded_plus_is_rejected_not_shifted(docs, client, query):
    """Gołe „+” w adresie to po dekodowaniu spacja — ma być 400 (z podpowiedzią), a nie ciche przesunięcie okna."""
    r = client.get(f"/api/v1/documents?{query}", headers=KEY)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"


def test_since_date_with_zone_without_time_is_400_not_shifted(docs, client):
    """`2026-10-11+02:00` (poprawnie zakodowane %2B) to data ze strefą, a nie 02:00 UTC — 400 zamiast okna
    przesuniętego o 2 godziny. Komunikat podaje pełną postać — sama wskazówka o %2B nic by tu nie pomogła."""
    r = client.get("/api/v1/documents?since=2026-10-11%2B02:00", headers=KEY)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_request"
    assert "Data ze strefą musi zawierać godzinę: 2026-10-11T00:00:00+02:00" in r.get_json()["error"]["message"]
