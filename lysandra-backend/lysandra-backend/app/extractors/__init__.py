"""
Extractor registry. Order matters: more specific extractors must be listed
before the generic fallback. See README "Adding a new custom domain
extractor" for how to plug in a new one.
"""
from app.extractors.base import BaseExtractor
from app.extractors.generic import GenericYtDlpExtractor
from app.extractors.terabox import TeraboxExtractor
from app.extractors.youtube import YoutubeExtractor

# Registration order = priority order. Add new custom extractors ABOVE
# GenericYtDlpExtractor() so they get first refusal on their domains.
REGISTRY: list[BaseExtractor] = [
    YoutubeExtractor(),
    TeraboxExtractor(),
    # <-- add new custom extractors here, e.g. MyNewSiteExtractor(),
    GenericYtDlpExtractor(),  # must stay last: it matches every domain
]


def get_extractor(domain: str) -> BaseExtractor:
    for extractor in REGISTRY:
        if extractor.can_handle(domain):
            return extractor
    # unreachable because GenericYtDlpExtractor.can_handle() always returns True
    raise RuntimeError("No extractor matched (this should never happen)")
