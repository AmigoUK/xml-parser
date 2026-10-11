"""Tryb synchronizacji `GET /api/v1/documents` (`updated_since` / `cursor`): keyset po `(updated_at, id)` rosnąco,
`next_cursor` = pozycja ostatniego zwróconego dokumentu, dostawa „co najmniej raz”. Kursor: `app/api/cursor.py`.

Gdy liczy się tylko czas zmiany i liczba dokumentów, dokumenty są wstawiane wprost do bazy (bez `ingest` — 1 203
plików byłoby zbyt wolne). Dane fikcyjne. Test oznaczony `needs_mariadb` działa na prawdziwej, pustej bazie MariaDB
(`TEST_MARIADB_URL`); bez niej jest pomijany."""
import base64
import re
from datetime import datetime, timedelta

import pytest

from app.api.cursor import decode_cursor, encode_cursor
from app.api.timeutil import format_api_datetime
from app.extensions import db
from app.models import Document, utcnow
from app.services.apikeys import create_key, verify_key
from app.services.pipeline import touch
from tests.conftest import sample_bytes
from tests.test_learning import resolve_with_top_suggestions
from tests.test_migrations import mariadb_url, needs_mariadb  # noqa: F401 (fixture)

KEY = {"X-API-Key": "xp_test_demo_key"}
BASE = datetime(2026, 1, 1, 6, 0, 0)  # wcześniej niż „teraz” — touch() zawsze przesuwa dokument na koniec
SINCE_BASE = format_api_datetime(BASE)  # updated_since obejmujące wszystkie dokumenty wstawione od BASE
BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


@pytest.fixture
def demo_key(seeded):
    """Klucz demo jako obiekt `ApiKey` — do wstawiania jego dokumentów wprost do bazy."""
    return verify_key("xp_test_demo_key")


def _add_docs(key, times) -> list[int]:
    """Zatwierdzone dokumenty klucza `key` z podanymi `updated_at`, wprost w bazie. Zwraca id w kolejności `times`."""
    docs = [Document(source="api", filename=f"d{i}.xml", sha256=f"{i:064x}", status="approved", api_key_id=key.id,
                     issues=[], overrides={}, created_at=BASE, updated_at=at) for i, at in enumerate(times)]
    db.session.add_all(docs)
    db.session.flush()  # id już nadane; po commit odczyt każdego id byłby osobnym zapytaniem
    ids = [d.id for d in docs]
    db.session.commit()
    return ids


def _bulk(key, count, step=timedelta(microseconds=1)) -> list[int]:
    """`count` dokumentów z `updated_at` = BASE + i·step (domyślnie co mikrosekundę: kolejność czasu = kolejność id)."""
    return _add_docs(key, [BASE + i * step for i in range(count)])


def _page(client, headers=KEY, **params) -> dict:
    r = client.get("/api/v1/documents", headers=headers, query_string=params)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _pages(client, headers=KEY, cursor=None, max_pages=10, **params) -> list[dict]:
    """Kolejne strony jak u klienta: te same parametry + `cursor` z poprzedniej odpowiedzi, aż `next_cursor` = null."""
    bodies = []
    while len(bodies) < max_pages:
        bodies.append(_page(client, headers, **(dict(params, cursor=cursor) if cursor else params)))
        cursor = bodies[-1]["next_cursor"]
        if cursor is None:
            return bodies
    pytest.fail(f"next_cursor nie kończy się po {max_pages} stronach")


def _ids(items) -> list[int]:
    return [item["id"] for item in items]


def _b64url(text: str) -> str:
    """Kursor złożony ręcznie (base64url bez dopełnienia) — do podrabiania jego treści."""
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


# --- regresja P1: zatwierdzenie po czasie T ------------------------------------------------------------------------

def test_approved_after_t_is_in_updated_since_but_not_in_since(demo_key, client):
    """Faktura przyjęta przed T, zatwierdzona przez operatora po T: `since` (czas przyjęcia) jej nie widzi,
    `updated_since` (czas ostatniej zmiany) — tak."""
    _add_docs(demo_key, [BASE])  # zatwierdzona dawno i od tego czasu bez zmian — poza oknem updated_since=T
    r = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml"))
    assert r.status_code == 201 and r.get_json()["status"] == "needs_review"
    doc_id = r.get_json()["id"]
    db.session.get(Document, doc_id).created_at = utcnow() - timedelta(hours=1)  # przyjęta godzinę temu
    db.session.commit()
    t = format_api_datetime(utcnow())
    resolve_with_top_suggestions(db.session.get(Document, doc_id))  # operator w panelu → approved
    synced = _page(client, updated_since=t, status="approved")
    assert _ids(synced["items"]) == [doc_id] and synced["next_cursor"] is None
    assert _page(client, since=t, status="approved") == {"items": []}  # stary tryb: po czasie przyjęcia


