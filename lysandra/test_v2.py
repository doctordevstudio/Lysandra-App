import base64
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from lysandra import netutil  # noqa: E402
from lysandra.extractors import direct  # noqa: E402
from lysandra.util import today_str  # noqa: E402
from lysandra.videos import duration_text, parse_duration, parse_sources, source_type  # noqa: E402
from tests.helpers import AppClient, png_bytes  # noqa: E402
from tests.test_backend import Admin, Base, TestContent, make_app  # noqa: E402

VID = {"title": "Big Movie", "description": "A story", "thumbnail_url": "https://i.test/p.jpg", "preview_url": "https://i.test/p.mp4",
       "duration": "1:35:00", "tags": "action, drama , ", "video_link": "https://cdn.test/movie/master.m3u8", "category": "bollywood",
       "year": 2024, "rating": 7.8, "sources": "Server 2 | https://cdn.test/alt.mp4 | HD\nEmbed | https://embed.test/p/1 | | embed\nbad | ftp://x"}


class TestVideoLibrary(Base):
    def test_helpers(self):
        self.assertEqual((parse_duration("1:35:00"), parse_duration("95"), parse_duration("12:30"), parse_duration("x")), (5700, 5700, 750, 0))
        self.assertEqual((duration_text(5700), duration_text(750), duration_text(0)), ("1h 35m", "12m", ""))
        self.assertEqual([source_type(u) for u in ("https://a/x.m3u8?t=1", "https://a/x.mp4", "https://a/watch?v=1")], ["hls", "direct", "page"])
        self.assertEqual(source_type("https://a/x.mp4", True), "embed")
        self.assertEqual(len(parse_sources(VID["sources"])), 2)

    def test_admin_crud_pagination_search_and_human_timestamp(self):
        for i in range(25):
            r = self.admin.post("/videos", {**VID, "title": f"Movie {i:02d}", "category": "video" if i % 2 else "series", "tags": "tag%d" % i})
            self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["created_human"].endswith("IST"))
        self.assertEqual(self.admin.post("/videos", {**VID, "title": ""}).status_code, 400)
        self.assertEqual(self.admin.post("/videos", {**VID, "video_link": "ftp://x"}).status_code, 400)
        p1 = self.admin.get("/videos?page=1&per=12").get_json()
        self.assertEqual((p1["total"], len(p1["items"]), p1["pages"]), (25, 12, 3))
        self.assertEqual(len(self.admin.get("/videos?page=3&per=12").get_json()["items"]), 1)
        self.assertEqual(self.admin.get("/videos?q=movie 07").get_json()["total"], 1)
        self.assertEqual(self.admin.get("/videos?q=tag2").get_json()["total"], 6)          # tags match too: tag2, tag20..tag24
        self.assertEqual(self.admin.get("/videos?category=series").get_json()["total"], 13)
        vid = p1["items"][0]["id"]
        up = self.admin.put(f"/videos/{vid}", {"title": "Renamed", "enabled": False}).get_json()
        self.assertEqual((up["title"], up["enabled"], up["duration_sec"]), ("Renamed", False, 5700))
        self.assertEqual(self.admin.put("/videos/nope", {"title": "x"}).status_code, 404)
        self.admin.delete(f"/videos/{vid}")
        self.assertEqual(self.admin.get("/videos").get_json()["total"], 24)

    def test_catalog_pages_of_20_hides_links_and_sources_on_demand(self):
        for i in range(45):
            self.admin.post("/videos", {**VID, "title": f"T{i:02d}", "category": "hollywood"})
        self.admin.post("/videos", {**VID, "title": "Hidden", "category": "hollywood", "enabled": False})
        self.admin.post("/videos", {**VID, "title": "Channel", "category": "livetv"})
        st, p1 = self.u.call("/catalog", {"kind": "hollywood", "page": 1, "limit": 20})
        self.assertEqual((len(p1["items"]), p1["pages"], p1["total"]), (20, 3, 45))
        st, p3 = self.u.call("/catalog", {"kind": "hollywood", "page": 3, "limit": 20})
        self.assertEqual(len(p3["items"]), 5)
        item = p1["items"][0]
        self.assertNotIn("video_link", item)
        self.assertNotIn("cdn.test", str(p1))
        self.assertEqual((item["kind"], item["sources_count"], item["duration_text"]), ("hollywood", 3, "1h 35m"))
        st, s = self.u.call("/catalog", {"kind": "hollywood", "q": "t07"})
        self.assertEqual(s["total"], 1)
        self.assertEqual(self.u.call("/catalog", {"kind": "livetv", "limit": 100})[1]["total"], 1)
        self.assertEqual(self.u.call("/catalog", {"kind": "nonsense"})[1]["code"], "bad")
        st, v = self.u.call("/video", {"id": item["id"]})
        types = [x["type"] for x in v["sources"]]
        self.assertEqual(types, ["hls", "direct", "embed"])          # HLS first = recommended
        self.assertEqual(self.u.call("/video", {"id": "nope"})[1]["code"], "not_found")

    def test_watch_and_download_stats_per_category(self):
        a = self.admin.post("/videos", {**VID, "category": "bollywood"}).get_json()
        b = self.admin.post("/videos", {**VID, "title": "Show", "category": "series"}).get_json()
        self.ctx.extractors.direct.extract = lambda url: {"title": "x", "thumbnail": "", "duration": 60, "platform": "Direct link", "relay": False,
            "direct": True, "formats": [dict(kind="av", fid="auto", label="Auto", quality="Auto", ext="mp4", mime="video/mp4", size=0, url="https://cdn.test/m.m3u8",
                                                headers={}, audio_only=False, hls=True, height=0)]}
        self.admin.put("/settings/limits", {"free_daily_downloads": 5, "free_daily_watch": 5, "fetch_per_minute": 50})
        for vid, watch in ((a["id"], True), (a["id"], True), (a["id"], False), (b["id"], True)):
            f = self.u.call("/fetch", {**TestContent._fp("cdn.test/movie/master.m3u8"), "vid": vid})[1]
            self.assertTrue(f["direct"])
            ok = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "auto", "watch": watch})[1]
            self.assertTrue(ok["ok"] and ok["hls"])
        td = today_str()
        st = self.admin.get(f"/videos/stats?from={td}&to={td}").get_json()
        row = {c["cat"]: c for c in st["categories"]}
        self.assertEqual((row["bollywood"]["today"], row["series"]["today"]), ({"watch": 2, "download": 1}, {"watch": 1, "download": 0}))
        self.assertEqual((st["total"]["all"], st["total"]["range"]), ({"watch": 3, "download": 1}, {"watch": 3, "download": 1}))
        item = [v for v in self.admin.get("/videos").get_json()["items"] if v["id"] == a["id"]][0]
        self.assertEqual((item["watch_count"], item["download_count"]), (2, 1))


