"""
YouTube extractor. Uses yt-dlp with proxy rotation (YouTube rate-limits /
blocks a lot of datacenter IPs, hence the proxy pool from config).
"""
import asyncio
import random

import yt_dlp

from app.extractors.base import BaseExtractor, ExtractionError, FormatInfo, VideoInfo
from app.firebase_client import config_cache

YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"}


class YoutubeExtractor(BaseExtractor):
    name = "youtube"

    def can_handle(self, domain: str) -> bool:
        return domain in YOUTUBE_DOMAINS or domain.endswith(".youtube.com")

    def _pick_proxy(self) -> str | None:
        proxies = config_cache.get("youtube_proxies") or []
        return random.choice(proxies) if proxies else None

    def _run_ytdlp(self, url: str) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 20,
        }
        proxy = self._pick_proxy()
        if proxy:
            opts["proxy"] = proxy
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    async def extract(self, url: str) -> VideoInfo:
        try:
            info = await asyncio.get_event_loop().run_in_executor(None, self._run_ytdlp, url)
        except Exception as e:
            raise ExtractionError(f"YouTube extraction failed: {e}")

        formats: list[FormatInfo] = []
        for f in info.get("formats", []):
            if not f.get("url"):
                continue
            height = f.get("height")
            quality = f"{height}p" if height else (f.get("format_note") or f.get("format_id", "unknown"))
            has_video = f.get("vcodec") not in (None, "none")
            has_audio = f.get("acodec") not in (None, "none")
            formats.append(FormatInfo(
                quality=quality,
                ext=f.get("ext", "mp4"),
                filesize_bytes=f.get("filesize") or f.get("filesize_approx"),
                url=f["url"],
                type="video_audio" if (has_video and has_audio) else ("video" if has_video else "audio"),
            ))

        return VideoInfo(
            source=self.name,
            title=info.get("title", "Untitled"),
            thumbnail=info.get("thumbnail"),
            duration_seconds=info.get("duration"),
            uploader=info.get("uploader"),
            formats=formats,
        )
