import base64
import json
import re
import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from lysandra import create_app  # noqa: E402
from lysandra.config import Settings  # noqa: E402
from lysandra.db import MemoryDB  # noqa: E402
from lysandra.extractors.base import ExtractorError  # noqa: E402
from lysandra.extractors.formats import build_formats  # noqa: E402
from lysandra.util import today_str  # noqa: E402
from tests.helpers import APK, SECRET, AppClient, png_bytes  # noqa: E402

ADMIN_CHAT = "9001001"


def make_app():
    s = Settings(app_secret=SECRET, allowed_apk_sha256=[APK], admin_password="pw-123456", admin_user="boss",
                 telegram_bot_token="TOK", telegram_admin_chat_id=ADMIN_CHAT, telegram_webhook_secret="whsec",
                 public_url="https://x.test", testing=True, cookie_secure=False, admin_path="/panel")
    app = create_app(s, MemoryDB())
    sent = []
    tg = app.ctx.telegram
    tg.api = lambda method, data=None, files=None: (sent.append((method, data, bool(files))) or
                                                    {"ok": True, "result": {"photo": [{"file_id": "FID1"}]}})
    app.sent = sent
    return app


class Admin:
    def __init__(self, app):
        self.c = app.test_client()
        self.csrf = None

    def login(self, user="boss", pw="pw-123456", fp="fp1"):
        r = self.c.post("/panel/api/auth/login", json={"username": user, "password": pw, "fp": fp},
                        headers={"User-Agent": "T", "CF-Connecting-IP": "5.5.5.5"})
        if r.status_code == 200:
            self.csrf = r.get_json()["csrf"]
        return r

    def req(self, method, path, **kw):
        h = {"X-CSRF-Token": self.csrf or "", "User-Agent": "T"}
        return getattr(self.c, method)("/panel/api" + path, headers=h, **kw)

    def get(self, p, **kw): return self.req("get", p, **kw)
    def post(self, p, j=None): return self.req("post", p, json=j or {})
    def put(self, p, j=None): return self.req("put", p, json=j or {})
    def delete(self, p): return self.req("delete", p)


