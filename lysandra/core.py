"""Application context + data services (stats, users, content)."""
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from .config import Settings
from .configstore import ConfigStore
from .db import MemoryDB, RTDB
from .security import AdminAuth, AppGuard, IPIntel, RateLimiter, client_ip as _client_ip, ip_in_list
from .util import (date_range, now_ts, push_id, safe_key, today_str, ts_to_date)
from .videos import Videos


class Context:
    def __init__(self, settings: Settings, db=None):
        self.settings = settings
        self.log = logging.getLogger("lysandra")
        if db is None:
            db = RTDB(settings.firebase_db_url, settings.firebase_db_secret) if settings.firebase_db_url else MemoryDB()
        self.db = db
        self.cfg = ConfigStore(db)
        self.limiter = RateLimiter()
        self.ipintel = IPIntel(settings.ipintel_provider)
        self.metrics = defaultdict(int)
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="lys-bg")
        self.quota_lock = threading.Lock()
        self._bans = None
        self._bans_lock = threading.Lock()
        self.guard = AppGuard(self)
        self.admin = AdminAuth(self)
        self.stats = Stats(self)
        self.users = Users(self)
        self.content = Content(self)
        self.videos = Videos(self)
        self._canon = {}
        self._id_lock = threading.Lock()
        self.payments = None   # set by app factory
        self.telegram = None
        self.extractors = None

    # --- helpers
    def client_ip(self):
        return _client_ip(self.settings)

    def bg(self, fn, *a, **kw):
        """Run fire-and-forget work off the request thread (synchronous in tests)."""
        def run():
            try:
                fn(*a, **kw)
            except Exception:
                self.log.exception("background job failed")
        if self.settings.testing:
            run()
        else:
            self.pool.submit(run)

    def admin_log(self, action, detail=""):
        from flask import g
        a = getattr(g, "admin", None) or {}
        self.db.put(f"admin_logs/{today_str()}/{push_id()}",
                    {"ts": now_ts(), "user": a.get("user", "system"), "ip": a.get("ip", ""),
                     "action": action, "detail": str(detail)[:400]})

    # --- bans
    def _load_bans(self):
        with self._bans_lock:
            if self._bans is None:
                self._bans = set((self.db.get("bans") or {}).keys())
        return self._bans

    def is_banned(self, dev):
        return dev in self._load_bans()

    def set_ban(self, dev, banned, reason=""):
        bans = self._load_bans()
        if banned:
            self.db.put(f"bans/{dev}", {"ts": now_ts(), "reason": reason[:200]})
            bans.add(dev)
        else:
            self.db.delete(f"bans/{dev}")
            bans.discard(dev)

    # --- clone protection: devices that share the same hardware identity share one account
    def canon(self, dev):
        c = self._canon.get(dev)
        if c:
            return c
        c = self.db.get(f"idmap/by_dev/{dev}")
        if c:
            self._canon[dev] = c
        return c or dev

    def link_identity(self, dev, drm):
        """Called at app start. `drm` is a hash of the device's MediaDrm id (same for every clone of the app on one phone)."""
        with self._id_lock:
            c = self.db.get(f"idmap/by_dev/{dev}")
            if not c:
                owner = self.db.get(f"idmap/by_drm/{drm}") if drm else None
                c = owner or dev
                self.db.put(f"idmap/by_dev/{dev}", c)
            if drm and self.db.get(f"idmap/by_drm/{drm}") is None:
                self.db.put(f"idmap/by_drm/{drm}", c)
            self._canon[dev] = c
            return c

    def linked_devices(self, canon):
        return sorted(d for d, c in (self.db.get("idmap/by_dev") or {}).items() if c == canon and d != canon)

    # --- network policy (shared by app endpoints)
    def ip_flags(self, ip):
        sec = self.cfg.get("security")
        flags = {"blocked": False, "reason": ""}
        if ip_in_list(ip, sec.get("blocked_cidrs", [])):
            return {"blocked": True, "reason": "network"}
        info = self.ipintel.lookup(ip)
        if sec.get("block_datacenter") and info["datacenter"]:
            return {"blocked": True, "reason": "datacenter"}
        if sec.get("block_vpn") and (info["vpn"] or info["tor"]):
            return {"blocked": True, "reason": "vpn"}
        if sec.get("block_proxy") and info["proxy"]:
            return {"blocked": True, "reason": "proxy"}
        return flags


