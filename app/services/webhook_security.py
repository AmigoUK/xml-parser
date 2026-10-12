"""Bezpieczeństwo webhooków: walidacja celu (anty-SSRF) i podpis HMAC dostaw.

Moduł jest czysty (bez DB i bez Flaska) — konfigurację (`WEBHOOK_ALLOW_HTTP`,
`WEBHOOK_ALLOWED_HOSTS`) przyjmuje przez argumenty.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

HEADER_TIMESTAMP = "X-XP-Timestamp"
HEADER_SIGNATURE = "X-XP-Signature"
HEADER_DELIVERY = "X-XP-Delivery"

MAX_URL_LENGTH = 500
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPAT = ipaddress.ip_network("::/96")


class TargetError(ValueError):
    """Niedozwolony adres docelowy webhooka (komunikat po polsku, pokazywany adminowi)."""


@dataclass(frozen=True)
class ResolvedTarget:
    """Zwalidowany cel: składniki URL oraz wybrany adres IP (None przy `resolve=False`)."""

    url: str
    scheme: str
    host: str
    port: int
    path: str
    ip: str | None


def _unwrap(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Rozpakowuje IPv4 osadzone w IPv6 (mapped, NAT64 64:ff9b::/96, zgodne ::/96)."""
    if ip.version == 6:
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return mapped
        if ip in _NAT64 or ip in _V4_COMPAT:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def is_blocked_ip(ip) -> bool:
    """Czy adres jest niepubliczny (loopback, prywatny, link-local/metadata, CGNAT, ...)."""
    ip = _unwrap(ip)
    if ip.version == 4 and ip in _CGNAT:
        return True
    return not ip.is_global


def parse_allowed_hosts(text: str) -> tuple:
    """Parsuje listę dozwolonych celów (nazwy hostów lub IP/CIDR) rozdzieloną przecinkami/białymi znakami."""
    items: list = []
    for token in (text or "").replace(",", " ").split():
        try:
            items.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            items.append(token.lower())
    return tuple(items)


def _in_allowlist(ip, allowed_hosts: tuple) -> bool:
    ip = _unwrap(ip)
    return any(
        not isinstance(a, str) and a.version == ip.version and ip in a for a in allowed_hosts
    )


def validate_target(
    url: str, *, allow_http: bool = False, allowed_hosts: tuple = (), resolve: bool = True
) -> ResolvedTarget:
    """Waliduje adres webhooka; przy `resolve=True` rozwiązuje DNS i sprawdza wszystkie adresy."""
    url = (url or "").strip()
    if not url:
        raise TargetError("Adres webhooka jest pusty.")
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise TargetError("Adres webhooka nie może zawierać spacji ani znaków sterujących.")
    if len(url) > MAX_URL_LENGTH:
        raise TargetError(f"Adres webhooka jest za długi (maks. {MAX_URL_LENGTH} znaków).")
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise TargetError("Adres webhooka jest nieprawidłowy.") from None
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise TargetError("Dozwolony jest tylko adres https://.")
    if scheme == "http" and not allow_http:
        raise TargetError("Adres http:// jest wyłączony — użyj https:// (lub włącz WEBHOOK_ALLOW_HTTP).")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise TargetError("Adres webhooka nie może zawierać danych logowania (user:hasło@).")
    if parts.fragment or "#" in url:
        raise TargetError("Adres webhooka nie może zawierać fragmentu (#...).")
    if not host:
        raise TargetError("Adres webhooka nie zawiera nazwy hosta.")
    host = host.lower()
    if port is not None and not 1 <= port <= 65535:
        raise TargetError("Port w adresie webhooka musi mieścić się w zakresie 1–65535.")
    if port is None:
        port = 443 if scheme == "https" else 80
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    if not resolve:
        return ResolvedTarget(url, scheme, host, port, path, None)

    allowed_names = {a for a in allowed_hosts if isinstance(a, str)}
    host_allowed = host in allowed_names

    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError):
            raise TargetError(f"Nie udało się rozwiązać nazwy hosta „{host}” (DNS).") from None
        addresses = []
        for info in infos:
            raw = info[4][0].split("%", 1)[0]
            try:
                addresses.append(ipaddress.ip_address(raw))
            except ValueError:
                continue
        if not addresses:
            raise TargetError(f"Host „{host}” nie ma adresów IP.") from None

    chosen = None
    for ip in addresses:
        if not (host_allowed or _in_allowlist(ip, allowed_hosts)) and is_blocked_ip(ip):
            raise TargetError(
                f"Adres wskazuje na sieć niepubliczną ({ip}) — niedozwolone (ochrona SSRF)."
            )
        if chosen is None:
            chosen = str(_unwrap(ip))
    return ResolvedTarget(url, scheme, host, port, path, chosen)


def sign(secret: str, ts: str, body: bytes) -> str:
    """Podpis HMAC-SHA256 z `"<ts>.<body>"`; zwraca `sha256=<hex>`."""
    mac = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(
    secret: str, ts: str, body: bytes, signature: str, *, max_skew: int = 300, now: float | None = None
) -> bool:
    """Weryfikuje podpis (porównanie stałoczasowe) i świeżość znacznika czasu; nigdy nie rzuca wyjątku."""
    try:
        if not (isinstance(secret, str) and isinstance(ts, str) and isinstance(body, bytes)):
            return False
        if not isinstance(signature, str):
            return False
        if not (ts.isascii() and ts.isdigit() and len(ts) <= 12):
            return False
        current = time.time() if now is None else now
        if abs(current - int(ts)) > max_skew:
            return False
        expected = sign(secret, ts, body).encode()
        return hmac.compare_digest(expected, signature.encode("utf-8", "surrogateescape"))
    except (TypeError, ValueError, AttributeError, UnicodeError):
        return False


def new_secret() -> str:
    """Nowy sekret podpisu (256 bitów, alfabet URL-safe); pokazywany adminowi tylko raz."""
    return secrets.token_urlsafe(32)