class Base(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.ctx = self.app.ctx
        self.web = self.app.test_client()
        self.u = AppClient(self.web)
        self.admin = Admin(self.app)
        assert self.admin.login().status_code == 200


class TestSecurity(Base):
    def test_signature_replay_clock_apk(self):
        st, out = self.u.call("/boot", {"ver": 1, "info": {"model": "Pixel"}})
        self.assertEqual(st, 200)
        self.assertTrue(out["ok"])
        st, _ = self.u.call("/boot", {}, tamper=True)
        self.assertEqual(st, 401)
        st, _ = self.u.call("/boot", {}, nonce="n" * 16)
        self.assertEqual(st, 200)
        st, j = self.u.call("/boot", {}, nonce="n" * 16)
        self.assertEqual((st, j["e"]), (401, "replay"))
        st, j = self.u.call("/boot", {}, ts=int(time.time()) - 4000)
        self.assertEqual((st, j["e"]), (401, "clock"))
        bad = AppClient(self.web, apk="cd" * 32)
        self.assertEqual(bad.call("/boot", {})[0], 401)
        wrong = AppClient(self.web, secret="other-secret")
        self.assertEqual(wrong.call("/boot", {})[0], 401)
        r = self.web.post("/api/v1/boot", data="garbage")
        self.assertEqual(r.status_code, 400)

    def test_banned_device_and_rate_limit(self):
        self.u.call("/boot", {})
        self.ctx.set_ban(self.u.dev, True)
        st, j = self.u.call("/boot", {})
        self.assertEqual((st, j["e"]), (403, "banned"))
        self.ctx.set_ban(self.u.dev, False)
        codes = [self.u.call("/boot", {})[0] for _ in range(25)]
        self.assertIn(429, codes)

    def test_env_blocking(self):
        for d in ({"vpn": True}, {"proxy": True}, {"info": {"emulator": True}}):
            st, out = AppClient(self.web).call("/boot", {"ver": 1, **d})
            self.assertEqual((out["ok"], out["code"]), (False, "env"), d)
        self.ctx.cfg.save_section("security", {**self.ctx.cfg.get("security"), "blocked_cidrs": ["9.9.9.0/24"]})
        st, out = AppClient(self.web).call("/boot", {"ver": 1}, ip="9.9.9.9")
        self.assertEqual(out["code"], "env")

    def test_admin_lock_after_3_failures_and_single_session(self):
        a = Admin(self.app)
        for _ in range(3):
            self.assertEqual(a.login(pw="bad", fp="evil").status_code, 401)
        r = a.login(pw="pw-123456", fp="evil")
        self.assertEqual(r.status_code, 423)       # locked 24h even with the right password
        self.assertTrue(r.get_json()["locked_until"] > time.time() + 80000)
        # new login elsewhere kills the first session (single active session)
        b = Admin(self.app)
        self.assertEqual(self.admin.get("/dashboard").status_code, 200)
        self.assertEqual(b.login(fp="other-device").status_code, 423)  # same UA/ip lock keys
        self.assertEqual(self.admin.get("/dashboard").status_code, 200)

    def test_admin_session_rules(self):
        self.assertEqual(self.admin.post("/auth/logout").status_code, 200)
        self.assertEqual(self.admin.get("/dashboard").status_code, 401)
        self.assertEqual(self.admin.login().status_code, 200)
        # CSRF required for writes
        r = self.admin.c.post("/panel/api/blocks", json={"domains": "a.com"}, headers={"X-CSRF-Token": "bad"})
        self.assertEqual(r.status_code, 403)
        # idle expiry after 15 minutes
        self.ctx.admin.session["last"] -= 16 * 60
        self.assertEqual(self.admin.get("/dashboard").status_code, 401)
        # second login replaces the first
        a1, a2 = Admin(self.app), Admin(self.app)
        a1.login(fp="x1"); a2.login(fp="x2")
        self.assertEqual(a1.get("/dashboard").status_code, 401)
        self.assertEqual(a2.get("/dashboard").status_code, 200)

    def test_admin_requires_auth_everywhere(self):
        c = self.app.test_client()
        for p in ("/dashboard", "/settings", "/upi", "/txns", "/premium", "/content/dialogs", "/blocks", "/logs"):
            self.assertEqual(c.get("/panel/api" + p).status_code, 401, p)
        self.assertEqual(c.get("/panel/").status_code, 200)

    def test_origin_secret_and_webhook_secret(self):
        s = Settings(app_secret=SECRET, origin_secret="orig", testing=True, telegram_webhook_secret="ws",
                     cookie_secure=False)
        app = create_app(s, MemoryDB())
        c = app.test_client()
        self.assertEqual(c.get("/healthz").status_code, 200)
        self.assertEqual(c.get("/panel/").status_code, 403)
        self.assertEqual(c.get("/panel/", headers={"X-Origin-Secret": "orig"}).status_code, 404)  # no panel at default path
        r = self.web.post("/tg/wrong", json={})
        self.assertEqual(r.status_code, 404)
        r = self.web.post("/tg/whsec", json={})        # right path, missing header
        self.assertEqual(r.status_code, 404)


class TestContent(Base):
    def test_dialog_sort_cascade_and_engagement(self):
        ids = []
        for s in (1, 2, 3):
            ids.append(self.admin.post("/content/dialogs", {"message": f"m{s}", "sort": s}).get_json()["id"])
        new = self.admin.post("/content/dialogs", {"message": "new", "sort": 2}).get_json()
        items = self.admin.get("/content/dialogs").get_json()["items"]
        self.assertEqual([(i["message"], i["sort"]) for i in items], [("m1", 1), ("new", 2), ("m2", 3), ("m3", 4)])
        # disable + app only sees enabled
        self.admin.put(f"/content/dialogs/{ids[0]}", {"enabled": False})
        st, home = self.u.call("/home", {})
        self.assertEqual([d["message"] for d in home["dialogs"]], ["new", "m2", "m3"])
        # views/clicks are unique per device
        did = new["id"]
        for _ in range(3):
            self.u.call("/engage", {"kind": "dialogs", "id": did, "action": "view"})
        self.u.call("/engage", {"kind": "dialogs", "id": did, "action": "click"})
        AppClient(self.web).call("/engage", {"kind": "dialogs", "id": did, "action": "view"})
        it = [i for i in self.admin.get("/content/dialogs").get_json()["items"] if i["id"] == did][0]
        self.assertEqual((it["views"], it["clicks"]), (2, 1))
        users = self.admin.get(f"/content/dialogs/{did}/users?action=view").get_json()
        self.assertEqual(users["total"], 2)
        sm = self.admin.get("/content/dialogs/summary").get_json()
        self.assertEqual((sm["today"]["views"], sm["all"]["clicks"]), (2, 1))
        self.assertEqual(self.admin.put("/content/dialogs/nope", {}).status_code, 404)
        self.admin.delete(f"/content/dialogs/{did}")
        self.assertEqual(len(self.admin.get("/content/dialogs").get_json()["items"]), 3)

    def test_carousel_and_validation(self):
        self.assertEqual(self.admin.post("/content/carousel", {"url": "x"}).status_code, 400)
        self.admin.post("/content/carousel", {"image_url": "https://i/a.png", "sort": 0, "url": ""})
        self.admin.post("/content/carousel", {"image_url": "https://i/b.png", "sort": 0, "url": "https://t.me/x"})
        st, home = self.u.call("/home", {})
        self.assertEqual([c["image_url"][-5:] for c in home["carousel"]], ["b.png", "a.png"])

    def test_notifications_unread_pagination(self):
        for i in range(25):
            self.admin.post("/content/notifications", {"title": f"t{i}", "message": "m", "image_url": ""})
        st, r = self.u.call("/notifications", {})
        self.assertEqual((r["unread"], len(r["items"])), (25, 20))
        self.assertEqual(r["items"][0]["title"], "t24")
        st, r2 = self.u.call("/notifications", {"cursor": r["next"]})
        self.assertEqual(len(r2["items"]), 5)
        self.assertEqual(r2["next"], "")
        st, r3 = self.u.call("/notifications", {"after": r["newest"]})
        self.assertEqual(r3["unread"], 0)
        self.admin.post("/content/notifications", {"title": "fresh"})
        st, r4 = self.u.call("/notifications", {"after": r["newest"]})
        self.assertEqual(r4["unread"], 1)

    def test_blocked_domains(self):
        res = self.admin.post("/blocks", {"domains": "Bad.com, https://www.evil.org/path\nfoo.bar.net", "message": "<b>No</b>"})
        self.assertEqual(sorted(res.get_json()["added"]), ["bad.com", "evil.org", "foo.bar.net"])
        self.ctx.extractors.fallback.extract = lambda url: self.fail("must not be called")
        for u in ("bad.com/v/1", "https://sub.bad.com/x", "evil.org"):
            st, out = self.u.call("/fetch", self._fp(u))
            self.assertEqual(out["code"], "blocked", u)
            self.assertEqual(out["html"], "<b>No</b>")
        ev = self.admin.get(f"/events?kind=blocked_hit&from={today_str()}&to={today_str()}").get_json()
        self.assertEqual(len(ev["items"]), 3)
        key = self.admin.get("/blocks").get_json()["items"][0]["key"]
        self.admin.delete(f"/blocks/{key}")
        self.assertEqual(len(self.admin.get("/blocks").get_json()["items"]), 2)
        self.assertEqual(self.admin.post("/blocks", {"domains": "nodot"}).status_code, 400)

    @staticmethod
    def _fp(u):
        import hashlib
        return {"url": u, "h": hashlib.sha256(u.encode()).hexdigest()}


FAKE = {"title": "Cool: Video?", "thumbnail": "https://t/i.jpg", "duration": 61, "platform": "Vimeo", "uploader": "x",
        "relay": False, "formats": [{"fid": "v720_1", "kind": "av", "label": "720p MP4", "quality": "720p", "ext": "mp4",
                                     "mime": "video/mp4", "size": 5000000, "url": "https://cdn/x.mp4",
                                     "headers": {"User-Agent": "UA", "X-Secret": "s"}, "audio_only": False, "height": 720},
                                    {"fid": "a_1", "kind": "audio", "label": "Audio", "quality": "128kbps", "ext": "m4a", "mime": "audio/mp4",
                                     "size": 900000, "url": "https://cdn/x.m4a", "headers": {}, "audio_only": True,
                                     "height": 0}]}


class TestFetch(Base):
    def setUp(self):
        super().setUp()
        self.calls = []
        def fake(url):
            self.calls.append(url)
            return FAKE
        self.ctx.extractors.fallback.extract = fake

    def test_fetch_normalizes_and_hides_urls(self):
        for raw in ("abc.com/v", "https://abc.com/v"):
            st, out = self.u.call("/fetch", TestContent._fp(raw))
            self.assertTrue(out["ok"], out)
            self.assertNotIn("url", out["formats"][0])
        self.assertEqual(self.calls, ["https://abc.com/v"])      # second one served from cache
        self.assertEqual(out["title"], "Cool: Video?")

    def test_fetch_rejects_bad_input(self):
        st, out = self.u.call("/fetch", {"url": "https://abc.com/v", "h": "deadbeef"})
        self.assertEqual(out["code"], "integrity")
        for bad in ("", "http://localhost/x", "http://127.0.0.1/a", "http://192.168.1.2/x", "ftp://a.com", "a b.com"):
            st, out = self.u.call("/fetch", TestContent._fp(bad))
            self.assertEqual(out["code"], "bad_url", bad)

    def test_extractor_error_is_reported_and_counted(self):
        def boom(url): raise ExtractorError("Could not fetch this video.")
        self.ctx.extractors.fallback.extract = boom
        st, out = self.u.call("/fetch", TestContent._fp("abc.com/x"))
        self.assertEqual((out["code"], out["msg"]), ("fetch_failed", "Could not fetch this video."))
        s = self.admin.get("/dashboard").get_json()
        self.assertEqual(s["today"]["fetch_fail"], 1)

    def test_maintenance_blocks_fetch_and_counts_opens(self):
        self.admin.put("/settings/maintenance", {"enabled": True, "message": "<p>back soon</p>"})
        st, boot = self.u.call("/boot", {"ver": 1})
        self.assertTrue(boot["maintenance"]["on"])
        self.assertEqual(self.u.call("/fetch", TestContent._fp("abc.com/x"))[1]["code"], "maintenance")
        s = self.admin.get("/dashboard").get_json()
        self.assertEqual(s["today"]["maint_open"], 1)

    def test_daily_limit_and_premium(self):
        self.admin.put("/settings/limits", {"free_daily_downloads": 2, "free_daily_watch": 1, "fetch_per_minute": 30})
        st, f = self.u.call("/fetch", TestContent._fp("abc.com/x"))
        q = f["quota"]
        self.assertEqual((q["plan"], q["dl_limit"], q["dl_remaining"], q["w_limit"], q["w_remaining"]), ("Free", 2, 2, 1, 1))
        for i in range(2):
            st, a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})
            self.assertTrue(a["ok"])
            self.assertEqual(a["url"], "https://cdn/x.mp4")
            self.assertEqual(set(a["headers"]), {"User-Agent"})   # only safe headers forwarded
            self.assertEqual(a["filename"], "Cool Video.mp4")
        st, a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})
        self.assertEqual((a["ok"], a["code"], a["kind"]), (False, "limit", "download"))
        self.assertEqual((a["quota"]["dl_remaining"], a["quota"]["can_download"], a["quota"]["can_watch"]), (0, False, True))
        # another device can't use this fetch id
        other = AppClient(self.web)
        self.assertEqual(other.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})[1]["code"], "expired")
        # watching (streaming) never consumes the daily quota, even when it is exhausted
        st, a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1", "watch": True})
        self.assertTrue(a["ok"])                      # download limit used up, but one watch is left -> play only
        self.assertEqual((a["quota"]["w_remaining"], a["quota"]["can_watch"]), (0, False))
        st, a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1", "watch": True})
        self.assertEqual((a["code"], a["kind"]), ("limit", "watch"))   # both limits exhausted -> premium screen
        self.assertEqual(self.ctx.db.get(f"quota/{today_str()}/{self.u.dev}/d"), 2)
        # premium (admin grant, no plan limits) = unlimited downloads and watching
        self.ctx.payments.grant(self.u.dev, 30, "Admin", amount=0)
        for w in (False, True, False, True):
            st, a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1", "watch": w})
            self.assertTrue(a["ok"])
        self.assertTrue(a["quota"]["dl_unlimited"] and a["quota"]["w_unlimited"])
        self.assertEqual(self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "nope"})[1]["code"], "bad")

    def test_relay_for_youtube_like(self):
        r = dict(FAKE, relay=True, proxy=None)
        self.ctx.extractors.fallback.extract = lambda url: r
        st, f = self.u.call("/fetch", TestContent._fp("abc.com/y"))
        st, a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})
        self.assertIn("/api/v1/relay/", a["url"])
        self.assertEqual(self.web.get("/api/v1/relay/bad.1.x").status_code, 410)
        path = a["url"].replace("https://x.test", "")
        class R:  # fake upstream
            status_code, headers = 206, {"Content-Length": "4", "Content-Range": "bytes 0-3/10"}
            def iter_content(self, n): yield b"abcd"
        import lysandra.api_app as m
        m.requests.get = lambda *a, **k: R()
        resp = self.web.get(path, headers={"Range": "bytes=0-3"})
        self.assertEqual((resp.status_code, resp.data), (206, b"abcd"))

    def test_registry_routes(self):
        reg = self.ctx.extractors
        self.assertEqual(reg.resolve("m.youtube.com").name, "youtube")
        self.assertEqual(reg.resolve("youtu.be").name, "youtube")
        self.assertEqual(reg.resolve("www.terabox.com".replace("www.", "")).name, "terabox")
        self.assertEqual(reg.resolve("tera1024.com").name, "terabox")
        self.assertEqual(reg.resolve("vimeo.com").name, "yt-dlp")
        self.assertEqual(reg.resolve("notyoutube.com").name, "yt-dlp")
        with self.assertRaises(ExtractorError):
            reg.resolve("terabox.com").extract("https://terabox.com/s/1x")

    def test_build_formats_tabs_and_auto_merge(self):
        info = {"duration": 100, "formats": [
            {"url": "u1", "protocol": "https", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "filesize": 1, "format_id": "18"},
            {"url": "u3", "protocol": "https", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080, "format_id": "137", "filesize": 9},
            {"url": "u4", "protocol": "m3u8_native", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 480, "format_id": "h"},
            {"url": "u5", "protocol": "https", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 128, "format_id": "140", "filesize": 2},
            {"url": "u6", "protocol": "https", "ext": "exe", "vcodec": "avc1", "acodec": "mp4a", "height": 144, "format_id": "x"},
            {"url": "u7", "protocol": "http_dash_segments", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "format_id": "d"}]}
        f = build_formats(info)
        kinds = [(x["kind"], x["quality"]) for x in f]
        self.assertEqual(kinds, [("av", "480p"), ("av", "360p"), ("merge", "1080p"), ("video", "1080p"), ("audio", "128kbps")])
        merge = f[2]
        self.assertEqual((merge["parts"], merge["size"]), (["v137", "a140"], 11))
        self.assertTrue(f[0]["hls"] and not f[1]["hls"])
        self.assertTrue(all(x["duration"] == 100 for x in f))