class TestFetchModel(Base):
    def test_formats_tabs_merge_authorize_two_parts_one_quota(self):
        info = {"title": "Clip", "duration": 100, "extractor_key": "Youtube", "thumbnails": [{"url": "https://t/small.jpg", "height": 90, "width": 120},
                {"url": "https://t/big.jpg", "height": 720, "width": 1280}], "formats": [
            {"url": "https://c/v.mp4", "protocol": "https", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080, "format_id": "137", "filesize": 900},
            {"url": "https://c/a.m4a", "protocol": "https", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 128, "format_id": "140", "filesize": 100}]}
        y = self.ctx.extractors.fallback
        y.run = lambda url, extra=None: info
        self.admin.put("/settings/limits", {"free_daily_downloads": 2, "free_daily_watch": 2, "fetch_per_minute": 50})
        f = self.u.call("/fetch", TestContent._fp("vimeo.com/123"))[1]
        self.assertEqual(f["thumbnail"], "https://t/big.jpg")              # best thumbnail is chosen when `thumbnail` is missing
        self.assertEqual([(x["kind"], x["quality"]) for x in f["formats"]], [("merge", "1080p"), ("video", "1080p"), ("audio", "128kbps")])
        m = f["formats"][0]
        self.assertEqual((m["size"], f["duration"]), (1000, 100))
        a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": m["fid"]})[1]
        self.assertTrue(a["ok"] and a["merge"])
        self.assertEqual([(p["role"], p["url"]) for p in a["parts"]], [("video", "https://c/v.mp4"), ("audio", "https://c/a.m4a")])
        self.assertEqual(a["quota"]["dl_remaining"], 1)                      # merge costs ONE download
        self.assertEqual(self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": m["fid"], "watch": True})[1]["code"], "bad")  # merge can't be streamed

    def test_direct_hls_and_mp4_links(self):
        calls = []
        def fake(method, url, headers=None, max_bytes=2_000_000, **kw):
            calls.append((method, url))
            if url.endswith(".m3u8"):
                return 200, {}, (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\nlow.m3u8\n"
                                 b"#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720\nhi.m3u8\n"), url
            return 200, {"Content-Length": "123456"}, b"", url
        direct.safe_request = fake
        f = self.u.call("/fetch", TestContent._fp("https://cdn.test/live/master.m3u8"))[1]
        self.assertTrue(f["direct"])
        self.assertEqual([(x["fid"], x["quality"]) for x in f["formats"]], [("auto", "Auto"), ("h0", "720p"), ("h1", "360p")])
        a = self.u.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "h0", "watch": True})[1]
        self.assertEqual((a["url"], a["hls"]), ("https://cdn.test/live/hi.m3u8", True))
        g = self.u.call("/fetch", TestContent._fp("https://cdn.test/files/My_Movie-2024.mp4"))[1]
        self.assertEqual((g["title"], g["formats"][0]["size"], g["formats"][0]["kind"]), ("My Movie 2024", 123456, "av"))
        self.assertEqual(self.u.call("/fetch", TestContent._fp("https://cdn.test/a.mp3"))[1]["formats"][0]["kind"], "audio")

    def test_ssrf_guard(self):
        for host in ("localhost", "127.0.0.1", "192.168.0.5", "10.0.0.1", "169.254.169.254", "foo.internal", "::1"):
            self.assertFalse(netutil.host_is_public(host), host)
        with self.assertRaises(netutil.UnsafeURL):
            netutil.check_url("http://127.0.0.1:8080/x.m3u8")
        with self.assertRaises(netutil.UnsafeURL):
            netutil.check_url("file:///etc/passwd")


