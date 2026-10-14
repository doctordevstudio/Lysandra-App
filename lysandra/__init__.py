import logging
import os
import threading
import time

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import api_admin, api_app, site
from .config import Settings
from .core import Context
from .extractors import build_registry
from .payments import Payments
from .telegram import Telegram
from .util import const_eq


def create_app(settings=None, db=None):
    settings = settings or Settings.from_env()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__, static_folder=None, template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
    ctx = Context(settings, db)
    ctx.telegram = Telegram(ctx)
    ctx.payments = Payments(ctx)
    ctx.extractors = build_registry(ctx)
    app.ctx = ctx
    ctx.cfg.load()

    app.register_blueprint(api_app.init(ctx))
    admin_path = settings.admin_path
    app.register_blueprint(api_admin.init(ctx), url_prefix=admin_path + "/api")

    static_dir = os.path.join(os.path.dirname(__file__), "static", "admin")

    # ------------------------------------------------------------ rate limit on EVERY endpoint
    # (route group, requests, window seconds) – first matching prefix wins; everything else falls into "site"
    RATE_RULES = [
        (admin_path + "/api/auth/login", "login", 8, 60),
        (admin_path + "/api/", "admin_api", 300, 60),
        (admin_path, "admin_ui", 120, 60),
        ("/api/v1/relay/", "relay", 120, 60),
        ("/api/v1/", "app_api", 300, 60),
        ("/tg/", "telegram", 600, 60),
        ("/download", "apk", 6, 600),
        ("/healthz", "health", 60, 60),
        ("/assets/", "assets", 600, 60),
    ]

    @app.before_request
    def rate_limit():
        ip = ctx.client_ip()
        group, limit, window = "site", 120, 60
        for prefix, g_, lim, win in RATE_RULES:
            if request.path.startswith(prefix):
                group, limit, window = g_, lim, win
                break
        if not ctx.limiter.allow(f"rl:{group}:{ip}", limit, window):
            resp = jsonify({"e": "rate", "m": "Too many requests. Please slow down."})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(window)
            return resp

    @app.before_request
    def origin_gate():
        # Only traffic that came through Cloudflare (which adds this secret header) is served.
        if settings.origin_secret and request.path not in ("/healthz",) and not request.path.startswith("/tg/"):
            if not const_eq(request.headers.get("X-Origin-Secret", ""), settings.origin_secret):
                abort(403)

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.pop("Server", None)
        if request.path.startswith(admin_path):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
            resp.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; img-src 'self' data: https: http:; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if settings.cookie_secure:
                resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        elif not request.path.startswith(("/api/", "/tg/")):
            resp.headers.setdefault("Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        return resp

    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True, "t": int(time.time())})

    site.init(app, ctx)

    @app.route(admin_path)
    @app.route(admin_path + "/")
    def admin_index():
        return send_from_directory(static_dir, "index.html")

    @app.route(admin_path + "/static/<path:name>")
    def admin_static(name):
        return send_from_directory(static_dir, name)

    @app.route("/tg/<secret>", methods=["POST"])
    def tg_webhook(secret):
        want = settings.telegram_webhook_secret
        if not want or not const_eq(secret, want) or \
                not const_eq(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), want):
            abort(404)
        upd = request.get_json(silent=True) or {}
        ctx.bg(ctx.telegram.handle_update, upd)
        return jsonify({"ok": True})

    @app.errorhandler(404)
    def nf(_):
        return jsonify({"e": "nf"}), 404

    @app.errorhandler(413)
    def big(_):
        return jsonify({"e": "size"}), 413

    @app.errorhandler(405)
    def na(_):
        return jsonify({"e": "nf"}), 404

    if settings.background_jobs and not settings.testing:
        def janitor():
            while True:
                time.sleep(60)
                try:
                    ctx.payments.expire_due()
                    ctx.payments.expire_premiums()
                except Exception:
                    ctx.log.exception("janitor failed")
        threading.Thread(target=janitor, daemon=True, name="janitor").start()
        threading.Thread(target=ctx.telegram.set_webhook, daemon=True).start()

    if not ctx.admin.enabled:
        ctx.log.warning("ADMIN_PASSWORD is not set – the admin panel login is disabled")
    if not settings.app_secret:
        ctx.log.warning("APP_SECRET is not set – the app API is disabled")
    return app
