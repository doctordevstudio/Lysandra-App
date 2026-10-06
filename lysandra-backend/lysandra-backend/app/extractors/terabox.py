"""
Terabox / tera1024 / 1024tera extractor -- DUMMY implementation as requested.

This defines the correct shape of the response and where real logic plugs
in, but does not implement Terabox's actual share-link resolution (that
involves calling their internal share API, which changes often and is out
of scope here). Swap _dummy_lookup() for a real implementation when ready --
see README "Adding a new custom domain extractor".
"""
from app.extractors.base import BaseExtractor, FormatInfo, VideoInfo

TERABOX_DOMAINS = {"terabox.com", "tera1024.com", "1024tera.com", "teraboxapp.com"}


class TeraboxExtractor(BaseExtractor):
    name = "terabox"

    def can_handle(self, domain: str) -> bool:
        return domain in TERABOX_DOMAINS

    async def _dummy_lookup(self, url: str) -> VideoInfo:
        # TODO: replace with real Terabox share-link resolution:
        #   1. GET the share page, pull the `surl` / shareid / sign / timestamp
        #      params out of the page's embedded JSON.
        #   2. Call Terabox's list/download API with those params + your own
        #      session cookies, get back the direct CDN url(s).
        #   3. Map the response into FormatInfo entries below.
        return VideoInfo(
            source=self.name,
            title="[DUMMY] Terabox file",
            thumbnail=None,
            duration_seconds=None,
            uploader=None,
            formats=[
                FormatInfo(quality="original", ext="mp4", filesize_bytes=None,
                           url="https://example.com/replace-with-real-terabox-logic", type="video_audio"),
            ],
        )

    async def extract(self, url: str) -> VideoInfo:
        return await self._dummy_lookup(url)
