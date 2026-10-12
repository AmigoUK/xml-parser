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


class TargetError(ValueError):
    """Niedozwolony adres docelowy webhooka (komunikat po polsku, pokazywany adminowi)."""


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    path: str
    ip: str | None


def _unwrap(ip):
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


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


def _in_allowlist(ip, allowed_hosts) -> bool:
    ip = _unwrap(ip)
    return any(
        not isinstance(a, str) and a.version == ip.version and ip in a for a in allowed_hosts
    )


def validate_target(
    url: str, *, allow_http: bool = False, allowed_hosts=(), resolve: bool = True
) -> ResolvedTarget:
    """Waliduje adres webhooka; przy `resolve=True` rozwiązuje DNS i sprawdza wszystkie adresy."""
    url = (url or "").strip()
    if not url:
        raise TargetError("Adres webhooka jest pusty.")
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
    """Weryfikuje podpis (porównanie stałoczasowe) oraz świeżość znacznika czasu."""
    if not isinstance(ts, str) or not ts.isascii() or not ts.isdigit():
        return False
    current = time.time() if now is None else now
    if abs(current - int(ts)) > max_skew:
        return False
    return hmac.compare_digest(sign(secret, ts, body), signature or "")


def new_secret() -> str:
    return secrets.token_urlsafe(32)
