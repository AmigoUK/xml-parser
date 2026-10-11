"""Wysyłka faktury do parsera, odbiór dokumentu kanonicznego i synchronizacja zmian (Python 3.9+, pakiet requests).

Użycie:  python3 faktura.py faktura.xml       — wysyłka i odbiór wyniku (sposób A)
         python3 faktura.py --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

BASE_URL = "__API_BASE__/api/v1"
API_KEY = os.environ["XP_API_KEY"]  # klucz trzymaj w zmiennej środowiskowej, nie w kodzie
FINAL = {"approved", "duplicate", "rejected"}  # statusy, na których kończymy odpytywanie
SYNC_START = "1970-01-01T00:00:00Z"  # pierwszy przebieg: pełna synchronizacja (albo data wdrożenia integracji)
SYNC_MARGIN = timedelta(minutes=5)  # zapas na zmiany zatwierdzone w bazie w innej kolejności niż ich updated_at


class ApiError(Exception):
    def __init__(self, http_status, code, message):
        super().__init__(f"HTTP {http_status} {code}: {message}")
        self.http_status, self.code = http_status, code


def _call(method, path, retries=4, **kwargs):
    """Żądanie z ponawianiem przy błędach sieci i 5xx; błędy 4xx zgłaszane od razu jako ApiError."""
    delay = 2
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, BASE_URL + path, headers={"X-API-Key": API_KEY},
                                 timeout=60, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == retries:
                raise
        else:
            if r.status_code < 500 or attempt == retries:
                if r.status_code >= 400:
                    try:
                        err = r.json().get("error", {})
                    except ValueError:
                        err = {}
                    raise ApiError(r.status_code, err.get("code", "http_error"), err.get("message", r.text[:200]))
                return r.json()
        time.sleep(delay)
        delay = min(delay * 2, 60)


def send_invoice(path):
    """Wysyła plik (multipart, pole 'file'). Ponowienie po timeoucie jest bezpieczne: ten sam plik
    wysłany drugi raz tym samym kluczem dostaje status 'duplicate' ze wskazaniem oryginału."""
    with open(path, "rb") as fh:
        data = fh.read()  # bajty, nie uchwyt — przy ponowieniu wysyłamy je jeszcze raz
    return _call("POST", "/documents", files={"file": (os.path.basename(path), data)})


def original_id(doc):
    """Dla statusu 'duplicate': id wcześniejszego dokumentu tej samej faktury (albo None)."""
    for issue in doc.get("issues") or []:
        if issue.get("code") == "duplicate" and str(issue.get("source_value") or "").isdigit():
            return int(issue["source_value"])
    return None


def wait_for_result(doc_id, first_delay=5, max_delay=300, timeout=3600):
    """Odpytuje GET /documents/{id}, dopóki dokument czeka na operatora (backoff 5 s → 5 min).
    Zwraca dokument w statusie końcowym albo None po przekroczeniu `timeout` sekund."""
    deadline = time.monotonic() + timeout
    delay = first_delay
    while True:
        doc = _call("GET", f"/documents/{doc_id}")
        if doc["status"] in FINAL:
            return doc
        if time.monotonic() + delay > deadline:
            return None  # zapisz id i sprawdź później (np. z harmonogramu zadań)
        time.sleep(delay)
        delay = min(delay * 2, max_delay)


def _minus_margin(api_time):
    """'2026-10-11T06:04:38.312308Z' minus SYNC_MARGIN, w tym samym formacie (fromisoformat < 3.11 nie zna 'Z')."""
    t = datetime.fromisoformat(api_time.replace("Z", "+00:00")) - SYNC_MARGIN
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sync_approved(state_path="xp-sync.json"):
    """Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego
    przebiegu. Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id → updated_at.
    Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id)."""
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        state = {"last_sync": None, "seen": {}}
    since = _minus_margin(state["last_sync"]) if state["last_sync"] else SYNC_START
    params = {"updated_since": since, "status": "approved", "limit": 500}
    while True:
        page = _call("GET", "/documents", params=params)
        if "next_cursor" not in page:  # brak pola (a nie null) to tryb zwykły listy, a nie ostatnia strona
            raise RuntimeError("Błąd protokołu: odpowiedź bez pola next_cursor (serwer sprzed v0.5.0?) — "
                               "synchronizacja przerwana.")
        for item in page["items"]:
            if state["seen"].get(str(item["id"])) == item["updated_at"]:
                continue  # już przetworzony: powtórka z marginesu albo z granicy updated_since
            doc = _call("GET", f"/documents/{item['id']}")  # pełny wynik z invoice
            invoice = doc["invoice"] or {}
            print(f"#{doc['id']} {doc['status']} {item['updated_at']} {invoice.get('number') or ''}")
            # importuj tylko approved — pozycja listy mogła się zdezaktualizować (reprocess, odrzucenie, duplikat)
            if doc["status"] == "approved":
                pass  # tu zaimportuj doc["invoice"] do swojego systemu — idempotentnie (aktualizacja rekordu po id)
            state["seen"][str(item["id"])] = item["updated_at"]  # parę zapisz niezależnie od statusu
            # czas zawsze w formacie API (6 cyfr ułamka i Z), więc porównanie tekstów = porównanie czasu
            state["last_sync"] = max(state["last_sync"] or "", item["updated_at"])
        if state["last_sync"]:  # pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
            cutoff = _minus_margin(state["last_sync"])
            state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
        with open(state_path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(state_path + ".tmp", state_path)  # stan po każdej stronie; zapis atomowy
        if page["next_cursor"] is None:
            return state
        params["cursor"] = page["next_cursor"]  # kolejna strona: te same parametry + kursor


if __name__ == "__main__":
    if sys.argv[1] == "--sync":
        sync_approved(*sys.argv[2:3])
        sys.exit(0)
    doc = send_invoice(sys.argv[1])
    print(f"Dokument #{doc['id']}: {doc['status']} ({doc['status_label']})")
    if doc["status"] == "duplicate":
        print(f"Duplikat dokumentu #{original_id(doc)} — użyj wyniku oryginału.")
    elif doc["status"] not in FINAL:
        doc = wait_for_result(doc["id"]) or doc
    if doc["status"] == "approved":
        invoice = doc["invoice"]  # dokument kanoniczny do zaimportowania w Twoim systemie
        print(invoice["number"], invoice["totals"]["gross"], invoice["currency"])
        for line in invoice["lines"]:
            print(f"  {line['product_index']}: {line['qty']} {line['unit']} × {line['unit_price_net']}")
    elif doc["status"] == "rejected":
        print("Odrzucony:", "; ".join(i["message"] for i in doc["issues"]))
    elif doc["status"] == "needs_review":
        print("Nadal czeka na operatora — sprawdź później.")
