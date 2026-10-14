"""YouTube – yt-dlp through a rotating proxy (YOUTUBE_PROXIES), optional cookies (YT_COOKIES)."""
import itertools
import os
import tempfile
import threading

from .base import ExtractorError
from .ytdlp import YtDlpExtractor


class YouTubeExtractor(YtDlpExtractor):
    name = "youtube"
    domains = ("youtube.com", "youtu.be", "youtube-nocookie.com", "youtubekids.com")
    relay = True   # googlevideo URLs are locked to the IP that resolved them

    def __init__(self, ctx):
        super().__init__(ctx)
        self._cycle = itertools.cycle(ctx.settings.youtube_proxies or [None])
        self._lock = threading.Lock()
        self._cookie_file = None
        if ctx.settings.youtube_cookies.strip():
            f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
            f.write(ctx.settings.youtube_cookies.replace("\\n", "\n"))
            f.close()
            os.chmod(f.name, 0o600)
            self._cookie_file = f.name

    def next_proxy(self):
        with self._lock:
            return next(self._cycle)

    def extract(self, url):
        proxies = self.ctx.settings.youtube_proxies or [None]
        last = None
        for _ in range(min(3, len(proxies))):
            proxy = self.next_proxy()
            extra = {}
            if proxy:
                extra["proxy"] = proxy
            if self._cookie_file:
                extra["cookiefile"] = self._cookie_file
            try:
                info = self.run(url, extra)
                res = self.shape(info)
                res["proxy"] = proxy
                return res
            except ExtractorError as e:
                last = e
        raise last or ExtractorError("Could not fetch this YouTube video right now. Please try again.")
