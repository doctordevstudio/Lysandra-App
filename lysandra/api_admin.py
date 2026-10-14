"""Admin panel API (HTML/JS panel lives in static/admin). Everything needs an
authenticated single session, CSRF token and is audit-logged."""
import copy
import json
from collections import defaultdict

from flask import Blueprint, Response, g, jsonify, make_response, request

from .defaults import DEFAULT_CONFIG, EDITABLE_SECTIONS
from .videos import CAT_LABEL, CATS
from .util import (DEVICE_RE, date_range, fmt_ist, now_ts, push_id, today_str, to_int, valid_date)

KIND_PREFIX = {"dialogs": "dialog", "carousel": "carousel", "notifications": "notification"}


def init(ctx):
    bp = Blueprint("admin_api", __name__)
    auth = ctx.admin
    req = auth.required
    stats, db = ctx.stats, ctx.db

    def rng():
        a = request.args.get("from") or today_str()
        b = request.args.get("to") or a
        if a == "all":                       # "All time" drill-downs cover the last 365 days of event lists
            a, b = today_str(-364), today_str()
        if not (valid_date(a) and valid_date(b)):
            a = b = today_str()
        return min(a, b), max(a, b)

    def page_args(default=25):
        return max(1, to_int(request.args.get("page"), 1)), min(100, max(1, to_int(request.args.get("per"), default)))

    def paginate(rows, page, per):
        total = len(rows)
        return {"items": rows[(page - 1) * per: page * per], "total": total, "page": page, "per": per}

    def user_brief(dev):
        u = db.get(f"users/{dev}") or {}
        return {"ip": u.get("ip", ""), "model": u.get("model", ""), "brand": u.get("brand", ""),
                "android": u.get("android", "")}

    # ------------------------------------------------------------ auth
    @bp.route("/auth/login", methods=["POST"])
    def login():
        j = request.get_json(silent=True) or {}
        res, err = auth.login(str(j.get("username", ""))[:60], str(j.get("password", ""))[:200],
                              str(j.get("fp", ""))[:80])
        if err:
            code = 423 if "locked_until" in err else 401
            return jsonify({**err, "locked": "locked_until" in err}), code
        resp = jsonify({"ok": True, "csrf": res["csrf"]})
        resp.set_cookie("lys_sid", res["sid"], httponly=True, secure=ctx.settings.cookie_secure,
                        samesite="Strict", max_age=auth.IDLE * 2, path="/")
        g.admin = {"user": j.get("username", ""), "ip": ctx.client_ip()}
        ctx.admin_log("login", "success")
        return resp

    @bp.route("/auth/logout", methods=["POST"])
    @req
    def logout():
        ctx.admin_log("logout")
        auth.logout()
        resp = jsonify({"ok": True})
        resp.delete_cookie("lys_sid", path="/")
        return resp

    @bp.route("/auth/me")
    def me():
        s = auth.current()
        if not s:
            return jsonify({"auth": False}), 401
        return jsonify({"auth": True, "user": s["user"], "csrf": s["csrf"], "idle": auth.IDLE,
                        "tg": ctx.telegram.enabled, "env": {"firebase": bool(ctx.settings.firebase_db_url),
                                                           "public_url": ctx.settings.public_url}})

    # ------------------------------------------------------------ dashboard
    @bp.route("/dashboard")
    @req
    def dashboard():
        a, b = rng()
        s = stats.summary(a, b)
        s["premium"] = premium_numbers(a, b)
        s["users_total"] = (db.get("stats/total") or {}).get("new_user", 0)
        return jsonify(s)

    @bp.route("/events")
    @req
    def events():
        kind = request.args.get("kind", "")
        if not kind.replace("_", "").isalnum() or len(kind) > 60:
            return jsonify({"error": "bad kind"}), 400
        a, b = rng()
        res = stats.list_events(kind, a, b, request.args.get("cursor", ""), min(100, to_int(request.args.get("limit"), 25)))
        for it in res["items"]:
            if it.get("dev"):
                it.update({k: v for k, v in user_brief(it["dev"]).items() if k not in it or not it[k]})
        return jsonify(res)

    @bp.route("/top-users")
    @req
    def top_users():
        return jsonify({"items": ctx.users.top(50)})

    @bp.route("/user/<dev>", methods=["GET", "PUT", "DELETE"])
    @req
    def user(dev):
        if not DEVICE_RE.match(dev):
            return jsonify({"error": "bad id"}), 400
        if request.method == "PUT":
            if not db.get(f"users/{dev}"):
                return jsonify({"error": "user not found"}), 404
            d = ctx.users.update(dev, request.get_json(silent=True) or {})
            ctx.admin_log("user:update", dev)
        elif request.method == "DELETE":
            ctx.users.delete(dev, with_premium=request.args.get("premium") == "1")
            ctx.admin_log("user:delete", dev)
            return jsonify({"ok": True})
        else:
            d = ctx.users.detail(dev)
        d["engagement"] = ctx.content.user_engagement(dev)
        d["txns"] = [t for day in (db.get("txns") or {}).values() for t in day.values() if t.get("dev") in (dev, d.get("canon"))][-20:]
        return jsonify(d)

    @bp.route("/users/search")
    @req
    def users_search():
        return jsonify({"items": ctx.users.search(request.args.get("q", ""))})

    @bp.route("/user/<dev>/unlink", methods=["POST"])
    @req
    def user_unlink(dev):
        """Split a device away from the shared (clone) identity it was linked to."""
        if not DEVICE_RE.match(dev):
            return jsonify({"error": "bad id"}), 400
        db.put(f"idmap/by_dev/{dev}", dev)
        ctx._canon[dev] = dev
        ctx.admin_log("user:unlink", dev)
        return jsonify({"ok": True})

    @bp.route("/user/<dev>/ban", methods=["POST"])
    @req
    def ban(dev):
        if not DEVICE_RE.match(dev):
            return jsonify({"error": "bad id"}), 400
        j = request.get_json(silent=True) or {}
        ctx.set_ban(dev, bool(j.get("banned", True)), str(j.get("reason", "")))
        ctx.admin_log("ban" if j.get("banned", True) else "unban", dev)
        return jsonify({"ok": True})

    # ------------------------------------------------------------ content (dialogs / carousel / notifications / apps)
    @bp.route("/content/<kind>", methods=["GET", "POST"])
    @req
    def content(kind):
        if kind not in ("dialogs", "carousel", "notifications", "apps"):
            return jsonify({"error": "bad kind"}), 404
        if request.method == "POST":
            j = request.get_json(silent=True) or {}
            if kind == "notifications" and not (j.get("title") or "").strip():
                return jsonify({"error": "Title is required"}), 400
            if kind == "carousel" and not (j.get("image_url") or "").strip():
                return jsonify({"error": "Image URL is required"}), 400
            if kind == "dialogs" and not ((j.get("message") or "").strip() or (j.get("image_url") or "").strip()):
                return jsonify({"error": "Add an image URL or a message"}), 400
            if kind == "apps" and not (j.get("name") or "").strip():
                return jsonify({"error": "Name is required"}), 400
            item = ctx.content.create(kind, j)
            ctx.admin_log(f"{kind}:create", item["id"])
            return jsonify(item)
        return jsonify({"items": ctx.content.all(kind)})

    @bp.route("/content/<kind>/<iid>", methods=["PUT", "DELETE"])
    @req
    def content_item(kind, iid):
        if kind not in ("dialogs", "carousel", "notifications", "apps"):
            return jsonify({"error": "bad kind"}), 404
        if request.method == "DELETE":
            ctx.content.delete(kind, iid)
            ctx.admin_log(f"{kind}:delete", iid)
            return jsonify({"ok": True})
        item = ctx.content.update(kind, iid, request.get_json(silent=True) or {})
        if not item:
            return jsonify({"error": "not found"}), 404
        ctx.admin_log(f"{kind}:update", iid)
        return jsonify(item)

    @bp.route("/content/<kind>/<iid>/users")
    @req
    def content_users(kind, iid):
        if kind not in KIND_PREFIX:
            return jsonify({"error": "bad kind"}), 404
        page, per = page_args()
        return jsonify(ctx.content.engaged_users(kind, iid, request.args.get("action", "view"), page, per))

    @bp.route("/content/<kind>/summary")
    @req
    def content_summary(kind):
        if kind not in KIND_PREFIX:
            return jsonify({"error": "bad kind"}), 404
        a, b = rng()
        s = stats.summary(a, b)
        p = KIND_PREFIX[kind]
        pick = lambda blk: {"views": blk.get(f"{p}_view", 0), "clicks": blk.get(f"{p}_click", 0)}
        return jsonify({k: pick(s[k]) for k in ("today", "yesterday", "all", "range")})

    # ------------------------------------------------------------ video library
    @bp.route("/videos", methods=["GET", "POST"])
    @req
    def videos():
        if request.method == "POST":
            item, err = ctx.videos.create(request.get_json(silent=True) or {})
            if err:
                return jsonify({"error": err}), 400
            ctx.admin_log("video:create", item["id"])
            return jsonify(item)
        page, per = page_args(12)
        res = ctx.videos.query(request.args.get("q", ""), request.args.get("category", ""), page, per)
        return jsonify(res)

    @bp.route("/videos/<vid>", methods=["PUT", "DELETE"])
    @req
    def video_item(vid):
        if request.method == "DELETE":
            ctx.videos.delete(vid)
            ctx.admin_log("video:delete", vid)
            return jsonify({"ok": True})
        item, err = ctx.videos.update(vid, request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), 404 if err == "Video not found" else 400
        ctx.admin_log("video:update", vid)
        return jsonify(item)

    @bp.route("/videos/stats")
    @req
    def videos_stats():
        a, b = rng()
        s = stats.summary(a, b)
        cats = []
        for c in CATS:
            row = {"cat": c, "label": CAT_LABEL[c], "count": len([v for v in ctx.videos._items().values() if v.get("category") == c])}
            for period in ("today", "yesterday", "all", "range"):
                row[period] = {"watch": s[period].get(f"vwatch_{c}", 0), "download": s[period].get(f"vdl_{c}", 0)}
            cats.append(row)
        tot = {p: {"watch": s[p].get("vwatch", 0), "download": s[p].get("vdl", 0)} for p in ("today", "yesterday", "all", "range")}
        return jsonify({"categories": cats, "total": tot, "from": a, "to": b})

    # ------------------------------------------------------------ blocked domains
    @bp.route("/blocks", methods=["GET", "POST"])
    @req
    def blocks():
        if request.method == "POST":
            j = request.get_json(silent=True) or {}
            raw = str(j.get("domains", "")).replace(",", "\n").split()
            added = ctx.content.add_blocked(raw, str(j.get("message", ""))[:5000])
            if not added:
                return jsonify({"error": "No valid domain found"}), 400
            ctx.admin_log("block:add", ",".join(added))
            return jsonify({"ok": True, "added": added})
        items = sorted(ctx.content.blocked().values(), key=lambda x: x["domain"])
        return jsonify({"items": items})

    @bp.route("/blocks/<key>", methods=["DELETE"])
    @req
    def block_delete(key):
        ctx.content.remove_blocked(key)
        ctx.admin_log("block:remove", key)
        return jsonify({"ok": True})

    # ------------------------------------------------------------ settings
    @bp.route("/settings")
    @req
    def settings_get():
        return jsonify({"config": ctx.cfg.cfg, "sections": EDITABLE_SECTIONS})

    def validate(section, v):
        if not isinstance(v, dict):
            raise ValueError("Invalid data")
        if len(json.dumps(v)) > 120_000:
            raise ValueError("Too large")
        if section == "premium":
            plans = v.get("plans")
            if not isinstance(plans, list) or not plans:
                raise ValueError("At least one plan is required")
            clean, seen = [], set()
            for p in plans:
                pid = str(p.get("id", "")).strip()[:20]
                if not pid or pid in seen or not pid.replace("_", "").isalnum():
                    raise ValueError("Each plan needs a unique alphanumeric id")
                seen.add(pid)
                days, price = to_int(p.get("days"), 0, 0, 3650), to_int(p.get("price"), 0, 0, 100000)
                if days < 1 or price < 1:
                    raise ValueError("Plan days and price must be positive")
                clean.append({"id": pid, "name": str(p.get("name", ""))[:40] or pid, "days": days, "price": price,
                              "badge": str(p.get("badge", ""))[:20],
                              "downloads_per_day": to_int(p.get("downloads_per_day"), 0, 0, 10000),
                              "watch_per_day": to_int(p.get("watch_per_day"), 0, 0, 10000)})
            v["plans"] = clean
            v["features"] = [str(x)[:80] for x in (v.get("features") or [])][:10]
        if section == "limits":
            v["free_daily_downloads"] = to_int(v.get("free_daily_downloads"), 2, 0, 1000)
            v["free_daily_watch"] = to_int(v.get("free_daily_watch"), 5, 0, 1000)
            v["fetch_per_minute"] = to_int(v.get("fetch_per_minute"), 12, 1, 120)
        if section == "payment":
            v["txn_expiry_minutes"] = to_int(v.get("txn_expiry_minutes"), 10, 2, 120)
            v["submitted_ttl_hours"] = to_int(v.get("submitted_ttl_hours"), 24, 1, 168)
            v["max_pending_per_device"] = to_int(v.get("max_pending_per_device"), 2, 1, 10)
            v["max_txn_per_hour"] = to_int(v.get("max_txn_per_hour"), 6, 1, 60)
            if v.get("rotation") not in ("success", "round_robin"):
                v["rotation"] = "success"
        if section == "app":
            v["version_code"] = to_int(v.get("version_code"), 1, 1, 10**7)
            v["min_version_code"] = to_int(v.get("min_version_code"), 1, 1, 10**7)
        if section == "landing":
            for k in ("features", "steps", "faqs"):
                v[k] = [str(x).strip()[:600] for x in (v.get(k) or []) if str(x).strip()][:20]
            if v.get("apk_url") and not str(v["apk_url"]).startswith(("http://", "https://")):
                raise ValueError("APK URL must start with http:// or https://")
        if section == "security":
            v["blocked_cidrs"] = [str(x).strip() for x in (v.get("blocked_cidrs") or []) if str(x).strip()][:500]
        return v

    @bp.route("/settings/<section>", methods=["PUT"])
    @req
    def settings_put(section):
        if section not in EDITABLE_SECTIONS:
            return jsonify({"error": "bad section"}), 404
        try:
            val = validate(section, request.get_json(silent=True))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        saved = ctx.cfg.save_section(section, val)
        ctx.admin_log("settings:" + section, "updated")
        return jsonify({"ok": True, "section": saved})

    # ------------------------------------------------------------ premium
    def premium_numbers(a, b):
        t, y = today_str(), today_str(-1)
        lo, hi = min(a, y), max(b, t)
        earn = ctx.payments.earnings_range(lo, hi)
        def tot(rows, dates):
            r = [e for e in rows if e["date"] in dates]
            return {"count": len(r), "amount": sum(e["amount"] for e in r)}
        all_rows = ctx.payments.earnings_range("2020-01-01", "2100-01-01")
        rows = [e for e in earn]
        recs = [r for r in (db.get("premium") or {}).values() if isinstance(r, dict)]
        return {"today": tot(rows, {t}), "yesterday": tot(rows, {y}), "range": tot(rows, set(date_range(a, b))),
                "all": {"count": len(all_rows), "amount": sum(e["amount"] for e in all_rows)},
                "active": len([r for r in recs if r.get("status") == "active" and r.get("expires", 0) > now_ts()]),
                "total_users": len(recs)}

    @bp.route("/premium")
    @req
    def premium_list():
        flt = request.args.get("filter", "all")
        a, b = rng()
        t, y = today_str(), today_str(-1)
        dates = {"today": {t}, "yesterday": {y}, "range": set(date_range(a, b))}.get(flt)
        page, per = page_args()
        status = request.args.get("status", "")
        rows = []
        for dev, r in (db.get("premium") or {}).items():
            if not isinstance(r, dict):
                continue
            if dates is not None and not (r.get("updated") and ctx_date(r["updated"]) in dates):
                continue
            live = r.get("status")
            if live == "active" and r.get("expires", 0) <= now_ts():
                live = "expired"
            if status and live != status:
                continue
            rows.append({"dev": dev, **r, "status": live, **user_brief(dev)})
        rows.sort(key=lambda r: -r.get("updated", 0))
        out = paginate(rows, page, per)
        out["summary"] = premium_numbers(a, b)
        return jsonify(out)

    def ctx_date(ts):
        from .util import ts_to_date
        return ts_to_date(ts)

    @bp.route("/premium/earnings")
    @req
    def premium_earnings():
        a, b = rng()
        rows = ctx.payments.earnings_range(a, b)
        per_day = defaultdict(lambda: {"count": 0, "amount": 0})
        for e in rows:
            per_day[e["date"]]["count"] += 1
            per_day[e["date"]]["amount"] += e["amount"]
        return jsonify({"days": [{"date": d, **v} for d, v in sorted(per_day.items())],
                        "total": sum(e["amount"] for e in rows), "count": len(rows)})

    @bp.route("/premium/<dev>/<action>", methods=["POST"])
    @req
    def premium_action(dev, action):
        if not DEVICE_RE.match(dev):
            return jsonify({"error": "bad id"}), 400
        j = request.get_json(silent=True) or {}
        by = f"admin:{g.admin['user']}"
        if action == "revoke":
            ok = ctx.payments.revoke(dev, by, str(j.get("reason", "")))
            ctx.admin_log("premium:revoke", dev)
            return jsonify({"ok": ok})
        if action in ("renew", "grant"):
            days = to_int(j.get("days"), 0, 0, 3650)
            if days < 1:
                return jsonify({"error": "Days must be 1 or more"}), 400
            if action == "renew":
                rec = ctx.payments.renew(dev, days, by)
            else:
                pl = ctx.payments.plan(str(j.get("plan_id", "")))
                rec = ctx.payments.grant(dev, days, pl["name"] if pl else str(j.get("plan", "Admin grant"))[:40], "", 0, by,
                                         pl["id"] if pl else "", kind="grant")
            ctx.admin_log(f"premium:{action}", f"{dev} +{days}d")
            return jsonify({"ok": True, "premium": rec})
        if action == "edit":
            try:
                rec = ctx.payments.edit(dev, j.get("started"), j.get("expires"), j.get("plan_id"), by)
            except Exception as e:
                return jsonify({"error": getattr(e, "msg", "Invalid data")}), 400
            ctx.admin_log("premium:edit", f"{dev} exp={rec.get('expires')}")
            return jsonify({"ok": True, "premium": rec})
        return jsonify({"error": "bad action"}), 404

    # ---- plan categories: Free / each plan; purchased + expiring per day, with drill-down lists
    def plan_cats():
        return [{"id": p["id"], "name": p["name"]} for p in ctx.cfg.get("premium", "plans", [])] + [{"id": "other", "name": "Other / admin"}]

    def periods(a, b):
        t, y = today_str(), today_str(-1)
        return {"today": {t}, "yesterday": {y}, "range": set(date_range(a, b))}

    @bp.route("/premium/overview")
    @req
    def premium_overview():
        a, b = rng()
        cats = plan_cats()
        ids = {c["id"] for c in cats}
        per = periods(a, b)
        recs = {d: r for d, r in (db.get("premium") or {}).items() if isinstance(r, dict)}
        cat_of = lambda r: r.get("plan_id") if r.get("plan_id") in ids else "other"
        now = now_ts()
        out = {c["id"]: {"name": c["name"], "active": 0, "purchased": {k: 0 for k in (*per, "all")},
                         "expiring": {k: 0 for k in (*per, "all")}} for c in cats}
        for r in recs.values():
            c = out[cat_of(r)]
            if r.get("status") == "active" and r.get("expires", 0) > now:
                c["active"] += 1
            if r.get("status") != "revoked" and r.get("expires"):
                d = ctx_date(r["expires"])
                c["expiring"]["all"] += 1
                for k, ds in per.items():
                    if d in ds:
                        c["expiring"][k] += 1
        lo, hi = min(a, today_str(-1)), max(b, today_str())
        ev = db.get("sub_events", order_by_key=True, start_at=lo, end_at=hi) or {}
        for day, items in ev.items():
            for e in (items or {}).values():
                if e.get("kind") in ("purchase", "renew", "grant"):
                    c = out[e.get("plan_id") if e.get("plan_id") in ids else "other"]
                    for k, ds in per.items():
                        if day in ds:
                            c["purchased"][k] += 1
        active_total = sum(c["active"] for c in out.values())
        users_total = (db.get("stats/total") or {}).get("new_user", 0)
        return jsonify({"plans": out, "order": [c["id"] for c in cats], "free_users": max(0, users_total - active_total),
                        "active_total": active_total, "users_total": users_total})

    @bp.route("/premium/users")
    @req
    def premium_users():
        a, b = rng()
        mode, plan, period = request.args.get("mode", "active"), request.args.get("plan", ""), request.args.get("period", "all")
        page, per = page_args()
        ids = {c["id"] for c in plan_cats()}
        recs = {d: r for d, r in (db.get("premium") or {}).items() if isinstance(r, dict)}
        cat_of = lambda r: r.get("plan_id") if r.get("plan_id") in ids else "other"
        now = now_ts()
        dates = periods(a, b).get(period)
        rows = []
        if mode == "free":
            active = {d for d, r in recs.items() if r.get("status") == "active" and r.get("expires", 0) > now}
            for d, u in (db.get("users") or {}).items():
                if isinstance(u, dict) and d not in active:
                    rows.append({"dev": d, "status": "free", "plan_name": "Free", "plan_id": "", "ip": u.get("ip", ""),
                                 "model": u.get("model", ""), "brand": u.get("brand", ""), "last_seen": u.get("last_seen", 0)})
            rows.sort(key=lambda r: -r["last_seen"])
        else:
            devs = None
            if mode == "purchased":
                lo, hi = (min(dates), max(dates)) if dates else ("2020-01-01", today_str())
                ev = db.get("sub_events", order_by_key=True, start_at=lo, end_at=hi) or {}
                devs = {e["dev"] for day, items in ev.items() if (dates is None or day in dates)
                        for e in (items or {}).values() if e.get("kind") in ("purchase", "renew", "grant")}
            for d, r in recs.items():
                if devs is not None and d not in devs:
                    continue
                if plan and cat_of(r) != plan:
                    continue
                live = r.get("status")
                if live == "active" and r.get("expires", 0) <= now:
                    live = "expired"
                if mode == "active" and live != "active":
                    continue
                if mode == "expiring":
                    if r.get("status") == "revoked" or not r.get("expires"):
                        continue
                    if dates is not None and ctx_date(r["expires"]) not in dates:
                        continue
                rows.append({"dev": d, **r, "status": live, **user_brief(d)})
            rows.sort(key=lambda r: r.get("expires", 0), reverse=(mode != "expiring"))
        return jsonify(paginate(rows, page, per))

    # ------------------------------------------------------------ UPI ids
    @bp.route("/upi", methods=["GET", "POST"])
    @req
    def upi():
        if request.method == "POST":
            j = request.get_json(silent=True) or {}
            name, upi_id, chat = str(j.get("name", "")).strip()[:60], str(j.get("upi_id", "")).strip(), str(j.get("chat_id", "")).strip()
            import re
            if not name or not re.match(r"^[\w.\-]{2,60}@[a-zA-Z0-9.\-]{2,40}$", upi_id):
                return jsonify({"error": "Enter a name and a valid UPI ID (like name@bank)"}), 400
            if not re.match(r"^-?\d{5,20}$", chat):
                return jsonify({"error": "Telegram chat ID must be a number (the user can send /start to the bot to see it)"}), 400
            for u in (db.get("upi") or {}).values():
                if isinstance(u, dict) and u.get("upi_id", "").lower() == upi_id.lower():
                    return jsonify({"error": "This UPI ID already exists"}), 400
            uid = push_id()
            rec = {"name": name, "upi_id": upi_id, "chat_id": chat, "active": True, "created": now_ts(),
                   "txn_count": 0, "success_count": 0, "failed_count": 0, "amount_total": 0, "last_assigned": 0}
            db.put(f"upi/{uid}", rec)
            ctx.admin_log("upi:add", upi_id)
            ctx.bg(ctx.telegram.send, chat, f"✅ You were added as a UPI receiver on Lysandra.\nUPI: <code>{upi_id}</code>")
            return jsonify({"id": uid, **rec})
        return jsonify({"items": [{"id": k, **v} for k, v in (db.get("upi") or {}).items() if isinstance(v, dict)]})

    @bp.route("/upi/<uid>", methods=["PUT", "DELETE"])
    @req
    def upi_item(uid):
        if not db.get(f"upi/{uid}"):
            return jsonify({"error": "not found"}), 404
        if request.method == "DELETE":
            db.delete(f"upi/{uid}")
            ctx.admin_log("upi:delete", uid)
            return jsonify({"ok": True})
        j = request.get_json(silent=True) or {}
        patch = {}
        for f, n in (("name", 60), ("upi_id", 80), ("chat_id", 20)):
            if f in j:
                patch[f] = str(j[f]).strip()[:n]
        if "active" in j:
            patch["active"] = bool(j["active"])
        db.patch(f"upi/{uid}", patch)
        ctx.admin_log("upi:update", uid)
        return jsonify({"ok": True})

    @bp.route("/upi/report")
    @req
    def upi_report():
        a, b = rng()
        t, y = today_str(), today_str(-1)
        return jsonify({"range": ctx.payments.upi_report(a, b), "today": ctx.payments.upi_report(t, t),
                        "yesterday": ctx.payments.upi_report(y, y), "from": a, "to": b})

    # ------------------------------------------------------------ transactions
    @bp.route("/txns")
    @req
    def txns():
        ctx.payments.expire_due()
        a, b = rng()
        if request.args.get("all") == "1":
            a, b = "2020-01-01", today_str()
        rows = ctx.payments.txns_range(a, b)
        st, upi_key, q = request.args.get("status", ""), request.args.get("upi", ""), request.args.get("q", "").strip().lower()
        if st:
            rows = [r for r in rows if r["status"] == st]
        if upi_key:
            rows = [r for r in rows if r["upi_key"] == upi_key]
        if q:
            rows = [r for r in rows if q in r["txn_id"].lower() or q in r["dev"] or q in (r.get("utr") or "") or q in r.get("ip", "")]
        counts = {"total": len(rows), "success": 0, "failed": 0, "pending": 0, "amount": 0}
        for r in rows:
            counts[r["status"]] += 1
            if r["status"] == "success":
                counts["amount"] += r["amount"]
        page, per = page_args()
        out = paginate([{k: v for k, v in r.items() if k != "proof_hash"} for r in rows], page, per)
        out["counts"] = counts
        return jsonify(out)

    @bp.route("/txns/<tid>/<action>", methods=["POST"])
    @req
    def txn_action(tid, action):
        label = f"admin:{g.admin['user']}"
        j = request.get_json(silent=True) or {}
        if action == "verify":
            res = ctx.payments.verify(tid.upper(), "admin", label)
        elif action == "fail":
            res = ctx.payments.fail(tid.upper(), str(j.get("reason", "")), "admin", label)
        else:
            return jsonify({"error": "bad action"}), 404
        ctx.admin_log(f"txn:{action}", tid)
        for chat, text in res.get("also", []):
            ctx.bg(ctx.telegram.send, chat, text)
        return jsonify({"ok": True, "text": res["text"]})

    @bp.route("/txns/<tid>/proof")
    @req
    def txn_proof(tid):
        data = ctx.payments.proof_image(tid.upper())
        if not data:
            return jsonify({"error": "Screenshot not available"}), 404
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------ logs
    @bp.route("/logs")
    @req
    def logs():
        kind = "admin_logs" if request.args.get("kind", "admin") == "admin" else "admin_login_logs"
        a, b = rng()
        out = []
        raw = db.get(kind, order_by_key=True, start_at=a, end_at=b) or {}
        for d in sorted(raw, reverse=True):
            for k, v in sorted((raw[d] or {}).items(), reverse=True):
                out.append({"id": k, "date": d, **v})
        page, per = page_args(50)
        return jsonify(paginate(out, page, per))

    return bp