class TestPayments(Base):
    def setUp(self):
        super().setUp()
        self.upi_a = self.admin.post("/upi", {"name": "Alice", "upi_id": "alice@okaxis", "chat_id": "7001001"}).get_json()
        self.upi_b = self.admin.post("/upi", {"name": "Bob", "upi_id": "bob@oksbi", "chat_id": "7002002"}).get_json()
        self.app.sent.clear()

    def create(self, plan="m3", client=None):
        st, out = (client or self.u).call("/pay/create", {"plan": plan})
        return out

    def chats(self, method="sendMessage"):
        return [d["chat_id"] for m, d, f in self.app.sent if m == method]

    def test_upi_validation(self):
        self.assertEqual(self.admin.post("/upi", {"name": "", "upi_id": "a@b", "chat_id": "1"}).status_code, 400)
        self.assertEqual(self.admin.post("/upi", {"name": "x", "upi_id": "bad id", "chat_id": "70011"}).status_code, 400)
        self.assertEqual(self.admin.post("/upi", {"name": "x", "upi_id": "alice@okaxis", "chat_id": "70011"}).status_code, 400)
        self.assertEqual(self.admin.post("/upi", {"name": "x", "upi_id": "x1@okaxis", "chat_id": "abc"}).status_code, 400)

    def test_create_txn_format_notify_and_reuse(self):
        out = self.create()
        t = out["txn"]
        self.assertTrue(out["ok"])
        self.assertRegex(t["txn"], r"^LYS\d{10}$")
        self.assertEqual((t["amount"], t["plan"], t["status"]), (49, "3 Months", "pending"))
        self.assertEqual(t["upi_uri"].split("&")[2], "am=49.00")
        self.assertEqual(sorted(self.chats()), sorted([ADMIN_CHAT, t and self.ctx.payments.get_txn(t["txn"])["chat_id"]]))
        again = self.create()
        self.assertEqual(again["txn"]["txn"], t["txn"])            # same pending plan is reused
        self.assertEqual(self.create("nope")["code"], "bad_plan")

    def test_upi_rotation_after_money_received(self):
        t1 = self.create("m1")["txn"]
        first = self.ctx.payments.get_txn(t1["txn"])["upi_id"]
        d2 = AppClient(self.web)
        t2 = self.create("m1", d2)["txn"]
        second = self.ctx.payments.get_txn(t2["txn"])["upi_id"]
        self.assertNotEqual(first, second)                          # un-paid txns also spread out
        owner = self.ctx.payments.get_txn(t1["txn"])["chat_id"]
        self.ctx.payments.verify(t1["txn"], owner)                  # first UPI received money
        d3, d4 = AppClient(self.web), AppClient(self.web)
        t3 = self.create("y1", d3)["txn"]
        t4 = self.create("y1", d4)["txn"]
        ups = [self.ctx.payments.get_txn(x["txn"])["upi_id"] for x in (t3, t4)]
        self.assertEqual(ups[0], second)                            # the one that has not received money goes next
        self.ctx.payments.verify(t3["txn"], "admin")
        t5 = self.create("m1", AppClient(self.web))["txn"]
        self.assertEqual(self.ctx.payments.get_txn(t5["txn"])["upi_id"], first)   # least successes after 1-1

    def test_no_upi_available(self):
        for u in (self.upi_a, self.upi_b):
            self.admin.put(f"/upi/{u['id']}", {"active": False})
        self.assertEqual(self.create()["code"], "no_upi")

    def test_full_flow_submit_verify_by_owner(self):
        t = self.create("m3")["txn"]
        rec = self.ctx.payments.get_txn(t["txn"])
        owner = rec["chat_id"]
        img = base64.b64encode(png_bytes()).decode()
        bad = [{"utr": "123", "image": img}, {"utr": "412345678901", "image": base64.b64encode(b"x" * 5000).decode()},
               {"utr": "412345678901", "image": "!!!"}]
        for b in bad:
            st, out = self.u.call("/pay/submit", {"txn": t["txn"], **b})
            self.assertFalse(out["ok"], b["utr"])
        st, out = self.u.call("/pay/submit", {"txn": t["txn"], "utr": "412345678901", "image": img})
        self.assertTrue(out["ok"])
        self.assertTrue(out["txn"]["proof"])
        photos = self.chats("sendPhoto")
        self.assertEqual(sorted(set(photos)), sorted({ADMIN_CHAT, owner}))
        self.assertEqual(len(photos), 4)                             # proof + QR for admin and owner
        self.assertEqual(self.ctx.payments.get_txn(t["txn"])["proof_file"], "FID1")
        # duplicate proof on second submit / reuse of UTR and screenshot on another txn
        self.assertEqual(self.u.call("/pay/submit", {"txn": t["txn"], "utr": "412345678901", "image": img})[1]["code"], "dup")
        other = AppClient(self.web)
        t2 = self.create("m1", other)["txn"]
        self.assertEqual(other.call("/pay/submit", {"txn": t2["txn"], "utr": "412345678901", "image": base64.b64encode(png_bytes(500, 500)).decode()})[1]["code"], "dup_utr")
        self.assertEqual(other.call("/pay/submit", {"txn": t2["txn"], "utr": "999999999999", "image": img})[1]["code"], "dup_image")
        # someone else's chat cannot verify
        r = self.ctx.payments.verify(t["txn"], "5555")
        self.assertIn("not allowed", r["text"])
        self.assertFalse(self.ctx.payments.premium_status(self.u.dev)["active"])
        # owner sends /verify through the Telegram webhook
        upd = {"message": {"chat": {"id": int(owner)}, "text": f"/verify {t['txn']}"}}
        r = self.web.post("/tg/whsec", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "whsec"})
        self.assertEqual(r.status_code, 200)
        st, s = self.u.call("/pay/status", {"txn": t["txn"]})
        self.assertEqual(s["txn"]["status"], "success")
        self.assertTrue(s["premium"]["active"])
        self.assertEqual(s["premium"]["plan"], "3 Months")
        self.assertEqual(s["premium"]["days_left"], 90)
        st, boot = self.u.call("/boot", {"ver": 1})
        self.assertTrue(boot["premium"]["active"])
        # verify twice is harmless, premium not double credited
        self.ctx.payments.verify(t["txn"], "admin")
        self.assertEqual(self.ctx.payments.premium_status(self.u.dev)["days_left"], 90)
        # other devices unaffected / cannot read this txn
        self.assertEqual(other.call("/pay/status", {"txn": t["txn"]})[1]["code"], "not_found")

    def test_fail_command_cancels_subscription(self):
        t = self.create("m1")["txn"]
        owner = self.ctx.payments.get_txn(t["txn"])["chat_id"]
        self.ctx.payments.verify(t["txn"], "admin")
        self.assertTrue(self.ctx.payments.premium_status(self.u.dev)["active"])
        self.app.sent.clear()
        upd = {"message": {"chat": {"id": int(owner)}, "text": f"/fail {t['txn']} fake screenshot, no money"}}
        self.web.post("/tg/whsec", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "whsec"})
        rec = self.ctx.payments.get_txn(t["txn"])
        self.assertEqual((rec["status"], rec["fail_reason"]), ("failed", "fake screenshot, no money"))
        self.assertFalse(self.ctx.payments.premium_status(self.u.dev)["active"])
        self.assertIn(ADMIN_CHAT, self.chats())
        up = self.ctx.db.get(f"upi/{rec['upi_key']}")
        self.assertEqual((up["success_count"], up["amount_total"], up["failed_count"]), (0, 0, 1))
        self.assertEqual(self.ctx.db.get("earn"), None)

    def test_txn_expires_after_10_minutes_but_proof_waits(self):
        t1 = self.create("m1")["txn"]
        c2 = AppClient(self.web)
        t2 = self.create("m1", c2)["txn"]
        c2.call("/pay/submit", {"txn": t2["txn"], "utr": "111122223333", "image": base64.b64encode(png_bytes()).decode()})
        for tid in (t1["txn"], t2["txn"]):
            rec = self.ctx.payments.get_txn(tid)
            rec["expires_at"] = int(time.time()) - 1
            self.ctx.payments._save(rec)
        st, s = self.u.call("/pay/status", {"txn": t1["txn"]})
        self.assertEqual(s["txn"]["status"], "failed")
        self.assertIn("10 minutes", s["txn"]["reason"])
        self.assertEqual(self.ctx.payments.get_txn(t2["txn"])["status"], "pending")   # waiting on receiver
        late = self.u.call("/pay/submit", {"txn": t1["txn"], "utr": "222233334444", "image": base64.b64encode(png_bytes()).decode()})[1]
        self.assertEqual(late["code"], "expired")
        # proof txn auto-fails after 24 h
        rec = self.ctx.payments.get_txn(t2["txn"])
        rec["submitted_at"] -= 25 * 3600
        self.ctx.payments._save(rec)
        self.ctx.payments.expire_due()
        self.assertEqual(self.ctx.payments.get_txn(t2["txn"])["status"], "failed")

    def test_limits_on_pending(self):
        ids = {self.create(p)["txn"]["txn"] for p in ("m1", "m3")}
        self.assertEqual(len(ids), 2)
        self.assertEqual(self.create("y1")["code"], "too_many")

    def test_premium_expiry_revoke_renew_admin(self):
        dev = self.u.dev
        self.ctx.payments.grant(dev, 30, "1 Month", "T1", 25)
        self.assertEqual(self.admin.post(f"/premium/{dev}/renew", {"days": 10}).get_json()["premium"]["status"], "active")
        self.assertEqual(self.ctx.payments.premium_status(dev)["days_left"], 40)
        self.assertTrue(self.admin.post(f"/premium/{dev}/revoke", {"reason": "abuse"}).get_json()["ok"])
        self.assertFalse(self.ctx.payments.premium_status(dev)["active"])
        self.admin.post(f"/premium/{dev}/grant", {"days": 5, "plan": "Gift"})
        self.assertEqual(self.ctx.payments.premium_status(dev)["plan"], "Gift")
        self.assertEqual(self.admin.post(f"/premium/{dev}/renew", {"days": 0}).status_code, 400)
        rec = self.ctx.db.get(f"premium/{dev}")
        self.ctx.db.put(f"premium/{dev}/expires", int(time.time()) - 5)
        self.assertEqual(self.ctx.payments.expire_premiums(), 1)
        self.assertEqual(self.ctx.db.get(f"premium/{dev}/status"), "expired")
        st, boot = self.u.call("/boot", {})
        self.assertFalse(boot["premium"]["active"])

    def test_admin_reports(self):
        t1 = self.create("m1")["txn"]
        c2 = AppClient(self.web)
        t2 = self.create("y1", c2)["txn"]
        c3 = AppClient(self.web)
        t3 = self.create("m3", c3)["txn"]
        self.admin.post(f"/txns/{t1['txn']}/verify")
        self.admin.post(f"/txns/{t2['txn']}/fail", {"reason": "fake"})
        td = today_str()
        r = self.admin.get(f"/txns?from={td}&to={td}").get_json()
        self.assertEqual(r["counts"], {"total": 3, "success": 1, "failed": 1, "pending": 1, "amount": 25})
        self.assertEqual(self.admin.get(f"/txns?status=success&from={td}&to={td}").get_json()["total"], 1)
        self.assertEqual(self.admin.get(f"/txns?q={t3['txn']}&from={td}&to={td}").get_json()["total"], 1)
        rep = self.admin.get(f"/upi/report?from={td}&to={td}").get_json()
        tot = {k: sum(x[k] for x in rep["range"]) for k in ("generated", "success", "failed", "pending", "amount")}
        self.assertEqual(tot, {"generated": 3, "success": 1, "failed": 1, "pending": 1, "amount": 25})
        pl = self.admin.get("/premium?filter=today").get_json()
        self.assertEqual(pl["total"], 1)
        self.assertEqual((pl["summary"]["today"], pl["summary"]["all"]), ({"count": 1, "amount": 25}, {"count": 1, "amount": 25}))
        ear = self.admin.get(f"/premium/earnings?from={td}&to={td}").get_json()
        self.assertEqual(ear["total"], 25)
        self.assertEqual(self.admin.get("/premium?filter=yesterday").get_json()["total"], 0)
        self.assertEqual(self.admin.get("/premium?status=expired&filter=all").get_json()["total"], 0)

    def test_plans_editable(self):
        r = self.admin.put("/settings/premium", {"plans": [{"id": "w1", "name": "Week", "days": 7, "price": 9}], "features": ["x"]})
        self.assertEqual(r.status_code, 200)
        out = self.create("w1")
        self.assertEqual(out["txn"]["amount"], 9)
        self.assertEqual(self.admin.put("/settings/premium", {"plans": []}).status_code, 400)
        self.assertEqual(self.admin.put("/settings/premium", {"plans": [{"id": "a b", "days": 1, "price": 1}]}).status_code, 400)
        self.assertEqual(self.admin.put("/settings/nope", {}).status_code, 404)

    def test_bot_help_and_pending(self):
        self.create("m1")
        for text in ("/start", "/pending", "/verify", "/status LYS1"):
            self.app.sent.clear()
            self.web.post("/tg/whsec", json={"message": {"chat": {"id": 7001001}, "text": text}},
                          headers={"X-Telegram-Bot-Api-Secret-Token": "whsec"})
            self.assertTrue(self.app.sent, text)


