"""
Security and SSRF Protection Utilities.
Ensures zero arbitrary local network probing and validates all external input.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse
from typing import Final

ALLOWED_MUSIC_DOMAINS: Final[frozenset[str]] = frozenset({
    "open.spotify.com",
    "spotify.link",
    "spotify.com",
    "music.youtube.com",
    "www.youtube.com",
    "youtube.com",
    "youtu.be",
    "music.apple.com",
    "tidal.com",
    "listen.tidal.com",
    "deezer.com",
    "www.deezer.com",
    "deezer.page.link",
    "soundcloud.com",
    "m.soundcloud.com",
    "api.soundcloud.com",
})

SEEK_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:(\d{1,2}):)?(\d{1,2}):)?(\d{1,2})$"
)


class SecurityValidationError(ValueError):
    """Raised when an untrusted input fails security checks."""
    pass


def is_safe_music_url(url: str) -> bool:
    """
    Validates that a URL is strictly HTTPS, belongs to an approved music provider,
    and does not resolve to a private or loopback IP address (SSRF mitigation).
    """
    if not url or len(url) > 2048:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Strictly HTTPS
    if parsed.scheme.lower() != "https":
        return False

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    # Check hostname whitelist or matching base domain
    domain_matched = False
    for allowed in ALLOWED_MUSIC_DOMAINS:
        if hostname == allowed or hostname.endswith("." + allowed):
            domain_matched = True
            break

    if not domain_matched:
        return False

    # Verify IP resolution (Block SSRF / DNS rebinding to 127.0.0.1, 10.0.0.0/8, etc.)
    nat64_net = ipaddress.ip_network("64:ff9b::/96")
    try:
        addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)

            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_unspecified
            ):
                return False

            # Check NAT64 well-known prefix (RFC 6052)
            if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in nat64_net:
                embedded_v4 = ipaddress.IPv4Address(ip_obj.packed[-4:])
                if (
                    embedded_v4.is_private
                    or embedded_v4.is_loopback
                    or embedded_v4.is_link_local
                    or embedded_v4.is_multicast
                    or embedded_v4.is_unspecified
                ):
                    return False
            elif ip_obj.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False

    return True


def sanitize_seek_timestamp(timestamp_str: str, max_duration_ms: int) -> int:
    """
    Converts timestamp string (e.g. '03:45', '1:20:30', or '45') into milliseconds,
    strictly bounded between 0 and track maximum length.
    """
    cleaned = timestamp_str.strip()
    match = SEEK_PATTERN.match(cleaned)
    if not match:
        raise SecurityValidationError(
            f"Invalid seek format '{timestamp_str}'. Expected format is MM:SS or HH:MM:SS."
        )

    hours_str, minutes_str, seconds_str = match.groups()
    hours = int(hours_str) if hours_str else 0
    minutes = int(minutes_str) if minutes_str else 0
    seconds = int(seconds_str) if seconds_str else 0

    if minutes >= 60 or seconds >= 60:
        raise SecurityValidationError("Minutes and seconds must be less than 60.")

    total_seconds = hours * 3600 + minutes * 60 + seconds
    total_ms = total_seconds * 1000

    if total_ms < 0:
        return 0
    if total_ms > max_duration_ms:
        return max_duration_ms

    return total_ms


def sanitize_gain(gain: float) -> float:
    """
    Enforces that equalizer gain sits firmly within Lavalink limits [-0.25, 1.0].
    """
    if not isinstance(gain, (int, float)):
        raise SecurityValidationError("Equalizer gain must be a numeric value.")
    clamped = max(-0.25, min(1.0, float(gain)))
    return round(clamped, 3)
