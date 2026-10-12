#!/usr/bin/env python3
"""Odbiorca webhooka parsera faktur — Python, tylko biblioteka standardowa.

Parser wysyła POST z JSON-em i nagłówkami:
  X-XP-Timestamp  czas wysyłki (sekundy unixowe, tekst)
  X-XP-Signature  sha256=<hex HMAC-SHA256(sekret, "<timestamp>.<surowe bajty ciała>")>
  X-XP-Delivery   identyfikator dostawy (UUID) — taki sam przy ponowieniach; użyj go jako klucza idempotencji

Sekret bierz ze zmiennej XP_WEBHOOK_SECRET (nie wpisuj go w kodzie).

Ochrona przed powtórzeniem (replay): podpis obejmuje tylko „<timestamp>.<ciało>”, bez nagłówka X-XP-Delivery,
więc w oknie ±300 s identyczne żądanie można przesłać ponownie. Deduplikuj po X-XP-Delivery WYŁĄCZNIE PO
pozytywnej weryfikacji podpisu (inaczej ktoś bez sekretu mógłby „zająć” cudzy identyfikator), przechowuj
widziane identyfikatory trwale (np. tabela webhook_deliveries_seen z unikalnym kluczem albo zbiór w Redis
z TTL > 300 s) i powtórzony identyfikator traktuj jak sukces: odpowiedz 200 bez ponownego przetwarzania.

Tryby:
  python3 webhook-odbiorca.py --port 9000                        serwer HTTP (domyślnie port 9000)
  python3 webhook-odbiorca.py --check <ts> <podpis> < ciało.json weryfikacja bez sieci: OK / powód, kod 0 / 1
                                                                 (opcjonalnie --now <ts> zamiast zegara systemowego)
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 1024 * 1024  # 1 MiB: większe ciało odrzucamy (413) bez czytania
MAX_SKEW = 300  # sekundy: starsze lub „z przyszłości” żądania odrzucamy (ochrona przed powtórzeniem)


def verify(secret: str, timestamp: str, signature: str, body: bytes, now: int | None = None) -> str | None:
    """None, gdy podpis jest poprawny; w przeciwnym razie powód odrzucenia (po polsku)."""
    try:
        sent = int(timestamp)
    except (TypeError, ValueError):
        return "nieprawidłowy znacznik czasu"
    if abs((int(time.time()) if now is None else now) - sent) > MAX_SKEW:
        return f"znacznik czasu poza dopuszczalnym oknem {MAX_SKEW} s"
    # Podpis liczymy z SUROWYCH bajtów ciała — nie z ponownie zserializowanego JSON-a.
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):  # porównanie w stałym czasie
        return "nieprawidłowy podpis"
    return None


class Handler(BaseHTTPRequestHandler):
    secret = ""
    seen: set[str] = set()  # ilustracja; w produkcji trwały magazyn (tabela / Redis), nie pamięć procesu

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.reply(411, "wymagany poprawny nagłówek Content-Length")
        if length < 0:
            return self.reply(400, "nieprawidłowy Content-Length")
        if length > MAX_BODY:
            return self.reply(413, "ciało zbyt duże")
        body = self.rfile.read(length)
        reason = verify(self.secret, self.headers.get("X-XP-Timestamp", ""),
                        self.headers.get("X-XP-Signature", ""), body)
        if reason:
            print(f"odrzucono: {reason}", flush=True)
            return self.reply(401, reason)
        # Dopiero po weryfikacji przetwarzamy treść. Odpowiadaj szybko (2xx); ciężką pracę zlecaj w tle.
        # Dostawa może przyjść ponownie z tym samym X-XP-Delivery — zapisuj go i pomijaj duplikaty.
        try:
            data = json.loads(body)
        except ValueError:
            return self.reply(400, "ciało nie jest JSON-em")
        if not isinstance(data, dict):
            return self.reply(400, "ciało musi być obiektem JSON")
        delivery = self.headers.get("X-XP-Delivery", "")
        if delivery in self.seen:  # powtórzona dostawa: sukces bez ponownego przetwarzania
            return self.reply(200, "ok (duplikat)")
        self.seen.add(delivery)
        if data.get("event") == "webhook.test":
            print("test OK", flush=True)
        else:
            print(f"event={data.get('event')} id={data.get('id')} status={data.get('status')} "
                  f"delivery={delivery}", flush=True)
        self.reply(200, "ok")

    def reply(self, code: int, text: str):
        payload = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # własne wiersze dziennika wyżej


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", nargs=2, metavar=("TS", "PODPIS"), help="zweryfikuj ciało ze stdin i zakończ")
    parser.add_argument("--now", type=int, help="z --check: bieżący czas (sekundy unixowe) zamiast zegara")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    secret = os.environ.get("XP_WEBHOOK_SECRET", "")
    if not secret:
        print("Ustaw zmienną XP_WEBHOOK_SECRET (sekret webhooka z panelu).", file=sys.stderr)
        return 2
    if args.check:
        reason = verify(secret, args.check[0], args.check[1], sys.stdin.buffer.read(), args.now)
        print(reason or "OK")
        return 1 if reason else 0
    Handler.secret = secret
    print(f"Nasłuch na porcie {args.port} (Ctrl+C kończy)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
