"""Admin managed video library: powers the Videos tab and the Home tabs (Bollywood, Hollywood, Series, Live TV).

Only the admin decides what is in the library. Store links to content you own or are licensed to distribute.
The list endpoint never exposes the playable links – they are returned only when the user presses Play/Download."""
import posixpath
import threading
from urllib.parse import urlparse

from .extractors.direct import DIRECT_EXT
from .util import fmt_ist, now_ts, push_id

CATS = ("video", "bollywood", "hollywood", "series", "livetv")
CAT_LABEL = {"video": "Videos", "bollywood": "Bollywood", "hollywood": "Hollywood", "series": "Series", "livetv": "Live TV"}


def _url_ok(u):
    p = urlparse(u or "")
    return p.scheme in ("http", "https") and bool(p.netloc) and len(u) <= 2000


def parse_duration(v):
    """'1:35:00', '95:10' or plain minutes -> seconds."""
    s = str(v or "").strip().lower().replace("min", "").replace("m", "").strip()
    if not s:
        return 0
    try:
        if ":" in s:
            parts = [int(x) for x in s.split(":")]
            sec = 0
            for p in parts:
                sec = sec * 60 + p
            return max(0, sec)
        return max(0, int(float(s) * 60))
    except ValueError:
        return 0


def duration_text(sec):
    sec = int(sec or 0)
    if sec <= 0:
        return ""
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s" if sec < 600 else f"{m}m"


def source_type(url, embed=False):
    if embed:
        return "embed"
    ext = posixpath.splitext(urlparse(url).path.lower())[1].lstrip(".")
    if ext == "m3u8":
        return "hls"
    return "direct" if ext in DIRECT_EXT else "page"


def parse_sources(text):
    """'Label | URL | quality | embed' per line."""
    out = []
    for line in str(text or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and _url_ok(parts[1]):
            out.append({"label": parts[0][:40] or "Source", "url": parts[1], "quality": (parts[2] if len(parts) > 2 else "")[:12],
                        "embed": len(parts) > 3 and parts[3].lower() in ("embed", "iframe", "1", "yes", "true")})
    return out[:12]


class Videos:
    def __init__(self, ctx):
        self.ctx = ctx
        self._cache = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------ storage
    def _items(self):
        with self._lock:
            if self._cache is None:
                raw = self.ctx.db.get("content/videos") or {}
                self._cache = {k: {**v, "id": k} for k, v in raw.items() if isinstance(v, dict)}
            return self._cache

    def invalidate(self):
        with self._lock:
            self._cache = None

    def get(self, vid):
        return self._items().get(vid)

    def clean(self, data):
        d, err = {}, None
        title = str(data.get("title", "")).strip()[:150]
        link = str(data.get("video_link", "")).strip()
        if not title:
            return None, "Title is required"
        if not _url_ok(link):
            return None, "Video link must be a valid http(s) URL"
        for k in ("thumbnail_url", "preview_url"):
            v = str(data.get(k, "")).strip()
            if v and not _url_ok(v):
                return None, f"{k.replace('_', ' ').capitalize()} must be a valid http(s) URL"
            d[k] = v
        cat = str(data.get("category", "video")).strip().lower()
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = tags.replace("\n", ",").split(",")
        tags = [str(t).strip()[:30] for t in tags if str(t).strip()][:15]
        try:
            year = int(data.get("year") or 0)
            rating = round(float(data.get("rating") or 0), 1)
        except (TypeError, ValueError):
            return None, "Year and rating must be numbers"
        sec = parse_duration(data.get("duration"))
        d.update({"title": title, "description": str(data.get("description", "")).strip()[:5000], "video_link": link,
                  "category": cat if cat in CATS else "video", "tags": tags, "duration_sec": sec, "duration_text": duration_text(sec),
                  "year": year if 1900 <= year <= 2100 else 0, "rating": rating if 0 < rating <= 10 else 0,
                  "enabled": bool(data.get("enabled", True)),
                  "sources": parse_sources(data["sources"]) if isinstance(data.get("sources"), str) else
                  [s for s in (data.get("sources") or []) if isinstance(s, dict) and _url_ok(s.get("url"))][:12]})
        return d, err

    def create(self, data):
        d, err = self.clean(data)
        if err:
            return None, err
        now = now_ts()
        d.update({"created": now, "created_human": fmt_ist(now) + " IST", "updated_human": fmt_ist(now) + " IST",
                  "watch_count": 0, "download_count": 0})
        vid = push_id()
        self.ctx.db.put(f"content/videos/{vid}", d)
        self.invalidate()
        return {**d, "id": vid}, None

    def update(self, vid, data):
        cur = self.get(vid)
        if not cur:
            return None, "Video not found"
        merged = {**cur, **data}
        if "sources" not in data:
            merged["sources"] = cur.get("sources", [])
        if "duration" not in data:
            merged["duration"] = cur.get("duration_sec", 0) / 60
        d, err = self.clean(merged)
        if err:
            return None, err
        d["updated_human"] = fmt_ist(now_ts()) + " IST"
        self.ctx.db.patch(f"content/videos/{vid}", d)
        self.invalidate()
        return self.get(vid), None

    def delete(self, vid):
        self.ctx.db.delete(f"content/videos/{vid}")
        self.invalidate()

    # ------------------------------------------------------------ queries
    def query(self, q="", category="", page=1, per=20, enabled_only=False):
        items = sorted(self._items().values(), key=lambda x: x["id"], reverse=True)
        if enabled_only:
            items = [i for i in items if i.get("enabled", True)]
        if category:
            items = [i for i in items if i.get("category") == category]
        q = (q or "").strip().lower()
        if q:
            items = [i for i in items if q in i.get("title", "").lower() or q in i.get("description", "").lower()
                     or any(q in t.lower() for t in i.get("tags", []))]
        total = len(items)
        per = max(1, min(100, per))
        page = max(1, page)
        pages = max(1, -(-total // per))
        return {"items": items[(page - 1) * per: page * per], "total": total, "page": page, "pages": pages, "per": per}

    @staticmethod
    def public(i):
        return {"id": i["id"], "kind": i.get("category", "video"), "title": i.get("title", ""), "description": i.get("description", ""),
                "poster": i.get("thumbnail_url", ""), "preview": i.get("preview_url", ""), "duration_text": i.get("duration_text", ""),
                "duration_sec": i.get("duration_sec", 0), "tags": i.get("tags", []), "year": i.get("year", 0), "rating": i.get("rating", 0),
                "live": i.get("category") == "livetv", "created_human": i.get("created_human", ""),
                "sources_count": 1 + len(i.get("sources", []))}

    @staticmethod
    def sources(i):
        rows = [{"label": "Main", "url": i["video_link"], "quality": "", "embed": False}] + list(i.get("sources", []))
        seen, out = set(), []
        for r in rows:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            t = source_type(r["url"], r.get("embed", False))
            out.append({"label": r.get("label") or "Source", "url": r["url"], "quality": r.get("quality", ""), "type": t})
        # HLS first, then others – the first row is the recommended one
        out.sort(key=lambda r: {"hls": 0, "direct": 1, "page": 2, "embed": 3}[r["type"]])
        return out

    def count(self, vid, field):
        """field: watch_count | download_count"""
        item = self.get(vid)
        if not item:
            return
        self.ctx.db.increment(f"content/videos/{vid}/{field}", 1)
        item[field] = item.get(field, 0) + 1