class TestCloneProtection(Base):
    def test_same_hardware_shares_one_account(self):
        drm = "ab12cd34" * 4
        orig, clone = AppClient(self.web), AppClient(self.web)
        orig.call("/boot", {"ver": 1, "drm": drm})
        self.ctx.payments.grant(self.ctx.canon(orig.dev), 30, "3 Months", plan_id="m3")
        out = clone.call("/boot", {"ver": 1, "drm": drm})[1]          # parallel space / dual app copy of the same phone
        self.assertTrue(out["premium"]["active"])                       # shares the premium of the original
        self.assertEqual(self.ctx.canon(clone.dev), orig.dev)
        other = AppClient(self.web)
        self.assertFalse(other.call("/boot", {"ver": 1, "drm": "99" * 16})[1]["premium"]["active"])   # a different phone is unaffected

    def test_free_quota_is_shared_between_clones(self):
        self.ctx.extractors.fallback.extract = lambda url: {"title": "x", "thumbnail": "", "duration": 1, "platform": "W", "relay": False, "formats": [
            dict(kind="av", fid="f1", label="360p", quality="360p", ext="mp4", mime="video/mp4", size=1, url="https://c/x.mp4", headers={}, audio_only=False, height=360)]}
        self.admin.put("/settings/limits", {"free_daily_downloads": 2, "free_daily_watch": 5, "fetch_per_minute": 50})
        drm = "ef56ab78" * 4
        a, b = AppClient(self.web), AppClient(self.web)
        a.call("/boot", {"ver": 1, "drm": drm}); b.call("/boot", {"ver": 1, "drm": drm})
        for c in (a, b):
            f = c.call("/fetch", TestContent._fp("vimeo.com/9"))[1]
            self.assertTrue(c.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "f1"})[1]["ok"])
        f = b.call("/fetch", TestContent._fp("vimeo.com/9"))[1]
        self.assertEqual(b.call("/authorize", {"fetch_id": f["fetch_id"], "fid": "f1"})[1]["code"], "limit")   # no fresh quota via the clone

    def test_client_reported_clone_signals_are_refused_and_counted(self):
        c = AppClient(self.web)
        out = c.call("/boot", {"ver": 1, "clone": ["user:10"]})[1]
        self.assertEqual((out["ok"], out["code"]), (False, "env"))
        self.assertEqual(self.admin.get("/dashboard").get_json()["today"]["clone_blocked"], 1)

    def test_admin_can_unlink_and_sees_linked_devices(self):
        drm = "12ab34cd" * 4
        a, b = AppClient(self.web), AppClient(self.web)
        a.call("/boot", {"ver": 1, "drm": drm}); b.call("/boot", {"ver": 1, "drm": drm})
        d = self.admin.get(f"/user/{b.dev}").get_json()
        self.assertEqual((d["canon"], d["linked"]), (a.dev, [b.dev]))
        self.admin.post(f"/user/{b.dev}/unlink")
        self.assertEqual(self.admin.get(f"/user/{b.dev}").get_json()["canon"], b.dev)


