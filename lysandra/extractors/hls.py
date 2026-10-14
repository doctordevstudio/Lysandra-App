"""Tiny HLS playlist reader used by the direct extractor (master -> variants, media -> duration)."""
import re
from urllib.parse import urljoin

_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _attrs(line):
    return {k: v.strip('"') for k, v in _ATTR.findall(line.split(":", 1)[1])}


def parse(text, base_url):
    """Returns {"master": bool, "variants": [...], "duration": float, "live": bool}."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines or not lines[0].startswith("#EXTM3U"):
        raise ValueError("not an m3u8 playlist")
    variants, duration, live = [], 0.0, True
    audio_groups = {}
    pending = None
    for l in lines:
        if l.startswith("#EXT-X-STREAM-INF"):
            pending = _attrs(l)
        elif l.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in l:
            a = _attrs(l)
            audio_groups.setdefault(a.get("GROUP-ID", ""), []).append(a)
        elif l.startswith("#EXTINF"):
            try:
                duration += float(l.split(":", 1)[1].split(",")[0])
            except ValueError:
                pass
        elif l.startswith("#EXT-X-ENDLIST"):
            live = False
        elif not l.startswith("#") and pending is not None:
            res = pending.get("RESOLUTION", "")
            h = int(res.split("x")[1]) if "x" in res else 0
            variants.append({"url": urljoin(base_url, l), "bandwidth": int(pending.get("BANDWIDTH", "0") or 0), "height": h,
                             "fps": int(float(pending["FRAME-RATE"])) if pending.get("FRAME-RATE") else 0,
                             "codecs": pending.get("CODECS", ""), "audio_group": pending.get("AUDIO", "")})
            pending = None
    return {"master": bool(variants), "variants": variants, "duration": duration, "live": live and not variants}
