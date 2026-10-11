"""Wysyłka faktury do parsera i odbiór dokumentu kanonicznego (Python 3.9+, pakiet requests)."""
import os
import sys
import time

import requests

BASE_URL = "__API_BASE__/api/v1"
API_KEY = os.environ["XP_API_KEY"]  # klucz trzymaj w zmiennej środowiskowej, nie w kodzie
FINAL = {"approved", "duplicate", "rejected"}  # statusy, na których kończymy odpytywanie


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


if __name__ == "__main__":
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
