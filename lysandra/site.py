"""Public landing website: /, /privacy, /terms, /dmca, /support, /developer, /download (APK)."""
import os

import requests
from flask import Response, redirect, render_template, send_from_directory

STATIC = os.path.join(os.path.dirname(__file__), "static", "site")


def init(app, ctx):
    def L():
        return ctx.cfg.get("landing")

    @app.route("/assets/<path:name>", endpoint="site_assets")
    def assets(name):
        resp = send_from_directory(STATIC, name)
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @app.route("/")
    def landing():
        return render_template("index.html", L=L(), plans=ctx.cfg.get("premium", "plans", []))

    def page(heading, key):
        return render_template("page.html", L=L(), heading=heading, body=ctx.cfg.get("legal", key, ""))

    @app.route("/privacy")
    def privacy():
        return page("Privacy Policy", "privacy_html")

    @app.route("/terms")
    def terms():
        return page("Terms & Conditions", "terms_html")

    @app.route("/dmca")
    def dmca():
        return page("DMCA", "dmca_html")

    @app.route("/support")
    def support():
        return render_template("support.html", L=L(), S=ctx.cfg.get("support"))

    @app.route("/developer")
    def developer():
        return render_template("developer.html", L=L(), D=ctx.cfg.get("developer"))

    @app.route("/robots.txt")
    def robots():
        base = ctx.settings.public_url
        return Response(f"User-agent: *\nDisallow: {ctx.settings.admin_path}/\nDisallow: /api/\n" + (f"Sitemap: {base}/sitemap.xml\n" if base else ""),
                        mimetype="text/plain")

    @app.route("/sitemap.xml")
    def sitemap():
        base = ctx.settings.public_url or ""
        urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/", "/privacy", "/terms", "/dmca", "/support", "/developer"))
        return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        mimetype="application/xml")

    @app.route("/download")
    def download_apk():
        cfg = L()
        url = (cfg.get("apk_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return render_template("page.html", L=cfg, heading="Download", body="<p>The APK is not available yet. Please check back soon or join our Telegram channel.</p>"), 404
        ctx.stats.bump_bg("apk_download")
        name = f"Lysandra-{cfg.get('version', '1.0')}.apk".replace(" ", "")
        try:
            up = requests.get(url, stream=True, timeout=(8, 30), allow_redirects=True)
            ctype = up.headers.get("Content-Type", "")
            if up.status_code != 200 or "html" in ctype.lower() or cfg.get("apk_mode") == "redirect":
                up.close()
                return redirect(url, code=302)
            headers = {"Content-Type": "application/vnd.android.package-archive", "Content-Disposition": f'attachment; filename="{name}"',
                       "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
            if up.headers.get("Content-Length"):
                headers["Content-Length"] = up.headers["Content-Length"]
            return Response(up.iter_content(128 * 1024), headers=headers)
        except requests.RequestException:
            return redirect(url, code=302)
