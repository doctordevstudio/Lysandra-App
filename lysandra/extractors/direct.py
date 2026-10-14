"""Directly playable links (.m3u8, .mp4, .mkv, .mp3 ...): no scraping, just describe the file for the app."""
import posixpath
from urllib.parse import unquote, urlparse

from ..netutil import UnsafeURL, safe_request
from . import hls
from .base import Extractor, ExtractorError
from .formats import MIME, OK_EXT

DIRECT_EXT = OK_EXT | {"m3u8"}


def looks_direct(url):
    path = urlparse(url).path.lower()
    return posixpath.splitext(path)[1].lstrip(".") in DIRECT_EXT


class DirectExtractor(Extractor):
    name = "direct"
    domains = ()

    def title_of(self, url):
        p = urlparse(url)
        base = unquote(posixpath.basename(p.path))
        name = posixpath.splitext(base)[0]
        if name.lower() in ("index", "master", "playlist", "") or len(name) < 3:
            name = posixpath.basename(posixpath.dirname(p.path)) or p.hostname
        return (name or p.hostname).replace("_", " ").replace("-", " ").strip()[:120]

    def extract(self, url):
        ext = posixpath.splitext(urlparse(url).path.lower())[1].lstrip(".")
        host = (urlparse(url).hostname or "").lower()
        title = self.title_of(url)
        base = {"title": title, "thumbnail": "", "uploader": host, "platform": "Direct link", "relay": False, "direct": True}
        try:
            if ext == "m3u8":
                code, _, body, final = safe_request("GET", url, max_bytes=1_500_000)
                if code != 200:
                    raise ExtractorError("This stream link is not reachable right now.")
                try:
                    info = hls.parse(body.decode("utf-8", "ignore"), final)
                except ValueError:
                    raise ExtractorError("This link is not a valid HLS playlist.")
                dur = int(info["duration"])
                fm = []
                if info["master"]:
                    fm.append(self._fmt("auto", "Auto (adaptive quality)", "Auto", final, 0, 0, dur, 0))
                    for i, v in enumerate(sorted(info["variants"], key=lambda x: (x["height"], x["bandwidth"]), reverse=True)):
                        q = f"{v['height']}p" if v["height"] else f"{v['bandwidth'] // 1000}kbps"
                        size = int(v["bandwidth"] * dur / 8) if dur else 0
                        fm.append(self._fmt(f"h{i}", f"{q} HLS", q, v["url"], v["height"], size, dur, v["fps"]))
                else:
                    fm.append(self._fmt("orig", "Original HLS stream" + (" (live)" if info["live"] else ""), "Original", final, 0, 0, dur, 0))
                return {**base, "duration": dur, "live": info["live"], "formats": fm}
            size = 0
            try:
                code, headers, _, _ = safe_request("HEAD", url, max_bytes=0)
                if code == 200:
                    size = int(headers.get("Content-Length") or 0)
            except Exception:
                size = 0
            audio = MIME.get(ext, "").startswith("audio")
            f = {"fid": "orig", "kind": "audio" if audio else "av", "label": f"Original {ext.upper()}", "quality": "Original", "ext": ext,
                 "mime": MIME.get(ext, "video/mp4"), "size": size, "size_approx": False, "url": url, "headers": {}, "audio_only": audio,
                 "video_only": False, "height": 0, "fps": 0, "vcodec": "", "acodec": "", "hls": False, "duration": 0, "tbr": 0}
            return {**base, "duration": 0, "live": False, "formats": [f]}
        except UnsafeURL:
            raise ExtractorError("This link can't be opened.")
        except ExtractorError:
            raise
        except Exception:
            raise ExtractorError("Could not read this link. Please check it and try again.")

    @staticmethod
    def _fmt(fid, label, quality, url, height, size, dur, fps):
        return {"fid": fid, "kind": "av", "label": label, "quality": quality, "ext": "mp4", "mime": "video/mp4", "size": size,
                "size_approx": bool(size), "url": url, "headers": {}, "audio_only": False, "video_only": False, "height": height,
                "fps": fps, "vcodec": "", "acodec": "", "hls": True, "duration": dur, "tbr": 0}