# --- stronicowanie kursorem ----------------------------------------------------------------------------------------

def test_three_pages_return_every_document_once_in_keyset_order(demo_key, client):
    ids = _bulk(demo_key, 1203)
    bodies = _pages(client, updated_since=SINCE_BASE, limit=500)
    assert [len(b["items"]) for b in bodies] == [500, 500, 203]
    assert bodies[-1]["next_cursor"] is None
    # każdy z 1 203 dokładnie raz, rosnąco po (updated_at, id) — tutaj czas rośnie razem z id
    assert [i for b in bodies for i in _ids(b["items"])] == ids


def test_document_changed_while_paging_is_delivered_again_and_none_is_lost(demo_key, client):
    ids = _bulk(demo_key, 30)
    first = _page(client, updated_since=SINCE_BASE, limit=10)
    assert _ids(first["items"]) == ids[:10]
    changed = db.session.get(Document, ids[3])  # dokument z już pobranej strony
    touch(changed)
    db.session.commit()
    rest = _pages(client, cursor=first["next_cursor"], updated_since=SINCE_BASE, limit=10)
    # pozostałe 20 w dotychczasowej kolejności, a zmieniony jeszcze raz — na końcu, bo ma najnowszy updated_at
    assert [_ids(b["items"]) for b in rest] == [ids[10:20], ids[20:30], [ids[3]]]
    assert set(_ids(first["items"])) | {i for b in rest for i in _ids(b["items"])} == set(ids)  # żaden nie zginął
    again = rest[-1]["items"][0]
    assert again["updated_at"] == format_api_datetime(changed.updated_at) > first["items"][3]["updated_at"]


def test_cursor_of_another_key_only_sets_position(demo_key, client):
    """Kursor nie niesie zakresu: z cudzym kursorem klucz dostaje wyłącznie własne dokumenty, od wskazanej pozycji."""
    other, other_plaintext = create_key("drugi")
    db.session.commit()
    own_ids, other_ids = _bulk(demo_key, 5), _bulk(other, 5)  # te same czasy BASE+0…4 µs; id klucza 2 są większe
    cursor = _page(client, updated_since=SINCE_BASE, limit=2)["next_cursor"]  # pozycja (BASE+1 µs, own_ids[1])
    listed = _ids(_page(client, headers={"X-API-Key": other_plaintext}, cursor=cursor)["items"])
    assert not set(listed) & set(own_ids)
    assert listed == other_ids[1:]  # other_ids[0] (BASE+0 µs) leży przed pozycją kursora


def test_tied_updated_at_pages_by_id_without_gaps_or_duplicates(demo_key, client):
    ids = _bulk(demo_key, 5, step=timedelta(0))  # identyczny updated_at
    bodies = _pages(client, updated_since=SINCE_BASE, limit=2)
    assert [_ids(b["items"]) for b in bodies] == [ids[0:2], ids[2:4], ids[4:5]]


