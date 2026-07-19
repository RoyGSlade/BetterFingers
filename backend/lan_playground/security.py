"""Security primitives for the LAN playground (board #33).

Pure, dependency-light policy helpers -- no FastAPI, model, or network
imports -- so they're unit-testable standalone and shared by both the ASGI
app (backend/lan_playground/app.py) and its CLI entrypoint
(tools/lan_playground.py).

Nothing here ever logs or echoes request content.
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import socket
import time
from collections import defaultdict, deque

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    ),
    # Explicitly denies every audio/media capture API at the browser
    # permission-policy level -- belt-and-suspenders for "no audio APIs".
    "Permissions-Policy": "microphone=(), camera=(), geolocation=(), usb=(), display-capture=()",
}


def is_loopback_host(host: str) -> bool:
    return str(host or "").strip().lower() in LOOPBACK_HOSTS


def generate_access_code() -> str:
    """High-entropy, URL-safe code (~144 bits) for sharing over a link or verbally."""
    return secrets.token_urlsafe(18)


def generate_token() -> str:
    """High-entropy, URL-safe opaque token (~144 bits) for host/player auth headers."""
    return secrets.token_urlsafe(18)


_ROOM_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"  # no 0/O/1/I/L/U -- avoids transcription errors


def generate_room_code(length: int = 8) -> str:
    """Short, human-shareable room code (Crockford-ish base32, unambiguous alphabet).

    Not the primary security boundary by itself -- every game route also
    requires the site-wide X-Access-Code header plus Host/Origin checks; this
    just keeps someone from stumbling into a stranger's room by guessing a
    room id while the site-wide code is shared among trusted LAN guests.
    """
    return "".join(secrets.choice(_ROOM_CODE_ALPHABET) for _ in range(length))


def constant_time_equals(a: str, b: str) -> bool:
    # An empty secret must never authenticate, even against another empty
    # string (hmac.compare_digest("", "") is True by definition).
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def _is_private_ipv4(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return addr.is_private and not addr.is_loopback and not addr.is_link_local and not addr.is_multicast


def reachable_lan_ips() -> list[str]:
    """Best-effort list of this host's private IPv4 addresses (RFC1918)."""
    ips: list[str] = []
    seen: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in seen and _is_private_ipv4(ip):
                seen.add(ip)
                ips.append(ip)
    except OSError:
        pass
    # Fallback: a UDP "connect" (no packets sent) reveals the outbound-facing
    # interface IP, which getaddrinfo(hostname) sometimes misses (e.g. when
    # /etc/hosts maps the hostname to 127.0.1.1, common on Debian/Ubuntu).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            ip = probe.getsockname()[0]
            if ip not in seen and _is_private_ipv4(ip):
                seen.add(ip)
                ips.append(ip)
    except OSError:
        pass
    return ips


def host_header_allowed(host_header: str, allowed_hosts: set[str]) -> bool:
    hostname = (host_header or "").split(":", 1)[0].strip().lower()
    return bool(hostname) and hostname in allowed_hosts


def origin_allowed(origin_header: str | None, allowed_origins: set[str]) -> bool:
    """Same-origin policy: no Origin header (non-browser/plain navigation) passes;
    a present Origin header must match one of our own bound origins exactly."""
    if not origin_header:
        return True
    return origin_header.strip().lower() in {o.lower() for o in allowed_origins}


def sanitize_custom_instruction(text: str, max_chars: int) -> str:
    """Bound and normalize a user-supplied style instruction.

    This only guards against control-character/prompt-structure abuse and
    enforces the length cap -- it is NOT the safety mechanism against
    fabricated content. That job belongs to
    backend.services.message_rescue.check_preservation, which runs
    downstream on every variant regardless of what this instruction says.
    """
    if not text:
        return ""
    cleaned = "".join(ch for ch in text if ch in "\n\t" or (ch.isprintable() and ch != "\r"))
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_chars]


class RateLimiter:
    """Fixed-window-ish per-key request limiter (in-memory, single-process)."""

    def __init__(self, max_requests: int, window_s: float = 60.0):
        self.max_requests = max_requests
        self.window_s = window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
