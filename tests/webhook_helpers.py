"""Wspólne narzędzia testów webhooków (tests/test_webhooks_delivery.py, tests/test_cli_webhooks.py): lokalny
odbiorca HTTP z trybami odpowiedzi oraz fabryki kluczy API i dostaw. Fixtures `receiver`/`no_connection` są
w tests/conftest.py."""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.extensions import db
from app.models import EVENT_STATUS_CHANGED, WEBHOOK_PENDING, ApiKey, WebhookDelivery, utcnow

SECRET = "sekret-testowy-hurtowni-alfa"
NOW = utcnow().replace(microsecond=0)
SHUTDOWN_POLL = 0.05


# ---------------------------------------------------------------- odbiorca testowy

class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # zerwane połączenia (timeout klienta) nie brudzą wyjścia
        pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                                     "body": body})

    def _reply(self, code, body=b"", headers=()):
        self.send_response(code)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._record()
        self._reply(200, b"ok")

    def do_POST(self):
        self._record()
        mode = self.server.mode
        try:
            if mode == "ok":
                self._reply(200, b"ok")
            elif mode == "error":
                self._reply(500, b"awaria odbiorcy")
            elif mode == "redirect":
                self._reply(302, b"", [("Location", "/inne")])
            elif mode == "slow":
                self.server.release.wait(5)
                self._reply(200, b"za pozno")
            elif mode == "trickle":
                # status i nagłówki po jednym bajcie co 0,1 s — każde recv dostaje coś przed limitem pojedynczej
                # operacji, więc tylko łączny limit czasu przerwie takie żądanie
                for byte in b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nok":
                    if self.server.release.wait(0.1):
                        break
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            elif mode == "big":
                # zapowiada 10 MB, wysyła 2 KB i czeka — pełny odczyt zawisłby do limitu czasu
                self.send_response(500)
                self.send_header("Content-Length", str(10 * 1024 * 1024))
                self.end_headers()
                self.wfile.write(b"B" * 2048)
                self.wfile.flush()
                self.server.release.wait(5)
        except OSError:
            pass


class Receiver:
    def __init__(self):
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.requests = []
        self.server.mode = "ok"
        self.server.release = threading.Event()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/hook?zrodlo=xp"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": SHUTDOWN_POLL},
                                       daemon=True)
        self.thread.start()

    @property
    def requests(self):
        return self.server.requests

    def set_mode(self, mode):
        self.server.mode = mode

    def close(self):
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def make_key(url, *, secret=SECRET, active=True, name="Hurtownia Alfa — ERP"):
    key = ApiKey(name=name, prefix="xp_test", key_hash=os.urandom(32).hex(), active=active, webhook_url=url,
                 webhook_secret=secret)
    db.session.add(key)
    db.session.flush()
    return key


def make_delivery(key, *, doc_id=7, status=WEBHOOK_PENDING, next_attempt_at=None, created_at=None, attempts=0):
    payload = {"event": EVENT_STATUS_CHANGED, "id": doc_id, "status": "approved", "previous_status": "received",
               "updated_at": "2026-10-12T10:00:00Z", "document_url": f"https://xp.example.test/dokumenty/{doc_id}"}
    d = WebhookDelivery(api_key_id=key.id, event=EVENT_STATUS_CHANGED, payload=payload, status=status,
                        next_attempt_at=next_attempt_at, attempts=attempts)
    if created_at is not None:
        d.created_at = created_at
    db.session.add(d)
    db.session.commit()
    return d


def reload(delivery):
    db.session.expire_all()
    return db.session.get(WebhookDelivery, delivery.id)