# ====================================================================== stats
class Stats:
    def __init__(self, ctx):
        self.ctx = ctx

    def bump(self, kind, dev=None, ip="", extra=None, n=1, keep_event=True):
        db, date = self.ctx.db, today_str()
        db.increment(f"stats/daily/{date}/{kind}", n)
        db.increment(f"stats/total/{kind}", n)
        if dev and keep_event:
            ev = {"dev": dev, "ts": now_ts(), "ip": ip}
            if extra:
                ev.update(extra)
            db.put(f"ev/{kind}/{date}/{push_id()}", ev)

    def bump_bg(self, *a, **kw):
        self.ctx.bg(self.bump, *a, **kw)

    def mark_active(self, dev):
        date = today_str()
        path = f"ev/active/{date}/{dev}"
        if self.ctx.db.get(path) is None:
            self.ctx.db.put(path, now_ts())
            self.ctx.db.increment(f"stats/daily/{date}/active", 1)
            return True
        return False

    def daily(self, d_from, d_to):
        a, b = min(d_from, d_to), max(d_from, d_to)
        return self.ctx.db.get("stats/daily", order_by_key=True, start_at=a, end_at=b) or {}

    @staticmethod
    def _sum(days, dates):
        out = defaultdict(int)
        for d in dates:
            for k, v in (days.get(d) or {}).items():
                if isinstance(v, (int, float)):
                    out[k] += v
        return dict(out)

    def summary(self, d_from, d_to):
        today, yest = today_str(), today_str(-1)
        lo, hi = min(d_from, d_to, yest), max(d_from, d_to, today)
        days = self.daily(lo, hi)
        total = self.ctx.db.get("stats/total") or {}
        rng = date_range(d_from, d_to)
        ya = set((self.ctx.db.get(f"ev/active/{yest}", shallow=True) or {}).keys())
        ta = set((self.ctx.db.get(f"ev/active/{today}", shallow=True) or {}).keys())
        return {
            "today": self._sum(days, [today]), "yesterday": self._sum(days, [yest]),
            "all": total, "range": self._sum(days, rng),
            "range_days": {d: days.get(d, {}) for d in rng[-60:]},
            "yesterday_active_today": len(ya & ta),
            "dates": {"today": today, "yesterday": yest, "from": d_from, "to": d_to},
        }

    def list_events(self, kind, d_from, d_to, cursor="", limit=25):
        """Paginated events across a date range. cursor is "date|id" of the last item returned."""
        dates = date_range(d_from, d_to)
        items, c_date, c_id = [], "", ""
        if cursor and "|" in cursor:
            c_date, c_id = cursor.split("|", 1)
        for d in dates:
            if c_date and d < c_date:
                continue
            start = c_id + "\x00" if (c_date == d and c_id) else None
            rows = self.ctx.db.get(f"ev/{kind}/{d}", order_by_key=True, start_at=start,
                                   limit_first=limit - len(items) + 1) or {}
            for k in sorted(rows):
                if c_date == d and c_id and k <= c_id:
                    continue
                v = rows[k]
                items.append({"id": k, "date": d, **(v if isinstance(v, dict) else {"v": v})})
                if len(items) > limit:
                    break
            if len(items) > limit:
                break
        more = len(items) > limit
        items = items[:limit]
        nxt = f"{items[-1]['date']}|{items[-1]['id']}" if more and items else ""
        return {"items": items, "next": nxt}