class TestDashboard(Base):
    def test_dashboard_and_lists(self):
        for i in range(30):
            AppClient(self.web).call("/boot", {"ver": 1, "info": {"model": f"M{i}", "brand": "B"}})
        c = AppClient(self.web)
        c.call("/boot", {"ver": 1})
        c.call("/boot", {"ver": 1})
        for t, a in (("interstitial", "fetch"), ("interstitial", "fetch"), ("rewarded", "watch"), ("interstitial", "page_home")):
            c.call("/track", {"type": t, "platform": "startio", "action": a})
        self.assertEqual(c.call("/track", {"type": "interstitial", "platform": "monetag", "action": "fetch"})[1]["code"], "bad")
        s = self.admin.get("/dashboard").get_json()
        self.assertEqual((s["today"]["new_user"], s["all"]["new_user"], s["today"]["active"]), (31, 31, 31))
        self.assertEqual((s["today"]["ad_interstitial_startio_fetch"], s["today"]["ad_rewarded_startio_watch"]), (2, 1))
        self.assertEqual(s["today"]["ad_interstitial_startio_other"], 1)
        self.assertEqual(s["users_total"], 31)
        td = today_str()
        p1 = self.admin.get(f"/events?kind=new_user&from={td}&to={td}&limit=25").get_json()
        self.assertEqual((len(p1["items"]), bool(p1["next"])), (25, True))
        p2 = self.admin.get(f"/events?kind=new_user&from={td}&to={td}&limit=25&cursor={p1['next']}").get_json()
        self.assertEqual((len(p2["items"]), p2["next"]), (6, ""))
        ids = {i["id"] for i in p1["items"]} | {i["id"] for i in p2["items"]}
        self.assertEqual(len(ids), 31)
        self.assertTrue(p1["items"][0].get("model") is not None)
        top = self.admin.get("/top-users").get_json()["items"]
        self.assertEqual(len(top), 31)
        d = self.admin.get(f"/user/{c.dev}").get_json()
        self.assertEqual(len(d["logs"]), 2)               # every login stored
        self.assertEqual(d["user"]["opens"], 2)
        self.assertEqual(self.admin.get("/user/zz").status_code, 400)
        self.assertEqual(self.admin.get("/events?kind=../x").status_code, 400)

    def test_logs_recorded(self):
        self.admin.post("/blocks", {"domains": "x.com", "message": "m"})
        logs = self.admin.get("/logs?kind=admin").get_json()
        self.assertTrue(any(l["action"] == "block:add" for l in logs["items"]))
        self.assertTrue(self.admin.get("/logs?kind=login").get_json()["total"] >= 1)

    def test_settings_roundtrip_and_version_gate(self):
        r = self.admin.put("/settings/app", {"version_code": 5, "min_version_code": 3, "update_url": "https://t.me/lysandraapp"})
        self.assertEqual(r.status_code, 200)
        st, out = self.u.call("/boot", {"ver": 2})
        self.assertTrue(out["update"]["required"])
        st, out = self.u.call("/boot", {"ver": 5})
        self.assertFalse(out["update"]["available"])
        self.assertNotIn("terms_html", json.dumps(out))     # legal only via /legal, not at boot
        st, leg = self.u.call("/legal", {})
        self.assertIn("Terms", leg["terms"])
        self.assertNotIn("monetag", json.dumps(self.admin.get("/settings").get_json()).lower())
        self.assertNotIn("firebaseio", json.dumps(out))     # database url is never exposed