@pytest.mark.parametrize("cursor", [
    pytest.param("abc", id="nie-kursor"),
    pytest.param(_b64url("x|y"), id="czas-i-id-to-smieci"),
    pytest.param(_b64url("2026-10-11T00:00:00|0"), id="id-zero"),
    pytest.param(_b64url("2026-13-45T00:00:00.000000|1"), id="miesiac-13"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000|" + "9" * 30), id="id-poza-zakresem-bazy"),
])
def test_bad_cursor_is_400(demo_key, client, cursor):
    r = client.get("/api/v1/documents", headers=KEY, query_string={"cursor": cursor})
    assert r.status_code == 400
    error = r.get_json()["error"]
    assert error["code"] == "bad_request" and "next_cursor" in error["message"]


# --- updated_since: strefa czasowa i błędne wartości ---------------------------------------------------------------

@pytest.mark.parametrize("updated_since, expected", [
    # 08:00+02:00 == 06:00Z: okno od 06:00 UTC, tak samo jak dla 06:00 bez strefy (= UTC); granica włącznie
    pytest.param("2026-10-11T08:00:00+02:00", ["boundary", "after"], id="plus-2h"),
    pytest.param("2026-10-11T06:00:00", ["boundary", "after"], id="bez-strefy-to-utc"),
    pytest.param("2026-10-11T06:00:00Z", ["boundary", "after"], id="Z"),
    # kontrast: naiwne 08:00 to 08:00 UTC, czyli po wszystkich — dowodzi, że przesunięcie strefy jest liczone
    pytest.param("2026-10-11T08:00:00", [], id="bez-strefy-08-utc-puste"),
])
def test_updated_since_converts_zone_to_utc(demo_key, client, updated_since, expected):
    times = (datetime(2026, 10, 11, 5, 59, 59), datetime(2026, 10, 11, 6, 0, 0), datetime(2026, 10, 11, 7, 0, 0))
    ids = dict(zip(("before", "boundary", "after"), _add_docs(demo_key, times)))
    assert _ids(_page(client, updated_since=updated_since)["items"]) == [ids[k] for k in expected]


@pytest.mark.parametrize("query", [
    pytest.param("updated_since=abc", id="smieci"),
    pytest.param("updated_since=2026-13-45", id="miesiac-13"),
    pytest.param("updated_since=2026-10-11T08:00:00+02:00", id="niezakodowany-plus-to-spacja"),
])
def test_updated_since_bad_value_is_400(demo_key, client, query):
    r = client.get(f"/api/v1/documents?{query}", headers=KEY)
    assert r.status_code == 400
    error = r.get_json()["error"]
    assert error["code"] == "bad_request" and "updated_since" in error["message"]


# --- app/api/cursor.py ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("doc_id", [7, 42, 123])  # długość treści: dopełnienie „==”, „=” i bez dopełnienia
def test_cursor_round_trip_keeps_microseconds(doc_id):
    at = datetime(2026, 10, 11, 6, 4, 38, 312308)
    cursor = encode_cursor(at, doc_id)
    assert BASE64URL.fullmatch(cursor)  # bez „=” i tylko znaki base64url — w adresie nie wymaga kodowania
    assert decode_cursor(cursor) == (at, doc_id)


def test_cursor_carries_only_time_and_id():
    """Treść kursora to wyłącznie czas zmiany i id dokumentu — bez filtrów i danych wrażliwych."""
    # base64url z „2026-10-11T06:04:38.312308|7”; ze zwykłym dopełnieniem byłoby „…Nw==”
    assert encode_cursor(datetime(2026, 10, 11, 6, 4, 38, 312308), 7) == "MjAyNi0xMC0xMVQwNjowNDozOC4zMTIzMDh8Nw"


@pytest.mark.parametrize("text", [
    pytest.param("", id="pusty"),
    pytest.param("abc", id="po-dekodowaniu-nie-ascii"),
    pytest.param("A", id="zla-dlugosc-base64"),
    pytest.param("MjAy=", id="dopelnienie"),
    pytest.param("MjAy.Nw", id="znak-spoza-base64url"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000"), id="bez-separatora"),
    pytest.param(_b64url("x|1"), id="czas-smieci"),
    pytest.param(_b64url("2026-13-45T00:00:00.000000|1"), id="miesiac-13"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000|"), id="puste-id"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000|y"), id="id-nie-liczba"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000|-1"), id="id-ujemne"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000|0"), id="id-zero"),
    pytest.param(_b64url("2026-10-11T00:00:00.000000|" + "9" * 30), id="id-poza-zakresem-bazy"),
    pytest.param(None, id="None"),
])
def test_decode_rejects_bad_cursor_with_value_error(text):
    """Zawsze ValueError: API łapie tylko ten wyjątek, każdy inny dałby 500."""
    with pytest.raises(ValueError):
        decode_cursor(text)


# --- prawdziwa MariaDB (pusta baza testowa z TEST_MARIADB_URL; bez niej test jest pomijany) -------------------------

@needs_mariadb
def test_keyset_pages_writes_from_the_same_second_on_mariadb(mariadb_url, tmp_path):
    """DATETIME(6): 300 zapisów tuż po sobie (w tej samej sekundzie, różne albo równe mikrosekundy) — stronicowanie
    po 100 daje 3 strony i każdy dokument dokładnie raz, rosnąco po (updated_at, id)."""
    from app import create_app
    from app.services.seed import seed_base, seed_demo

    app = create_app({"TESTING": True, "SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": mariadb_url,
                      "STORAGE_DIR": str(tmp_path / "s"), "DEMO_MODE": True, "DEMO_API_KEY": "xp_test_demo_key",
                      "ADMIN_PASSWORD": ""})
    with app.app_context():
        try:
            db.create_all()
            seed_base()
            seed_demo()
            since = format_api_datetime(utcnow())
            ids = _add_docs(verify_key("xp_test_demo_key"), [utcnow() for _ in range(300)])  # utcnow() przy każdym
            stored = db.session.scalars(db.select(Document.updated_at)).all()
            # więcej różnych znaczników niż różnych sekund: wiele zapisów w jednej sekundzie, różne mikrosekundy
            assert len(set(stored)) > len({at.replace(microsecond=0) for at in stored})
            bodies = _pages(app.test_client(), updated_since=since, limit=100)
            listed = [item for b in bodies for item in b["items"]]
            assert [len(b["items"]) for b in bodies] == [100, 100, 100]
            assert sorted(_ids(listed)) == ids  # każdy z 300 dokładnie raz
            keys = [(item["updated_at"], item["id"]) for item in listed]
            assert keys == sorted(keys)
        finally:
            db.session.remove()  # zwolnienie transakcji — inaczej DROP TABLE w fixture czeka na blokadę metadanych
            db.engine.dispose()
