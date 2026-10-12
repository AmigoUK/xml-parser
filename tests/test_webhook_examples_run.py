"""Przykłady odbiorcy webhooka z Pomocy (app/help_examples/webhook-odbiorca.*) uruchamiane naprawdę: tryb --check
(bez sieci) w każdym języku wobec wektora referencyjnego oraz serwer Pythona wobec prawdziwego żądania HTTP.
Brak środowiska = skip tylko tego języka."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.web.help import EXAMPLES_DIR, WEBHOOK_EXAMPLES
from tests.test_help_examples_run import RUNTIMES, require_runtime

SECRET = "whsec_test_0123456789abcdef"
TS = "1760000000"
BODY = b'{"event":"webhook.test","id":null}'
SIGNATURE = "sha256=3bbaa1b01d7597a96349f290bbb59f27e7fdfe7d4918adbf949e7c3379973d46"
FILES = {"python": "webhook-odbiorca.py", "php": "webhook-odbiorca.php", "node": "webhook-odbiorca.mjs",
         "bash": "webhook-odbiorca.sh"}


@pytest.fixture(params=list(FILES))
def runtime(request):
    require_runtime(request.param)
    return request.param


def check(runtime: str, body: bytes, ts: str, signature: str, now: str | None = None):
    args = ["--check", ts, signature] + (["--now", now] if now else [])
    cmd = [shutil.which(RUNTIMES[runtime][1]) or RUNTIMES[runtime][1], str(EXAMPLES_DIR / FILES[runtime]), *args]
    return subprocess.run(cmd, input=body, capture_output=True, timeout=30,
                          env={**os.environ, "XP_WEBHOOK_SECRET": SECRET})


def test_check_mode_accepts_valid_signature(runtime):
    res = check(runtime, BODY, TS, SIGNATURE, now=TS)
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.decode().strip() == "OK"


def test_check_mode_rejects_tampered_body(runtime):
    res = check(runtime, BODY + b" ", TS, SIGNATURE, now=TS)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "OK" not in res.stdout.decode().split()
    assert res.stdout.decode().strip()  # powód po polsku


def test_check_mode_rejects_stale_timestamp(runtime):
    res = check(runtime, BODY, TS, SIGNATURE, now=str(int(TS) + 301))
    assert res.returncode == 1, res.stdout + res.stderr
    assert check(runtime, BODY, TS, SIGNATURE, now=str(int(TS) + 300)).returncode == 0  # granica włącznie


def test_check_mode_rejects_malformed_signature_and_timestamp(runtime):
    """Brak prefiksu sha256=, wielkie litery hex, nienumeryczny i ogromny znacznik czasu — zawsze kod 1."""
    hexpart = SIGNATURE.removeprefix("sha256=")
    assert check(runtime, BODY, TS, hexpart, now=TS).returncode == 1
    assert check(runtime, BODY, TS, "sha256=" + hexpart.upper(), now=TS).returncode == 1
    assert check(runtime, BODY, "abc", SIGNATURE, now=TS).returncode == 1
    assert check(runtime, BODY, "9" * 30, SIGNATURE, now=TS).returncode == 1


def test_examples_have_no_api_base_leftovers():
    for _lang, _title, name in WEBHOOK_EXAMPLES:
        path = EXAMPLES_DIR / name
        assert path.is_file(), name
        assert "__API_BASE__" not in path.read_text(encoding="utf-8"), name
    assert sorted(n for _, _, n in WEBHOOK_EXAMPLES) == sorted(FILES.values())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url: str, body: bytes, ts: str, signature: str) -> int:
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-XP-Timestamp": ts, "X-XP-Signature": signature,
        "X-XP-Delivery": "00000000-0000-4000-8000-000000000000"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_python_receiver_serves_200_and_verifies():
    import hmac
    from hashlib import sha256
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(EXAMPLES_DIR / FILES["python"]), "--port", str(port)],
                            env={**os.environ, "XP_WEBHOOK_SECRET": SECRET},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        url = f"http://127.0.0.1:{port}/"
        ts = str(int(time.time()))
        body = json.dumps({"event": "webhook.test", "id": None, "status": None}).encode()
        sig = "sha256=" + hmac.new(SECRET.encode(), ts.encode() + b"." + body, sha256).hexdigest()
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            try:
                status = _post(url, body, ts, sig)
                break
            except OSError:
                time.sleep(0.1)
        assert status == 200
        assert _post(url, body, ts, "sha256=" + "0" * 64) == 401
        assert _post(url, body + b" ", ts, sig) == 401
        for raw in (b"null", b"[]", b"42"):  # poprawnie podpisane, ale nie obiekt JSON -> 400, serwer żyje dalej
            raw_sig = "sha256=" + hmac.new(SECRET.encode(), ts.encode() + b"." + raw, sha256).hexdigest()
            assert _post(url, raw, ts, raw_sig) == 400
        assert _post(url, body, ts, sig) == 200  # duplikat (ten sam X-XP-Delivery) nadal 200
    finally:
        proc.kill()
        proc.communicate(timeout=10)