class TestUserAdmin(Base):
    def test_search_edit_override_delete(self):
        u = AppClient(self.web)
        u.call("/boot", {"ver": 1, "info": {"model": "Redmi Note 12", "brand": "Xiaomi"}})
        self.assertEqual(self.admin.get(f"/users/search?q={u.dev[:10]}").get_json()["items"][0]["id"], u.dev)
        self.assertEqual(self.admin.get(f"/users/search?q={u.dev}").get_json()["items"][0]["id"], u.dev)
        self.assertEqual(self.admin.get("/users/search?q=redmi").get_json()["items"][0]["id"], u.dev)
        self.assertEqual(self.admin.get("/users/search?q=zz").get_json()["items"], [])
        d = self.admin.put(f"/user/{u.dev}", {"notes": "VIP", "model": "Edited", "fetch_ok": 7, "dl_used": 1, "w_used": 3,
                                              "override": {"dl": 9, "w": 20}}).get_json()
        self.assertEqual((d["user"]["notes"], d["user"]["model"], d["user"]["fetch_ok"]), ("VIP", "Edited", 7))
        self.assertEqual((d["quota_today"], d["override"]), ({"dl_used": 1, "w_used": 3}, {"dl": 9, "w": 20}))
        q = u.call("/premium", {})[1]["quota"]
        self.assertEqual((q["dl_limit"], q["dl_remaining"], q["w_limit"], q["w_remaining"]), (9, 8, 20, 17))
        self.assertEqual(self.admin.put(f"/user/{'a' * 32}", {"notes": "x"}).status_code, 404)
        self.admin.put(f"/user/{u.dev}", {"override": {}})
        self.ctx.users._ov.clear()
        self.assertEqual(u.call("/premium", {})[1]["quota"]["dl_limit"], 2)
        self.ctx.payments.grant(u.dev, 30, "1 Month", plan_id="m1")
        self.admin.delete(f"/user/{u.dev}?premium=1")
        self.assertEqual(self.admin.get(f"/users/search?q={u.dev}").get_json()["items"], [])
        self.assertIsNone(self.ctx.db.get(f"premium/{u.dev}"))


class TestSiteAndRateLimit(Base):
    def test_landing_pages_and_dmca(self):
        r = self.web.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for needle in ("Download APK", "Frequently asked", "How to use", "id=\"drawer\"", "©️Copyright by Dr. Dev || Dr. Hamza 2026 All Rights Reserved.",
                       "RECOMMENDED", "₹49", "Play Protect"):
            self.assertIn(needle, html, needle)
        for path, text in (("/privacy", "Privacy Policy"), ("/terms", "Terms"), ("/dmca", "DMCA"), ("/support", "Customer Support"), ("/developer", "Dr. Dev")):
            rr = self.web.get(path)
            self.assertEqual(rr.status_code, 200, path)
            self.assertIn(text, rr.get_data(as_text=True))
        self.admin.put("/settings/legal", {"terms_html": "<p>T</p>", "privacy_html": "<p>P</p>", "dmca_html": "<h2>My DMCA</h2>"})
        self.assertIn("My DMCA", self.web.get("/dmca").get_data(as_text=True))
        self.assertEqual(self.u.call("/legal", {})[1]["dmca"], "<h2>My DMCA</h2>")
        self.assertIn("My DMCA", self.u.call("/home", {})[1]["legal"]["dmca"])
        self.assertEqual(self.web.get("/assets/site.css").status_code, 200)
        self.assertEqual(self.web.get("/robots.txt").status_code, 200)

    def test_landing_editable_from_admin(self):
        cfg = self.admin.get("/settings").get_json()["config"]["landing"]
        cfg["hero_title"] = "My custom headline"; cfg["faqs"] = ["Q one?|A one."]
        self.assertEqual(self.admin.put("/settings/landing", cfg).status_code, 200)
        html = self.web.get("/").get_data(as_text=True)
        self.assertIn("My custom headline", html)
        self.assertIn("A one.", html)
        cfg["apk_url"] = "ftp://bad"
        self.assertEqual(self.admin.put("/settings/landing", cfg).status_code, 400)

    def test_apk_download_streams_with_apk_headers(self):
        import lysandra.site as site
        class Up:
            status_code, headers = 200, {"Content-Type": "application/octet-stream", "Content-Length": "6"}
            def iter_content(self, n): yield b"APKDAT"
            def close(self): pass
        site.requests.get = lambda *a, **k: Up()
        r = self.web.get("/download")
        self.assertEqual((r.status_code, r.data), (200, b"APKDAT"))
        self.assertEqual(r.headers["Content-Type"], "application/vnd.android.package-archive")
        self.assertIn("attachment; filename=\"Lysandra-1.0.apk\"", r.headers["Content-Disposition"])
        class Html(Up):
            headers = {"Content-Type": "text/html"}
        site.requests.get = lambda *a, **k: Html()
        r = self.web.get("/download")
        self.assertEqual(r.status_code, 302)                            # an HTML page is not an APK -> redirect to the real file
        self.assertEqual(self.admin.get(f"/dashboard?from={today_str()}&to={today_str()}").get_json()["today"]["apk_download"], 2)

    def test_every_endpoint_group_is_rate_limited(self):
        def hammer(path, limit, method="get", **kw):
            codes = [getattr(self.web, method)(path, **kw).status_code for _ in range(limit + 3)]
            self.assertIn(429, codes, path)
            self.assertEqual(codes.count(429), 3, path)
        hammer("/healthz", 60)
        hammer("/download", 6)
        hammer("/nope-path", 120)
        r = self.web.get("/healthz")
        self.assertEqual(r.headers["Retry-After"], "60")
        self.assertEqual(r.get_json()["e"], "rate")

    def test_login_endpoint_is_throttled(self):
        c = self.app.test_client()
        codes = [c.post("/panel/api/auth/login", json={"username": "x", "password": "y", "fp": str(i)}).status_code for i in range(12)]
        self.assertIn(429, codes)

    def test_admin_and_app_api_rate_limits(self):
        codes = [self.web.post("/api/v1/boot", data="x").status_code for _ in range(320)]
        self.assertIn(429, codes)
        a = self.app.test_client()
        codes = [a.get("/panel/api/auth/me").status_code for _ in range(310)]
        self.assertIn(429, codes)