# ====================================================================== users
class Users:
    def __init__(self, ctx):
        self.ctx = ctx
        self._top = (0, [])
        self._ov, self._all_at, self._all_cache = {}, 0, {}

    def register_open(self, dev, ip, info, ver):
        db = self.ctx.db
        now = now_ts()
        existing = db.get(f"users/{dev}")
        base = {"last_seen": now, "ip": ip, "ver": ver,
                "model": info.get("model", "")[:60], "brand": info.get("brand", "")[:40],
                "android": info.get("android", "")[:20], "sdk": info.get("sdk", 0),
                "lang": info.get("lang", "")[:10], "rooted": bool(info.get("rooted"))}
        is_new = existing is None
        if is_new:
            base.update({"first_seen": now, "id": dev})
            db.put(f"users/{dev}", base)
            self.ctx.stats.bump("new_user", dev, ip)
        else:
            db.patch(f"users/{dev}", base)
        db.increment(f"users/{dev}/opens", 1)
        db.put(f"user_logs/{dev}/{push_id()}", {"ts": now, "ip": ip, "ver": ver, "model": base["model"],
                                              "android": base["android"], "rooted": base["rooted"]})
        self.ctx.stats.mark_active(dev)
        return is_new

    def override(self, dev):
        """Per-user daily limit override set by the admin: {"dl": int|None, "w": int|None}."""
        hit = self._ov.get(dev)
        if hit and hit[0] > time.time():
            return hit[1]
        ov = self.ctx.db.get(f"users/{dev}/override") or {}
        self._ov[dev] = (time.time() + 30, ov)
        return ov

    def _all(self):
        if time.time() - self._all_at > 30:
            self._all_cache = self.ctx.db.get("users") or {}
            self._all_at = time.time()
        return self._all_cache

    def search(self, q, limit=25):
        q = (q or "").strip().lower()
        if len(q) < 3:
            return []
        out = []
        direct = self.ctx.db.get(f"users/{q}") if len(q) >= 16 and q.isalnum() else None
        if isinstance(direct, dict):
            out.append((q, direct))
        for d, u in self._all().items():
            if len(out) >= limit:
                break
            if isinstance(u, dict) and d != q and (q in d or q in str(u.get("ip", "")).lower() or q in str(u.get("model", "")).lower()
                                                   or q in str(u.get("brand", "")).lower() or q in str(u.get("notes", "")).lower()):
                out.append((d, u))
        return [{"id": d, "ip": u.get("ip", ""), "model": u.get("model", ""), "brand": u.get("brand", ""),
                 "last_seen": u.get("last_seen", 0), "notes": u.get("notes", "")} for d, u in out]

    EDITABLE = {"notes": 300, "brand": 40, "model": 60, "ip": 45, "android": 20}
    COUNTERS = ("fetch_ok", "fetch_fail", "opens", "ad_interstitial", "ad_rewarded")

    def update(self, dev, data):
        patch = {}
        for k, n in self.EDITABLE.items():
            if k in data:
                patch[k] = str(data[k])[:n]
        for k in self.COUNTERS:
            if k in data:
                try:
                    patch[k] = max(0, int(data[k]))
                except (TypeError, ValueError):
                    pass
        if patch:
            self.ctx.db.patch(f"users/{dev}", patch)
        canon, date = self.ctx.canon(dev), today_str()
        for key, path in (("dl_used", "d"), ("w_used", "w")):
            if key in data:
                try:
                    self.ctx.db.put(f"quota/{date}/{canon}/{path}", max(0, int(data[key])))
                except (TypeError, ValueError):
                    pass
        if "override" in data:
            ov = {}
            for k in ("dl", "w"):
                v = (data["override"] or {}).get(k)
                if v not in (None, ""):
                    try:
                        ov[k] = max(0, int(v))
                    except (TypeError, ValueError):
                        pass
            self.ctx.db.put(f"users/{dev}/override", ov or None)
            self._ov.pop(dev, None)
        self._all_at = 0
        self._top = (0, [])
        return self.detail(dev)

    def delete(self, dev, with_premium=False):
        db = self.ctx.db
        db.delete(f"users/{dev}")
        db.delete(f"user_logs/{dev}")
        db.delete(f"bans/{dev}")
        db.delete(f"idmap/by_dev/{dev}")
        self.ctx._canon.pop(dev, None)
        self.ctx.set_ban(dev, False)
        if with_premium:
            db.delete(f"premium/{dev}")
        self._all_at = 0
        self._top = (0, [])

    def top(self, n=50):
        if time.time() - self._top[0] > 60:
            users = self.ctx.db.get("users") or {}
            rows = []
            for d, u in users.items():
                if isinstance(u, dict):
                    rows.append({"id": d, "ip": u.get("ip", ""), "model": u.get("model", ""),
                                 "brand": u.get("brand", ""), "android": u.get("android", ""),
                                 "fetch_ok": u.get("fetch_ok", 0), "fetch_fail": u.get("fetch_fail", 0),
                                 "ad_interstitial": u.get("ad_interstitial", 0),
                                 "ad_rewarded": u.get("ad_rewarded", 0), "last_seen": u.get("last_seen", 0)})
            rows.sort(key=lambda r: (-r["fetch_ok"], -r["last_seen"]))
            self._top = (time.time(), rows)
        return self._top[1][:n]

    def detail(self, dev, limit=100):
        u = self.ctx.db.get(f"users/{dev}")
        logs = self.ctx.db.get(f"user_logs/{dev}", order_by_key=True) or {}
        rows = [{"id": k, **v} for k, v in sorted(logs.items(), reverse=True)][:limit]
        canon = self.ctx.canon(dev)
        qd, date = self.ctx.db, today_str()
        return {"user": u, "logs": rows, "banned": self.ctx.is_banned(dev), "canon": canon,
                "linked": self.ctx.linked_devices(canon),
                "premium": self.ctx.db.get(f"premium/{canon}"),
                "quota_today": {"dl_used": qd.get(f"quota/{date}/{canon}/d") or 0, "w_used": qd.get(f"quota/{date}/{canon}/w") or 0},
                "override": self.ctx.db.get(f"users/{dev}/override") or {}}


