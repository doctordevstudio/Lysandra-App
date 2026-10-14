"""Endpoints used by the Android app. Every call is signed + encrypted (see security.py)."""
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from urllib.parse import urlparse

import requests
from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from .defaults import APP_SECTIONS
from .extractors.base import ExtractorError, host_of
from .security import ApiError
from .videos import CATS
from .util import clamp, now_ts, sha256_hex, today_str, to_int

AD_PLATFORMS = {"startio"}
AD_TYPES = {"interstitial", "rewarded", "banner", "native"}
AD_ACTIONS = {"fetch", "watch", "download", "status", "home", "history", "downloads", "apps", "player", "other"}


class FetchCache:
    def __init__(self, ttl=1200, cap=800):
        self.ttl, self.cap = ttl, cap
        self.d = {}
        self.lock = threading.Lock()

    def put(self, key, val):
        with self.lock:
            now = time.time()
            if len(self.d) >= self.cap:
                for k in [k for k, v in self.d.items() if v[0] < now][:200] or list(self.d)[:100]:
                    self.d.pop(k, None)
            self.d[key] = (now + self.ttl, val)

    def get(self, key):
        with self.lock:
            v = self.d.get(key)
            if v and v[0] > time.time():
                return v[1]
            self.d.pop(key, None)


def normalize_url(raw):
    u = (raw or "").strip()
    if not u or len(u) > 2000 or re.search(r"\s", u):
        raise ApiError("bad_url", "Please paste a valid video link")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        raise ApiError("bad_url", "Please paste a valid video link")
    host = p.hostname.lower()
    # SSRF protection: never let the server be pointed at internal addresses
    from .security import IPIntel
    if IPIntel.is_private(host) or host in ("localhost",) or host.endswith((".local", ".internal")):
        raise ApiError("bad_url", "This link can't be downloaded")
    return u