class TestPlansAndTracking(Base):
    def setUp(self):
        super().setUp()
        self.ctx.extractors.fallback.extract = lambda url: FAKE
        self.admin.put("/settings/limits", {"free_daily_downloads": 2, "free_daily_watch": 2, "fetch_per_minute": 100})

    def fetch(self, c=None):
        c = c or self.u
        return c.call("/fetch", TestContent._fp("abc.com/x"))[1]

    def test_default_free_limit_is_two_and_editable(self):
        c = AppClient(self.web)
        self.assertEqual(self.ctx.cfg.get("limits", "free_daily_downloads"), 2)
        self.admin.put("/settings/limits", {"free_daily_downloads": 4, "free_daily_watch": 6})
        q = c.call("/boot", {"ver": 1})[1]["quota"]
        self.assertEqual((q["dl_limit"], q["w_limit"]), (4, 6))
        self.admin.put("/settings/limits", {"free_daily_downloads": 0})
        f = self.fetch(c)
        self.assertFalse(f["quota"]["can_download"])
        self.assertEqual(c.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})[1]["code"], "limit")

    def test_one_month_limited_three_month_unlimited(self):
        m1 = AppClient(self.web); m3 = AppClient(self.web)
        self.ctx.payments.grant(m1.dev, 30, "1 Month", "T", 25, plan_id="m1")
        self.ctx.payments.grant(m3.dev, 90, "3 Months", "T", 49, plan_id="m3")
        q1 = self.fetch(m1)["quota"]
        self.assertEqual((q1["plan"], q1["free"], q1["dl_limit"], q1["w_limit"], q1["dl_unlimited"]), ("1 Month", False, 10, 15, False))
        q3 = self.fetch(m3)["quota"]
        self.assertEqual((q3["plan"], q3["dl_unlimited"], q3["w_unlimited"], q3["can_download"]), ("3 Months", True, True, True))
        # 1 Month plan is enforced server side too
        self.admin.put("/settings/premium", {"plans": [{"id": "m1", "name": "1 Month", "days": 30, "price": 25,
                                                           "downloads_per_day": 1, "watch_per_day": 1}, {"id": "m3", "name": "3 Months", "days": 90, "price": 49}], "features": []})
        f = self.fetch(m1)
        self.assertTrue(m1.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})[1]["ok"])
        self.assertEqual(m1.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "v720_1"})[1]["code"], "limit")

    def test_overview_lists_edit_renew_revoke(self):
        devs = {}
        for pid, days in (("m1", 30), ("m3", 90), ("y1", 365), ("m1", 30)):
            c = AppClient(self.web); c.call("/boot", {"ver": 1})
            self.ctx.payments.grant(c.dev, days, pid, "T", 1, plan_id=pid)
            devs.setdefault(pid, []).append(c.dev)
        AppClient(self.web).call("/boot", {"ver": 1})                      # one free user
        td = today_str()
        ov = self.admin.get(f"/premium/overview?from={td}&to={td}").get_json()
        self.assertEqual((ov["plans"]["m1"]["active"], ov["plans"]["m3"]["active"], ov["plans"]["y1"]["active"]), (2, 1, 1))
        self.assertEqual(ov["plans"]["m1"]["purchased"]["today"], 2)
        self.assertEqual((ov["free_users"], ov["active_total"]), (1, 4))
        # expiry: move one 1-Month subscriber's expiry to yesterday, one 3-Month to today
        yest = int(time.time()) - 86400
        r = self.admin.post(f"/premium/{devs['m1'][0]}/edit", {"expires": yest})
        self.assertEqual(r.get_json()["premium"]["status"], "expired")
        self.admin.post(f"/premium/{devs['m3'][0]}/edit", {"expires": int(time.time()) + 600})
        ov = self.admin.get(f"/premium/overview?from={td}&to={td}").get_json()
        self.assertEqual(ov["plans"]["m1"]["expiring"]["yesterday"], 1)
        self.assertEqual(ov["plans"]["m3"]["expiring"]["today"], 1)
        self.assertEqual(ov["plans"]["m1"]["active"], 1)
        # drill-down lists are paginated
        j = self.admin.get(f"/premium/users?mode=expiring&plan=m1&period=yesterday&from={td}&to={td}").get_json()
        self.assertEqual((j["total"], j["items"][0]["dev"]), (1, devs["m1"][0]))
        j = self.admin.get("/premium/users?mode=active&plan=m1&per=5").get_json()
        self.assertEqual(j["total"], 1)
        j = self.admin.get(f"/premium/users?mode=purchased&plan=m1&period=today&from={td}&to={td}&per=1&page=2").get_json()
        self.assertEqual((j["total"], len(j["items"])), (2, 1))
        j = self.admin.get("/premium/users?mode=free").get_json()
        self.assertEqual(j["total"], 2)       # the never-paid user + the expired one
        # edit plan + dates, renew, revoke
        d0 = devs["y1"][0]
        e = self.admin.post(f"/premium/{d0}/edit", {"plan_id": "m3", "started": int(time.time()) - 5 * 86400,
                                                       "expires": int(time.time()) + 30 * 86400}).get_json()["premium"]
        self.assertEqual((e["plan_id"], e["status"]), ("m3", "active"))
        self.assertEqual(self.admin.post(f"/premium/{d0}/edit", {"plan_id": "zzz"}).status_code, 400)
        self.admin.post(f"/premium/{d0}/renew", {"days": 10})
        self.assertGreaterEqual(self.ctx.payments.premium_status(d0)["days_left"], 39)
        self.admin.post(f"/premium/{d0}/revoke", {})
        self.assertFalse(self.ctx.payments.premium_status(d0)["active"])
        ov = self.admin.get(f"/premium/overview?from={td}&to={td}").get_json()
        self.assertEqual(ov["plans"]["m3"]["active"], 1)
        # grant by plan from the panel
        c = AppClient(self.web); c.call("/boot", {"ver": 1})
        g = self.admin.post(f"/premium/{c.dev}/grant", {"days": 30, "plan_id": "m3"}).get_json()["premium"]
        self.assertEqual((g["plan_id"], g["plan_name"]), ("m3", "3 Months"))


