"""
Extractor contract. Every domain handler (YouTube, Terabox, your next custom
site, ...) implements this interface. See README.md -> "Adding a new custom
domain extractor" for the full walkthrough.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel


class FormatInfo(BaseModel):
    quality: str          # e.g. "1080p", "720p", "audio"
    ext: str               # e.g. "mp4", "m4a"
    filesize_bytes: int | None = None
    url: str                # direct (possibly short-lived) media URL
    type: str = "video"     # "video" | "audio" | "video_audio"


class VideoInfo(BaseModel):
    source: str              # which extractor handled this, e.g. "youtube"
    title: str
    thumbnail: str | None = None
    duration_seconds: int | None = None
    uploader: str | None = None
    formats: list[FormatInfo] = []


class ExtractionError(Exception):
    def __init__(self, message: str, code: str = "extraction_failed"):
        self.message = message
        self.code = code
        super().__init__(message)


class BaseExtractor(ABC):
    name: str = "base"

    @abstractmethod
    def can_handle(self, domain: str) -> bool:
        """domain is already lowercased and stripped of 'www.' -- see router.py"""
        raise NotImplementedError

    @abstractmethod
    async def extract(self, url: str) -> VideoInfo:
        raise NotImplementedError