def init(ctx):
    bp = Blueprint("app_api", __name__, url_prefix="/api/v1")
    guard = ctx.guard
    cache = FetchCache()
    relay_key = hmac.new(ctx.guard.crypto.sig_key if ctx.guard.crypto else b"x", b"relay", hashlib.sha256).digest()
    ctx.fetch_cache = cache

    def ad_config():
        a = ctx.cfg.get("ads")
        return {k: a.get(k) for k in ("enabled", "startio_app_id", "banner_enabled", "native_enabled",
                                      "interstitial_enabled", "rewarded_enabled", "interstitial_cooldown_sec")}

    def premium_state(dev):
        return ctx.payments.premium_status(dev)

    def quota(dev, prem):
        """Server-side view of what this device may still do today (free tier or its plan's limits)."""
        date = today_str()
        used_d = to_int(ctx.db.get(f"quota/{date}/{dev}/d"), 0)
        used_w = to_int(ctx.db.get(f"quota/{date}/{dev}/w"), 0)
        lim = ctx.cfg.cfg["limits"]
        if prem["active"]:
            plan = ctx.payments.plan(prem.get("plan_id", "")) or {}
            dl, wl = to_int(plan.get("downloads_per_day"), 0, 0), to_int(plan.get("watch_per_day"), 0, 0)
            dl_unl, w_unl, name = dl == 0, wl == 0, prem["plan"] or "Premium"
        else:
            dl, wl = to_int(lim.get("free_daily_downloads"), 2, 0, 1000), to_int(lim.get("free_daily_watch"), 5, 0, 1000)
            ov = ctx.users.override(dev)             # admin can give one user a different daily limit
            dl, wl = to_int(ov.get("dl"), dl, 0, 10000) if "dl" in ov else dl, to_int(ov.get("w"), wl, 0, 10000) if "w" in ov else wl
            dl_unl = w_unl = False
            name = "Free"
        out = {"plan": name, "free": not prem["active"],
               "dl_limit": dl, "dl_used": used_d, "dl_unlimited": dl_unl, "dl_remaining": 10**6 if dl_unl else max(0, dl - used_d),
               "w_limit": wl, "w_used": used_w, "w_unlimited": w_unl, "w_remaining": 10**6 if w_unl else max(0, wl - used_w)}
        out["can_download"] = dl_unl or out["dl_remaining"] > 0
        out["can_watch"] = w_unl or out["w_remaining"] > 0
        return out

    # ---------------------------------------------------------------- boot
    @bp.route("/boot", methods=["POST"])
    @guard.secure(limit=20, window=60)
    def boot(d):
        raw, ip = g.raw_dev, g.ip
        cfg = ctx.cfg.cfg
        info = d.get("info") or {}
        ver = to_int(d.get("ver"), 0)
        sec = cfg["security"]
        # cloned / parallel / dual-space copies of the app: refuse (and the app itself crashes silently)
        clone = [str(x)[:20] for x in (d.get("clone") or [])][:8]
        if clone and sec.get("block_clones", True):
            ctx.stats.bump_bg("clone_blocked", raw, ip, {"env": clone})
            raise ApiError("env", "This copy of the app is not supported. Please install the original Lysandra.")
        drm = str(d.get("drm") or "").lower()
        drm = drm if len(drm) >= 16 and all(c in "0123456789abcdef" for c in drm) else ""
        dev = ctx.link_identity(raw, drm)      # clones of the same phone resolve to ONE account (premium + quota)
        g.dev = dev
        # environment policy – the app also checks locally, this is the server-side enforcement
        env = {"vpn": bool(d.get("vpn")), "proxy": bool(d.get("proxy")), "emu": bool(info.get("emulator")),
               "rooted": bool(info.get("rooted"))}
        if (sec["block_vpn"] and env["vpn"]) or (sec["block_proxy"] and env["proxy"]) \
                or (sec["block_emulator"] and env["emu"]) or (sec.get("block_rooted") and env["rooted"]):
            ctx.stats.bump_bg("env_blocked", raw, ip, {"env": [k for k, v in env.items() if v]})
            raise ApiError("env", "Please turn off VPN / proxy and use a real device.")
        fl = ctx.ip_flags(ip)
        if fl["blocked"]:
            ctx.stats.bump_bg("env_blocked", raw, ip, {"env": [fl["reason"]]})
            raise ApiError("env", "Your network is not allowed. Please turn off VPN / proxy and try again.")
        ctx.bg(ctx.users.register_open, raw, ip, info, ver)
        app = cfg["app"]
        maint = cfg["maintenance"]
        if maint.get("enabled"):
            ctx.stats.bump_bg("maint_open", raw, ip)
        prem = premium_state(dev)
        q = quota(dev, prem)
        out = {"ok": True, "maintenance": {"on": bool(maint.get("enabled")), "html": maint.get("message", "")},
               "update": {"required": ver < to_int(app.get("min_version_code"), 1),
                          "available": ver < to_int(app.get("version_code"), 1),
                          "name": app.get("latest_version_name"), "url": app.get("update_url"),
                          "message": app.get("update_message")},
               "app": {k: app.get(k) for k in ("name", "tagline", "supported_platforms_text", "unreachable_message")},
               "support": cfg["support"], "developer": cfg["developer"], "share": cfg["share"],
               "ads": ad_config(), "premium": {**prem, "plans": cfg["premium"]["plans"],
                                              "features": cfg["premium"]["features"]},
               "quota": q, "fetch_per_minute": cfg["limits"].get("fetch_per_minute", 12)}
        return out

    # ---------------------------------------------------------------- home (dialogs, carousel, apps)
    @bp.route("/home", methods=["POST"])
    @guard.secure(limit=30, window=60)
    def home(d):
        def pick(items, keys):
            return [{k: i.get(k) for k in keys} for i in items]
        return {"ok": True,
                "dialogs": pick(ctx.content.enabled("dialogs"), ("id", "title", "message", "image_url", "url", "sort")),
                "carousel": pick(ctx.content.enabled("carousel"), ("id", "title", "image_url", "url", "sort")),
                "apps": pick(ctx.content.enabled("apps"), ("id", "name", "url", "icon_url", "domain", "highlight", "sort")),
                "legal": {"terms": ctx.cfg.get("legal", "terms_html"), "privacy": ctx.cfg.get("legal", "privacy_html"),
                          "dmca": ctx.cfg.get("legal", "dmca_html")}}

    @bp.route("/legal", methods=["POST"])
    @guard.secure(limit=20, window=60)
    def legal(d):
        return {"ok": True, "terms": ctx.cfg.get("legal", "terms_html"), "privacy": ctx.cfg.get("legal", "privacy_html"),
                "dmca": ctx.cfg.get("legal", "dmca_html")}

    # ---------------------------------------------------------------- video library (Videos tab + Home tabs)
    @bp.route("/catalog", methods=["POST"])
    @guard.secure(limit=90, window=60)
    def catalog(d):
        kind = str(d.get("kind", "video"))
        if kind not in CATS:
            raise ApiError("bad", "bad request")
        limit = to_int(d.get("limit"), 20, 1, 100)
        res = ctx.videos.query(clamp(d.get("q"), 60), kind, to_int(d.get("page"), 1, 1, 10000), limit, enabled_only=True)
        return {"ok": True, "items": [ctx.videos.public(i) for i in res["items"]], "page": res["page"], "pages": res["pages"], "total": res["total"]}

    @bp.route("/video", methods=["POST"])
    @guard.secure(limit=60, window=60)
    def video(d):
        item = ctx.videos.get(clamp(d.get("id"), 40))
        if not item or not item.get("enabled", True):
            raise ApiError("not_found", "This title is no longer available.")
        return {"ok": True, "item": ctx.videos.public(item), "sources": ctx.videos.sources(item)}

    # ---------------------------------------------------------------- engagement
    @bp.route("/engage", methods=["POST"])
    @guard.secure(limit=60, window=60)
    def engage(d):
        kind = d.get("kind")
        if kind not in ("dialogs", "carousel", "notifications"):
            raise ApiError("bad", "bad request")
        ok = ctx.content.engage(kind, clamp(d.get("id"), 40), g.dev, g.ip, d.get("action"))
        return {"ok": True, "counted": ok}

    @bp.route("/notifications", methods=["POST"])
    @guard.secure(limit=40, window=60)
    def notifications(d):
        per = 20
        items = ctx.content.enabled("notifications")
        after = clamp(d.get("after"), 40)           # newest id the user has already seen
        unread = len([i for i in items if i["id"] > after]) if after else len(items)
        cursor = clamp(d.get("cursor"), 40)
        rows = [i for i in items if not cursor or i["id"] < cursor]
        page = rows[:per]
        return {"ok": True, "unread": unread, "newest": items[0]["id"] if items else "",
                "items": [{"id": i["id"], "title": i.get("title", ""), "message": i.get("message", ""),
                           "image_url": i.get("image_url", ""), "url": i.get("url", ""),
                           "ts": to_int(i["id"][:13]) // 1000} for i in page],
                "next": page[-1]["id"] if len(rows) > per else ""}

    # ---------------------------------------------------------------- ads tracking
    @bp.route("/track", methods=["POST"])
    @guard.secure(limit=120, window=60)
    def track(d):
        t, p, a = d.get("type"), d.get("platform", "startio"), d.get("action", "other")
        if t not in AD_TYPES or p not in AD_PLATFORMS:
            raise ApiError("bad", "bad request")
        a = a if a in AD_ACTIONS else "other"
        ctx.stats.bump_bg(f"ad_{t}_{p}_{a}", g.dev, g.ip, keep_event=t in ("interstitial", "rewarded"))
        if t in ("interstitial", "rewarded"):
            ctx.db.increment(f"users/{g.dev}/ad_{t}", 1) if ctx.settings.testing else \
                ctx.bg(ctx.db.increment, f"users/{g.dev}/ad_{t}", 1)
        return {"ok": True}

    # ---------------------------------------------------------------- fetch
    def public_format(f):
        return {"fid": f["fid"], "kind": f["kind"], "label": f["label"], "quality": f["quality"], "ext": f["ext"], "size": f["size"],
                "size_approx": f.get("size_approx", False), "height": f.get("height", 0), "fps": f.get("fps", 0),
                "vcodec": f.get("vcodec", ""), "acodec": f.get("acodec", ""), "hls": f.get("hls", False)}

    @bp.route("/fetch", methods=["POST"])
    @guard.secure(limit=40, window=60)
    def fetch(d):
        dev, ip = g.dev, g.ip
        url = normalize_url(d.get("url"))
        if sha256_hex(d.get("url", "").strip()) != d.get("h") and sha256_hex(url) != d.get("h"):
            raise ApiError("integrity", "Request integrity check failed")
        fpm = to_int(ctx.cfg.get("limits", "fetch_per_minute"), 12, 1, 120)
        if not ctx.limiter.allow(f"fetch:{dev}", fpm, 60):
            raise ApiError("rate", "You are fetching too fast. Please wait a moment.")
        if ctx.cfg.get("maintenance", "enabled"):
            raise ApiError("maintenance", "Lysandra is under maintenance")
        fl = ctx.ip_flags(ip)
        if fl["blocked"]:
            raise ApiError("env", "Your network is not allowed. Turn off VPN / proxy and try again.")
        host = host_of(url)
        rec = ctx.content.match_blocked(host)
        if rec:
            ctx.stats.bump_bg("blocked_hit", dev, ip, {"domain": rec["domain"], "url_host": host})
            raise ApiError("blocked", "blocked", html=rec.get("message", ""), domain=rec["domain"])
        vid = clamp(d.get("vid"), 40)
        vid = vid if vid and ctx.videos.get(vid) else ""
        ex = ctx.extractors.resolve(host, url)
        ck = "url:" + sha256_hex(url)
        res = cache.get(ck)
        try:
            if res is None:
                res = ex.extract(url)
                cache.put(ck, res)
        except ExtractorError as e:
            ctx.stats.bump_bg("fetch_fail", dev, ip, {"host": host, "why": str(e)[:80]})
            ctx.bg(ctx.db.increment, f"users/{dev}/fetch_fail", 1)
            raise ApiError("fetch_failed", str(e))
        fetch_id = secrets.token_urlsafe(12)
        cache.put("f:" + fetch_id, {"dev": dev, "url": url, "res": res, "host": host, "vid": vid})
        ctx.stats.bump_bg("fetch_ok", dev, ip, {"host": host, "ex": ex.name})
        ctx.bg(ctx.db.increment, f"users/{dev}/fetch_ok", 1)
        prem = premium_state(dev)
        return {"ok": True, "fetch_id": fetch_id, "title": res["title"], "thumbnail": res["thumbnail"],
                "duration": res["duration"], "platform": res["platform"], "uploader": res.get("uploader", ""),
                "direct": bool(res.get("direct")), "live": bool(res.get("live")), "upload_date": res.get("upload_date", ""),
                "views": res.get("views", 0), "formats": [public_format(f) for f in res["formats"]],
                "quota": quota(dev, prem), "premium": prem["active"]}

    # ---------------------------------------------------------------- authorize (enforces daily limit)
    def make_download(fmt, entry, dev):
        """Returns {"url","headers"} for one concrete file. IP-locked sites are streamed through the relay."""
        if (entry["res"].get("relay") or fmt.get("relay")) and not fmt.get("hls"):
            exp = now_ts() + 3600
            tok_id = secrets.token_urlsafe(10)
            cache.put("r:" + tok_id, {"url": fmt["url"], "headers": fmt.get("headers") or {}, "proxy": entry["res"].get("proxy"),
                                      "dev": dev, "mime": fmt["mime"]})
            sig = hmac.new(relay_key, f"{tok_id}.{exp}.{dev}".encode(), hashlib.sha256).hexdigest()[:32]
            return {"url": f"{ctx.settings.public_url or request.host_url.rstrip('/')}/api/v1/relay/{tok_id}.{exp}.{sig}", "headers": {}}
        return {"url": fmt["url"], "headers": {k: v for k, v in (fmt.get("headers") or {}).items()
                                               if k.lower() in ("user-agent", "referer", "cookie", "origin")}}

    @bp.route("/authorize", methods=["POST"])
    @guard.secure(limit=40, window=60)
    def authorize(d):
        dev = g.dev
        entry = cache.get("f:" + clamp(d.get("fetch_id"), 40))
        if not entry or entry["dev"] != dev:
            raise ApiError("expired", "This fetch has expired. Please fetch the link again.")
        formats = entry["res"]["formats"]
        fmt = next((f for f in formats if f["fid"] == d.get("fid")), None)
        if not fmt:
            raise ApiError("bad", "Invalid quality selected")
        prem = premium_state(dev)
        watching = bool(d.get("watch"))          # "watch" = stream in the player, has its own daily limit
        if watching and fmt["kind"] == "merge":
            raise ApiError("bad", "Pick a ready-made quality to watch")
        kind = "w" if watching else "d"
        with ctx.quota_lock:                     # check + consume atomically (no race between two requests)
            q = quota(dev, prem)
            if not q["can_watch" if watching else "can_download"]:
                raise ApiError("limit", "Daily limit reached", kind="watch" if watching else "download", quota=q)
            ctx.db.put(f"quota/{today_str()}/{dev}/{kind}", q["w_used" if watching else "dl_used"] + 1)
        vid = entry.get("vid")
        if vid and ctx.videos.get(vid):
            cat = ctx.videos.get(vid).get("category", "video")
            ctx.stats.bump_bg("vwatch" if watching else "vdl", dev, g.ip, {"vid": vid, "cat": cat}, keep_event=False)
            ctx.stats.bump_bg(("vwatch_" if watching else "vdl_") + cat, dev, g.ip, keep_event=False)
            ctx.videos.count(vid, "watch_count" if watching else "download_count")
        ctx.stats.bump_bg("watch_authorized" if watching else "download_authorized", dev, g.ip,
                          {"host": entry["host"]}, keep_event=False)
        title = re.sub(r"[^\w\- .()\[\]]+", "", entry["res"]["title"], flags=re.U).strip()[:80] or "video"
        q = quota(dev, prem)
        base = {"ok": True, "mime": fmt["mime"], "size": fmt["size"], "quota": q, "hls": bool(fmt.get("hls")),
                "filename": f"{title}.{fmt['ext']}", "merge": fmt["kind"] == "merge"}
        if fmt["kind"] == "merge":
            parts = []
            for role, pid in zip(("video", "audio"), fmt["parts"]):
                pf = next((f for f in formats if f["fid"] == pid), None)
                if not pf:
                    raise ApiError("bad", "Invalid quality selected")
                parts.append({"role": role, "ext": pf["ext"], "size": pf["size"], **make_download(pf, entry, dev)})
            return {**base, "parts": parts, "url": "", "headers": {}}
        return {**base, **make_download(fmt, entry, dev)}

    @bp.route("/relay/<token>", methods=["GET"])
    def relay(token):
        """Streams IP-locked media (YouTube) through the configured proxy. Token is short-lived and device-bound."""
        try:
            tok_id, exp, sig = token.split(".")
            entry = cache.get("r:" + tok_id)
            if not entry or int(exp) < now_ts():
                raise ValueError
            want = hmac.new(relay_key, f"{tok_id}.{exp}.{entry['dev']}".encode(), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(want, sig):
                raise ValueError
        except Exception:
            return Response("Gone", status=410)
        if not ctx.limiter.allow(f"relay:{request.remote_addr}", 120, 60):
            return Response("Slow down", status=429)
        hdrs = {k: v for k, v in entry["headers"].items() if k.lower() in ("user-agent", "referer", "origin")}
        if request.headers.get("Range"):
            hdrs["Range"] = request.headers["Range"]
        proxies = {"http": entry["proxy"], "https": entry["proxy"]} if entry.get("proxy") else None
        try:
            up = requests.get(entry["url"], headers=hdrs, stream=True, timeout=(8, 30), proxies=proxies)
        except requests.RequestException:
            return Response("Upstream error", status=502)
        out = {"Content-Type": entry["mime"], "Accept-Ranges": "bytes", "Cache-Control": "no-store"}
        for h in ("Content-Length", "Content-Range"):
            if h in up.headers:
                out[h] = up.headers[h]
        return Response(stream_with_context(up.iter_content(64 * 1024)), status=up.status_code, headers=out)

    # ---------------------------------------------------------------- premium + payments
    @bp.route("/premium", methods=["POST"])
    @guard.secure(limit=40, window=60)
    def premium(d):
        prem = premium_state(g.dev)
        return {"ok": True, "premium": {**prem, "plans": ctx.cfg.get("premium", "plans"),
                                        "features": ctx.cfg.get("premium", "features")},
                "quota": quota(g.dev, prem)}

    @bp.route("/pay/create", methods=["POST"])
    @guard.secure(limit=10, window=60)
    def pay_create(d):
        fl = ctx.ip_flags(g.ip)
        if fl["blocked"]:
            raise ApiError("env", "Turn off VPN / proxy to make a payment.")
        txn = ctx.payments.create_txn(g.dev, g.ip, clamp(d.get("plan"), 20))
        return {"ok": True, "txn": txn, "server_time": now_ts()}

    @bp.route("/pay/submit", methods=["POST"])
    @guard.secure(limit=8, window=60)
    def pay_submit(d):
        try:
            img = base64.b64decode(d.get("image", ""), validate=True)
        except Exception:
            raise ApiError("bad_image", "Invalid screenshot")
        txn = ctx.payments.submit_proof(g.dev, clamp(d.get("txn"), 20).upper(), d.get("utr", ""), img)
        return {"ok": True, "txn": txn}

    @bp.route("/pay/status", methods=["POST"])
    @guard.secure(limit=60, window=60)
    def pay_status(d):
        res = ctx.payments.status(g.dev, clamp(d.get("txn"), 20).upper())
        return {"ok": True, **res}

    @bp.route("/pay/history", methods=["POST"])
    @guard.secure(limit=20, window=60)
    def pay_history(d):
        return {"ok": True, "items": [ctx.payments.public_txn(t) for t in ctx.payments.my_txns(g.dev, 10)]}

    app_bp = bp
    return app_bp