class TestQR(unittest.TestCase):
    def test_qr_decodes(self):
        import cv2, numpy as np
        from lysandra import qr
        uri = "upi://pay?pa=alice@okaxis&pn=Alice&am=49.00&cu=INR&tn=Lysandra%20LYS1234567890"
        img = cv2.imdecode(np.frombuffer(qr.make_png(uri), np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(cv2.QRCodeDetectorAruco().detectAndDecode(img)[0], uri)


class TestMemoryDB(unittest.TestCase):
    def test_semantics(self):
        db = MemoryDB()
        db.increment("a/b/c", 2); db.increment("a/b/c", 3)
        self.assertEqual(db.get("a/b/c"), 5)
        db.put("x/1", {"k": 1}); db.put("x/2", {"k": 2}); db.put("x/3", {"k": 3})
        self.assertEqual(list(db.get("x", order_by_key=True, start_at="2", end_at="3")), ["2", "3"])
        self.assertEqual(list(db.get("x", order_by_key=True, limit_first=1)), ["1"])
        db.delete("x/1"); db.delete("x/2"); db.delete("x/3")
        self.assertIsNone(db.get("x"))
        db.patch("p", {"a": 1, "b": {".sv": {"increment": 4}}})
        self.assertEqual(db.get("p"), {"a": 1, "b": 4})


if __name__ == "__main__":
    unittest.main(verbosity=1)
