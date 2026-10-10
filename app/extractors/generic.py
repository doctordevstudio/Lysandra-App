"""
Fallback extractor: plain yt-dlp, no proxy, works for the 1000+ sites yt-dlp
natively supports out of the box. Always matches last in the registry.
"""
import asyncio

import yt_dlp

from app.extractors.base import BaseExtractor, ExtractionError, FormatInfo, VideoInfo


class GenericYtDlpExtractor(BaseExtractor):
    name = "generic"

    def can_handle(self, domain: str) -> bool:
        return True  # fallback -- always matches

    def _run_ytdlp(self, url: str) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 20,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    async def extract(self, url: str) -> VideoInfo:
        try:
            info = await asyncio.get_event_loop().run_in_executor(None, self._run_ytdlp, url)
        except Exception as e:
            raise ExtractionError(f"Could not extract media from this URL: {e}")

        formats: list[FormatInfo] = []
        for f in info.get("formats", info.get("entries", []) and [] or []):
            if not f.get("url"):
                continue
            height = f.get("height")
            quality = f"{height}p" if height else (f.get("format_note") or f.get("format_id", "unknown"))
            formats.append(FormatInfo(
                quality=quality,
                ext=f.get("ext", "mp4"),
                filesize_bytes=f.get("filesize") or f.get("filesize_approx"),
                url=f["url"],
                type="video_audio",
            ))

        # Some sites (direct media links, etc.) have no 'formats' list, just a top-level url
        if not formats and info.get("url"):
            formats.append(FormatInfo(
                quality=info.get("format_note", "default"),
                ext=info.get("ext", "mp4"),
                filesize_bytes=info.get("filesize"),
                url=info["url"],
                type="video_audio",
            ))

        return VideoInfo(
            source=self.name,
            title=info.get("title", "Untitled"),
            thumbnail=info.get("thumbnail"),
            duration_seconds=info.get("duration"),
            uploader=info.get("uploader"),
            formats=formats,
        )
