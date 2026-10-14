"""Fallback extractor – yt-dlp, which understands 1000+ sites."""
from .base import Extractor, ExtractorError

from .formats import build_formats


class YtDlpExtractor(Extractor):
    name = "yt-dlp"

    def opts(self):
        return {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
                "socket_timeout": 15, "retries": 1, "extractor_retries": 1, "nocheckcertificate": False,
                "playlist_items": "1", "geo_bypass": True}

    def run(self, url, extra=None):
        try:
            import yt_dlp
        except ImportError:
            raise ExtractorError("Downloader engine is not installed on the server.")
        o = self.opts()
        o.update(extra or {})
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:  # yt_dlp raises many DownloadError flavours
            msg = str(e)
            self.ctx.log.info("yt-dlp failed for %s: %s", url[:80], msg[:200])
            if "Unsupported URL" in msg:
                raise ExtractorError("This link is not supported. Please paste a direct video page link.")
            if "Private" in msg or "login" in msg.lower() or "Sign in" in msg:
                raise ExtractorError("This video is private or needs login, so it can't be downloaded.")
            raise ExtractorError("Could not fetch this video. Please check the link and try again.")
        if info and info.get("entries"):
            entries = [e for e in info["entries"] if e]
            info = entries[0] if entries else None
        if not info:
            raise ExtractorError("No downloadable video found at this link.")
        return info

    def extract(self, url):
        info = self.run(url)
        return self.shape(info)

    def shape(self, info):
        formats = build_formats(info)
        if not formats:
            raise ExtractorError("No downloadable formats were found for this video.")
        thumb = info.get("thumbnail") or ""
        if not thumb and info.get("thumbnails"):
            ths = [t for t in info["thumbnails"] if t.get("url")]
            ths.sort(key=lambda t: (t.get("height") or 0) * (t.get("width") or 0) or t.get("preference") or 0)
            thumb = ths[-1]["url"] if ths else ""
        return {"title": (info.get("title") or info.get("fulltitle") or "Video")[:200], "thumbnail": thumb,
                "duration": int(info.get("duration") or 0), "uploader": (info.get("uploader") or info.get("channel") or "")[:80],
                "platform": (info.get("extractor_key") or "Web").replace("Youtube", "YouTube"), "formats": formats,
                "relay": self.relay, "live": bool(info.get("is_live")), "direct": False,
                "upload_date": info.get("upload_date") or "", "views": int(info.get("view_count") or 0)}