class TestAdminPath(unittest.TestCase):
    """The panel must load whatever ADMIN_PATH is configured, with or without the trailing slash."""

    def app(self, path):
        from lysandra import create_app
        from lysandra.config import Settings
        from lysandra.db import MemoryDB
        return create_app(Settings(app_secret="x", admin_password="pw", admin_path=path, testing=True, cookie_secure=False), MemoryDB())

    def test_env_values_are_normalised(self):
        from lysandra.config import Settings
        for raw, want in (("adminpath", "/adminpath"), ("/adminpath/", "/adminpath"), (" /my-secret-panel ", "/my-secret-panel"), ("/a/b", "/a/b")):
            os.environ["ADMIN_PATH"] = raw
            self.assertEqual(Settings.from_env().admin_path, want, raw)
        os.environ.pop("ADMIN_PATH")
        self.assertEqual(Settings.from_env().admin_path, "/lysandra-admin")

    def test_with_and_without_trailing_slash(self):
        for path in ("/panel", "/my-secret-9x", "/a"):
            c = self.app(path).test_client()
            r = c.get(path)                                              # what the user typed: no trailing slash
            self.assertEqual((r.status_code, r.headers["Location"]), (302, path + "/"), path)
            r = c.get(path + "/")
            html = r.get_data(as_text=True)
            self.assertEqual(r.status_code, 200)
            for needle in (f'src="{path}/static/admin.js"', f'href="{path}/static/admin.css"', f'content="{path}"'):
                self.assertIn(needle, html, needle)                      # absolute URLs: never resolved against the wrong folder
            self.assertNotIn("{{ADMIN_PATH}}", html)
            for asset in ("admin.js", "admin.css", "icon.png", "favicon.png"):
                self.assertEqual(c.get(f"{path}/static/{asset}").status_code, 200, asset)
            self.assertEqual(c.get(path + "/api/auth/me").status_code, 401)   # API is reachable under the same path

    def test_short_admin_path_does_not_hijack_other_routes(self):
        c = self.app("/a").test_client()
        r = c.get("/assets/site.css")
        self.assertNotIn("no-store", r.headers.get("Cache-Control", ""))        # admin headers only below /a/
        self.assertNotIn("form-action", r.headers.get("Content-Security-Policy", ""))
        r = c.get("/api/v1/boot")
        self.assertNotIn("X-Robots-Tag", r.headers)
        self.assertEqual(c.get("/").status_code, 200)                           # landing page still on the root
        codes = [c.get("/healthz").status_code for _ in range(65)]
        self.assertEqual(codes.count(429), 5)                                   # normal per-route limits, not the admin group


if __name__ == "__main__":
    unittest.main(verbosity=1)
