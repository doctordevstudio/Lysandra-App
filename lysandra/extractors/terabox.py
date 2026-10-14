"""TeraBox family. Needs an upstream resolver configured with TERABOX_API_URL.

The resolver contract is documented in docs/ADD_EXTRACTOR.md. Until it is
configured the app shows a clear "not available" message (no fake data)."""
import requests

from .base import Extractor, ExtractorError


class TeraboxExtractor(Extractor):
    name = "terabox"
    domains = ("terabox.com", "terabox.app", "teraboxapp.com", "1024terabox.com", "1024tera.com", "tera1024.com",
               "4funbox.com", "mirrobox.com", "nephobox.com", "freeterabox.com", "momerybox.com",
               "teraboxlink.com", "terafileshare.com", "terabox.club")

    def extract(self, url):
        api = self.ctx.settings.terabox_api_url
        if not api:
            raise ExtractorError("TeraBox downloads are not enabled on the server yet.")
        try:
            r = requests.get(api, params={"url": url}, timeout=20)
            j = r.json()
        except Exception:
            raise ExtractorError("TeraBox service is not responding. Please try again later.")
        link = j.get("download_url") or j.get("url")
        if not r.ok or not link:
            raise ExtractorError("Could not fetch this TeraBox link.")
        ext = (j.get("ext") or "mp4").lower().lstrip(".")
        return {"title": (j.get("title") or "TeraBox file")[:200], "thumbnail": j.get("thumbnail") or "",
                "duration": int(j.get("duration") or 0), "uploader": "", "platform": "TeraBox", "relay": False,
                "formats": [{"fid": "tb_orig", "label": f"Original {ext.upper()}", "quality": "Original", "ext": ext,
                             "mime": "video/mp4" if ext in ("mp4", "mov", "mkv") else "application/octet-stream",
                             "size": int(j.get("size") or 0), "url": link, "headers": {}, "audio_only": False,
                             "height": 0}]}
