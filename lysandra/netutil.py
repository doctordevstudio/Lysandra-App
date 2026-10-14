"""SSRF-safe outbound HTTP helpers. The server never connects to private / loopback / link-local addresses,
even when a public-looking hostname resolves to one."""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

UA = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"


class UnsafeURL(Exception):
    pass


def host_is_public(host):
    """True when every address the host resolves to is a public unicast address."""
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            a = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if a.is_private or a.is_loopback or a.is_reserved or a.is_link_local or a.is_multicast or a.is_unspecified:
            return False
    return bool(infos)


def check_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeURL("bad url")
    if not host_is_public(p.hostname):
        raise UnsafeURL("private address")
    return url


def safe_request(method, url, headers=None, max_bytes=2_000_000, timeout=8, max_redirects=3):
    """GET/HEAD with manual redirect handling (each hop re-validated) and a hard body size cap."""
    hdr = {"User-Agent": UA, "Accept": "*/*"}
    hdr.update(headers or {})
    for _ in range(max_redirects + 1):
        check_url(url)
        r = requests.request(method, url, headers=hdr, timeout=timeout, stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            r.close()
            continue
        body = b""
        if method == "GET":
            for chunk in r.iter_content(64 * 1024):
                body += chunk
                if len(body) > max_bytes:
                    break
        r.close()
        return r.status_code, r.headers, body[:max_bytes], url
    raise UnsafeURL("too many redirects")