# ====================================================================== content
KINDS = ("dialogs", "carousel", "notifications", "apps")


class Content:
    """Dialogs, carousel, notifications and supported-app tiles + blocked domains."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._cache = {}
        self._lock = threading.RLock()

    def _load(self, kind):
        with self._lock:
            if kind not in self._cache:
                raw = self.ctx.db.get(f"content/{kind}") or {}
                self._cache[kind] = {k: {**v, "id": k} for k, v in raw.items() if isinstance(v, dict)}
            return self._cache[kind]

    def invalidate(self, kind=None):
        with self._lock:
            if kind:
                self._cache.pop(kind, None)
            else:
                self._cache.clear()

    def all(self, kind):
        items = list(self._load(kind).values())
        if kind == "notifications":
            items.sort(key=lambda x: x["id"], reverse=True)
        else:
            items.sort(key=lambda x: (x.get("sort", 0), x["id"]))
        return items

    def enabled(self, kind):
        return [i for i in self.all(kind) if i.get("enabled", True)]

    def get(self, kind, item_id):
        return self._load(kind).get(item_id)

    # ---- admin CRUD
    FIELDS = {
        "dialogs": ("image_url", "message", "url", "sort", "enabled", "title"),
        "carousel": ("image_url", "url", "sort", "enabled", "title"),
        "notifications": ("image_url", "title", "message", "url", "enabled"),
        "apps": ("name", "url", "sort", "highlight", "enabled", "icon_url", "domain"),
    }

    def _clean(self, kind, data):
        out = {}
        for f in self.FIELDS[kind]:
            if f in data:
                v = data[f]
                if f in ("sort",):
                    try:
                        v = max(0, int(v))
                    except Exception:
                        v = 0
                elif f in ("enabled", "highlight"):
                    v = bool(v)
                else:
                    v = str(v or "").strip()[:20000 if f == "message" else 600]
                out[f] = v
        return out

    def _make_room(self, kind, sort, skip_id=None):
        """Cascade-shift: item at `sort` moves to sort+1, and so on."""
        items = {i["id"]: i for i in self.all(kind) if i["id"] != skip_id}
        taken = {}
        for i in items.values():
            taken.setdefault(int(i.get("sort", 0)), []).append(i["id"])
        s = sort
        while s in taken:
            for iid in taken[s]:
                self.ctx.db.put(f"content/{kind}/{iid}/sort", s + 1)
            s += 1
        self.invalidate(kind)

    def create(self, kind, data):
        d = self._clean(kind, data)
        d.setdefault("enabled", True)
        if kind in ("dialogs", "carousel", "apps"):
            d["sort"] = d.get("sort", 0)
            self._make_room(kind, d["sort"])
        d.update({"created": now_ts(), "views": 0, "clicks": 0} if kind != "apps" else {"created": now_ts()})
        iid = push_id()
        self.ctx.db.put(f"content/{kind}/{iid}", d)
        self.invalidate(kind)
        return {**d, "id": iid}

    def update(self, kind, iid, data):
        cur = self.get(kind, iid)
        if not cur:
            return None
        d = self._clean(kind, data)
        if "sort" in d and kind in ("dialogs", "carousel", "apps") and d["sort"] != cur.get("sort"):
            self._make_room(kind, d["sort"], skip_id=iid)
        self.ctx.db.patch(f"content/{kind}/{iid}", d)
        self.invalidate(kind)
        return self.get(kind, iid)

    def delete(self, kind, iid):
        self.ctx.db.delete(f"content/{kind}/{iid}")
        self.ctx.db.delete(f"engage/{kind}/{iid}")
        self.invalidate(kind)

    # ---- engagement (unique per device)
    def engage(self, kind, iid, dev, ip, action):
        item = self.get(kind, iid)
        if not item or action not in ("view", "click"):
            return False
        f = "v" if action == "view" else "c"
        path = f"engage/{kind}/{iid}/{dev}"
        rec = self.ctx.db.get(path) or {}
        if rec.get(f):
            return False
        self.ctx.db.put(f"{path}/{f}", now_ts())
        self.ctx.db.increment(f"content/{kind}/{iid}/{'views' if f == 'v' else 'clicks'}", 1)
        with self._lock:
            c = self._cache.get(kind, {}).get(iid)
            if c is not None:
                c["views" if f == "v" else "clicks"] = c.get("views" if f == "v" else "clicks", 0) + 1
        self.ctx.stats.bump(f"{kind[:-1] if kind.endswith('s') else kind}_{action}", dev, ip, extra={"item": iid})
        return True

    def engaged_users(self, kind, iid, action, page=1, per=25):
        rows = self.ctx.db.get(f"engage/{kind}/{iid}") or {}
        f = "v" if action == "view" else "c"
        users = [(d, r[f]) for d, r in rows.items() if isinstance(r, dict) and r.get(f)]
        users.sort(key=lambda x: -x[1])
        total = len(users)
        out = []
        for d, ts in users[(page - 1) * per: page * per]:
            u = self.ctx.db.get(f"users/{d}") or {}
            out.append({"dev": d, "ts": ts, "ip": u.get("ip", ""), "model": u.get("model", ""),
                        "brand": u.get("brand", "")})
        return {"items": out, "total": total, "page": page, "per": per}

    def user_engagement(self, dev):
        """What a given user has seen/clicked across dialogs, carousel and notifications."""
        res = {}
        for kind in ("dialogs", "carousel", "notifications"):
            rows = []
            for it in self.all(kind):
                rec = self.ctx.db.get(f"engage/{kind}/{it['id']}/{dev}")
                if rec:
                    rows.append({"id": it["id"], "title": it.get("title") or it.get("message", "")[:40],
                                 "v": rec.get("v"), "c": rec.get("c")})
            res[kind] = rows
        return res

    # ---- blocked domains
    def blocked(self):
        with self._lock:
            if "blocked" not in self._cache:
                raw = self.ctx.db.get("blocked") or {}
                self._cache["blocked"] = {k: {**v, "key": k} for k, v in raw.items() if isinstance(v, dict)}
            return self._cache["blocked"]

    def add_blocked(self, domains, message):
        added = []
        for d in domains:
            d = d.strip().lower().replace("https://", "").replace("http://", "").split("/")[0].lstrip("*.")
            if d.startswith("www."):
                d = d[4:]
            if not d or "." not in d:
                continue
            key = safe_key(d)
            self.ctx.db.put(f"blocked/{key}", {"domain": d, "message": message, "created": now_ts()})
            added.append(d)
        with self._lock:
            self._cache.pop("blocked", None)
        return added

    def remove_blocked(self, key):
        self.ctx.db.delete(f"blocked/{key}")
        with self._lock:
            self._cache.pop("blocked", None)

    def match_blocked(self, host):
        host = host.lower()
        for rec in self.blocked().values():
            d = rec["domain"]
            if host == d or host.endswith("." + d):
                return rec
        return None
