"""
SSRF / input-validation guard. The whole point of this API is "fetch
whatever URL the user pastes" -- which is exactly the shape of a classic
SSRF vulnerability (OWASP A10) if left unchecked: someone could paste
http://169.254.169.254/latest/meta-data/ or http://localhost:6379/ and get
your server to attack itself or your internal network.

normalize_and_validate() must be called on every incoming URL before it
reaches any extractor.
"""
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Hostnames/suffixes we never allow, regardless of what they resolve to.
BLOCKED_HOST_SUFFIXES = ("localhost", ".local", ".internal")


class UnsafeUrlError(Exception):
    pass


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse -> treat as unsafe
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def normalize_and_validate(raw_url: str) -> tuple[str, str]:
    """
    Returns (normalized_url, domain) or raises UnsafeUrlError.
    domain is lowercased with a leading 'www.' stripped, for extractor matching.
    """
    raw_url = raw_url.strip()
    if len(raw_url) > 2048:
        raise UnsafeUrlError("URL too long")

    parsed = urlparse(raw_url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Only http/https URLs are allowed")

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("No host in URL")

    if any(host == s.lstrip(".") or host.endswith(s) for s in BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError("Host not allowed")

    # Resolve and block requests to private/loopback/link-local/metadata IPs.
    try:
        resolved_ips = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        raise UnsafeUrlError("Host does not resolve")

    for ip in resolved_ips:
        if _is_private_ip(ip):
            raise UnsafeUrlError("Host resolves to a disallowed address")

    domain = host[4:] if host.startswith("www.") else host
    return raw_url, domain
