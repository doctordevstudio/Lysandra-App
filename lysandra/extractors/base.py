"""Extractor framework.

To add support for a website with its own logic, create a class that subclasses
`Extractor`, list its `domains`, implement `extract()` and register it in
`build_registry()` below. See docs/ADD_EXTRACTOR.md.
"""
from urllib.parse import urlparse


class ExtractorError(Exception):
    """Message is shown to the user as-is – keep it friendly."""


class Extractor:
    name = "generic"
    domains = ()          # e.g. ("example.com",) – subdomains match automatically
    relay = False         # True => app downloads through /api/v1/relay (IP-locked CDN urls)

    def __init__(self, ctx):
        self.ctx = ctx

    def matches(self, host):
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def extract(self, url):
        """Return {title, thumbnail, duration, platform, uploader, formats:[...]}.
        Each format: {fid, label, quality, ext, mime, size, url, headers, audio_only}."""
        raise NotImplementedError


class Registry:
    def __init__(self, custom, fallback, direct=None):
        self.custom = custom
        self.fallback = fallback
        self.direct = direct

    def resolve(self, host, url=None):
        from .direct import looks_direct
        if url and looks_direct(url):
            return self.direct
        for e in self.custom:
            if e.matches(host):
                return e
        return self.fallback


def host_of(url):
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def build_registry(ctx):
    from .terabox import TeraboxExtractor
    from .youtube import YouTubeExtractor
    from .ytdlp import YtDlpExtractor
    from .direct import DirectExtractor
    return Registry([YouTubeExtractor(ctx), TeraboxExtractor(ctx)], YtDlpExtractor(ctx), DirectExtractor(ctx))
