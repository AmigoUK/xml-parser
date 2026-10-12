"""Testy bezpieczeństwa celu webhooka (anty-SSRF) i podpisu HMAC — bez Flaska i bez sieci."""

from __future__ import annotations

import ipaddress
import socket
import string

import pytest

from app.services import webhook_security as ws

SECRET = "whsec_test_0123456789abcdef"
TS = "1760000000"
BODY = b'{"event":"webhook.test","id":null}'
EXPECTED_SIG = "sha256=3bbaa1b01d7597a96349f290bbb59f27e7fdfe7d4918adbf949e7c3379973d46"


def fake_dns(mapping):
    """Podmienia getaddrinfo: nazwa -> lista adresów (str) albo wyjątek."""

    def _gai(host, port, *args, **kwargs):
        result = mapping[host]
        if isinstance(result, Exception):
            raise result
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in result
        ]

    return _gai


@pytest.fixture
def dns(monkeypatch):
    def setup(mapping):
        monkeypatch.setattr(socket, "getaddrinfo", fake_dns(mapping))

    return setup


def test_rejects_http_without_flag(dns):
    dns({"example.com": ["93.184.216.34"]})
    with pytest.raises(ws.TargetError):
        ws.validate_target("http://example.com/hook")
    with pytest.raises(ws.TargetError):
        ws.validate_target("ftp://example.com/hook")


def test_allows_http_with_flag(dns):
    dns({"example.com": ["93.184.216.34"]})
    t = ws.validate_target("http://example.com/hook?x=1", allow_http=True)
    assert (t.scheme, t.host, t.port, t.ip) == ("http", "example.com", 80, "93.184.216.34")
    assert t.path == "/hook?x=1"
    t2 = ws.validate_target("https://example.com", resolve=False)
    assert t2.port == 443 and t2.ip is None and t2.path == "/"


def test_rejects_userinfo_fragment_and_long_url(dns):
    dns({"example.com": ["93.184.216.34"]})
    for url in (
        "https://user:pw@example.com/h",
        "https://user@example.com/h",
        "https://example.com/h#frag",
        "https:///path",
        "https://example.com/" + "a" * 500,
    ):
        with pytest.raises(ws.TargetError):
            ws.validate_target(url)


def test_blocks_loopback_private_linklocal_metadata_cgnat(dns):
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
               "100.64.0.1", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "0.0.0.0"):
        assert ws.is_blocked_ip(ipaddress.ip_address(ip)), ip
        with pytest.raises(ws.TargetError):
            ws.validate_target(f"https://[{ip}]/h" if ":" in ip else f"https://{ip}/h")
    assert not ws.is_blocked_ip(ipaddress.ip_address("93.184.216.34"))
    assert not ws.is_blocked_ip(ipaddress.ip_address("2606:2800:220:1::1"))


def test_localhost_name_resolving_to_loopback_is_blocked(dns):
    dns({"localhost": ["127.0.0.1", "::1"], "evil.example": ["::ffff:10.0.0.1"]})
    with pytest.raises(ws.TargetError):
        ws.validate_target("https://localhost/h")
    with pytest.raises(ws.TargetError):
        ws.validate_target("https://evil.example/h")


def test_dns_returning_one_private_among_public_is_blocked(dns):
    dns({"mixed.example": ["93.184.216.34", "10.0.0.1"], "ok.example": ["93.184.216.34", "1.1.1.1"]})
    with pytest.raises(ws.TargetError):
        ws.validate_target("https://mixed.example/h")
    assert ws.validate_target("https://ok.example/h").ip == "93.184.216.34"


def test_allowlist_hostname_and_cidr_bypass_block(dns):
    dns({"intranet.local": ["10.1.2.3"], "other.local": ["10.9.9.9"], "cidr.local": ["192.168.5.5"]})
    allowed = ws.parse_allowed_hosts("Intranet.Local, 192.168.5.0/24\n10.1.2.3 ")
    assert "intranet.local" in allowed
    assert ipaddress.ip_network("192.168.5.0/24") in allowed
    assert ws.validate_target("https://intranet.local/h", allowed_hosts=allowed).ip == "10.1.2.3"
    assert ws.validate_target("https://cidr.local/h", allowed_hosts=allowed).ip == "192.168.5.5"
    assert ws.validate_target("https://192.168.5.77/h", allowed_hosts=allowed).ip == "192.168.5.77"
    with pytest.raises(ws.TargetError):
        ws.validate_target("https://other.local/h", allowed_hosts=allowed)
    # allowlista nie omija reguł schematu
    with pytest.raises(ws.TargetError):
        ws.validate_target("http://intranet.local/h", allowed_hosts=allowed)
    assert ws.parse_allowed_hosts("") == ()


def test_dns_failure_is_target_error(dns):
    dns({"nx.example": socket.gaierror(-2, "Name or service not known")})
    with pytest.raises(ws.TargetError, match="DNS|rozwiąz"):
        ws.validate_target("https://nx.example/h")


def test_sign_matches_reference_vector():
    assert ws.sign(SECRET, TS, BODY) == EXPECTED_SIG
    assert ws.HEADER_TIMESTAMP == "X-XP-Timestamp"
    assert ws.HEADER_SIGNATURE == "X-XP-Signature"
    assert ws.HEADER_DELIVERY == "X-XP-Delivery"


def test_verify_rejects_tampered_body_and_old_timestamp():
    sig = ws.sign(SECRET, TS, BODY)
    now = 1760000000
    assert ws.verify(SECRET, TS, BODY, sig, now=now)
    assert ws.verify(SECRET, TS, BODY, sig, now=now + 300)
    assert not ws.verify(SECRET, TS, BODY + b" ", sig, now=now)
    assert not ws.verify("inny", TS, BODY, sig, now=now)
    assert not ws.verify(SECRET, TS, BODY, sig, now=now + 301)
    assert not ws.verify(SECRET, TS, BODY, sig, now=now - 301)
    assert not ws.verify(SECRET, "abc", BODY, ws.sign(SECRET, "abc", BODY), now=now)
    assert not ws.verify(SECRET, TS, BODY, "", now=now)


def test_new_secret_length_and_alphabet():
    s = ws.new_secret()
    assert len(s) >= 43
    assert set(s) <= set(string.ascii_letters + string.digits + "-_")
    assert ws.new_secret() != s
