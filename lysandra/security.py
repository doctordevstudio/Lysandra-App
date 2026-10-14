"""Request security: signed + encrypted app API, replay protection, rate limits,
client IP resolution, IP reputation, admin sessions and brute-force locking."""
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import threading
import time
from functools import wraps

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .util import DEVICE_RE, const_eq, now_ts, push_id, sha256_hex, today_str

MAX_BODY = 3 * 1024 * 1024
TS_WINDOW = 300


# ---------------------------------------------------------------- crypto
class Crypto:
    def __init__(self, secret):
        master = hashlib.sha256(secret.encode()).digest()
        self.sig_key = hmac.new(master, b"sig", hashlib.sha256).digest()
        self.enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
        self.aes = AESGCM(self.enc_key)

    def sign(self, method, path, ts, nonce, dev, apk, body_b64):
        msg = "\n".join([method.upper(), path, str(ts), nonce, dev, apk, sha256_hex(body_b64)])
        return hmac.new(self.sig_key, msg.encode(), hashlib.sha256).hexdigest()

    def encrypt(self, obj, aad):
        iv = secrets.token_bytes(12)
        ct = self.aes.encrypt(iv, json.dumps(obj, separators=(",", ":")).encode(), aad.encode())
        return base64.b64encode(iv + ct).decode()

    def decrypt(self, b64, aad):
        raw = base64.b64decode(b64, validate=True)
        if len(raw) < 29:
            raise ValueError("short")
        return json.loads(self.aes.decrypt(raw[:12], raw[12:], aad.encode()))


# ---------------------------------------------------------------- limiter
class RateLimiter:
    def __init__(self):
        self.hits = {}
        self.lock = threading.Lock()
        self.last_gc = time.time()

    def allow(self, key, limit, window):
        now = time.time()
        with self.lock:
            arr = [t for t in self.hits.get(key, ()) if now - t < window]
            if len(arr) >= limit:
                self.hits[key] = arr
                return False
            arr.append(now)
            self.hits[key] = arr
            if now - self.last_gc > 120:
                self.last_gc = now
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 3600}
            return True


class NonceCache:
    def __init__(self, ttl=TS_WINDOW * 2):
        self.ttl = ttl
        self.seen = {}
        self.lock = threading.Lock()

    def use(self, nonce):
        now = time.time()
        with self.lock:
            if len(self.seen) > 20000 or (now % 60) < 1:
                self.seen = {k: v for k, v in self.seen.items() if v > now}
            if nonce in self.seen:
                return False
            self.seen[nonce] = now + self.ttl
            return True


# ---------------------------------------------------------------- IP intelligence
class IPIntel:
    def __init__(self, provider="none"):
        self.provider = provider
        self.cache = {}
        self.lock = threading.Lock()

    @staticmethod
    def is_private(ip):
        """True for private/loopback/reserved IPs. Non-IP strings (hostnames) are not private."""
        try:
            a = ipaddress.ip_address(ip)
            return a.is_private or a.is_loopback or a.is_reserved or a.is_link_local or a.is_multicast
        except ValueError:
            return False

    def lookup(self, ip):
        res = {"datacenter": False, "vpn": False, "proxy": False, "tor": False}
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return res
        if self.provider == "none" or self.is_private(ip):
            return res
        now = time.time()
        with self.lock:
            hit = self.cache.get(ip)
            if hit and hit[0] > now:
                return hit[1]
        try:
            if self.provider == "ipapi_is":
                r = requests.get("https://api.ipapi.is/", params={"q": ip}, timeout=2.5)
                if r.ok:
                    j = r.json()
                    res = {"datacenter": bool(j.get("is_datacenter")), "vpn": bool(j.get("is_vpn")),
                           "proxy": bool(j.get("is_proxy")), "tor": bool(j.get("is_tor"))}
                else:
                    return res  # fail-open, do not cache
        except Exception:
            return res
        with self.lock:
            if len(self.cache) > 5000:
                self.cache.clear()
            self.cache[ip] = (now + 86400, res)
        return res


def ip_in_list(ip, entries):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for e in entries or []:
        try:
            if "/" in e:
                if a in ipaddress.ip_network(e, strict=False):
                    return True
            elif a == ipaddress.ip_address(e):
                return True
        except ValueError:
            continue
    return False


def client_ip(settings):
    if settings.trust_cloudflare:
        v = request.headers.get("CF-Connecting-IP")
        if v:
            return v.strip()
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


# ---------------------------------------------------------------- app request guard
class AppGuard:
    def __init__(self, ctx):
        self.ctx = ctx
        self.crypto = Crypto(ctx.settings.app_secret) if ctx.settings.app_secret else None
        self.nonces = NonceCache()

    def _err(self, code, msg, status):
        return jsonify({"e": code, "m": msg, "t": now_ts()}), status

    def secure(self, limit=60, window=60, needs_device=True, allow_banned=False):
        """Decorator: verify, decrypt, rate-limit, then call fn(data) -> dict."""
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                ctx = self.ctx
                if self.crypto is None:
                    return self._err("config", "server not configured", 503)
                ip = client_ip(ctx.settings)
                g.ip = ip
                if not ctx.limiter.allow(f"ip:{ip}", 240, 60):
                    return self._err("rate", "Too many requests", 429)
                if request.content_length and request.content_length > MAX_BODY:
                    return self._err("size", "Payload too large", 413)
                h = request.headers
                ts, nonce, dev = h.get("X-L-Ts", ""), h.get("X-L-Nonce", ""), h.get("X-L-Dev", "")
                apk, sig = h.get("X-L-Apk", "").lower(), h.get("X-L-Sig", "")
                body = request.get_data(as_text=True) or ""
                if not (ts.isdigit() and 8 <= len(nonce) <= 64 and sig and len(body) < MAX_BODY):
                    return self._err("bad", "Malformed request", 400)
                if abs(now_ts() - int(ts)) > TS_WINDOW:
                    resp = self._err("clock", "Device clock is wrong", 401)
                    return resp
                if needs_device and not DEVICE_RE.match(dev):
                    return self._err("bad", "Malformed request", 400)
                expect = self.crypto.sign(request.method, request.path, ts, nonce, dev, apk, body)
                if not const_eq(expect, sig):
                    ctx.metrics["bad_sig"] += 1
                    return self._err("auth", "Unauthorized", 401)
                allowed = ctx.settings.allowed_apk_sha256
                if allowed and apk not in allowed:
                    ctx.metrics["bad_apk"] += 1
                    return self._err("auth", "Unauthorized", 401)
                if not self.nonces.use(nonce):
                    return self._err("replay", "Replay detected", 401)
                if not ctx.limiter.allow(f"dev:{dev}:{request.path}", limit, window):
                    return self._err("rate", "Too many requests", 429)
                if dev and not allow_banned and (ctx.is_banned(dev) or ctx.is_banned(ctx.canon(dev))):
                    return self._err("banned", "This device has been blocked.", 403)
                try:
                    p = json.loads(body).get("p", "") if body.startswith("{") else body
                    data = self.crypto.decrypt(p, f"{request.path}|{ts}|{nonce}") if p else {}
                except Exception:
                    return self._err("bad", "Malformed request", 400)
                g.raw_dev, g.apk, g.nonce = dev, apk, nonce
                g.dev = ctx.canon(dev) if dev else dev
                try:
                    out = fn(data, *a, **kw)
                except ApiError as e:
                    out = {"ok": False, "code": e.code, "msg": e.msg, **e.extra}
                except Exception:
                    ctx.log.exception("handler failed: %s", request.path)
                    return self._err("server", "Something went wrong. Please try again.", 500)
                out["t"] = now_ts()
                enc = self.crypto.encrypt(out, f"{request.path}|{ts}|{nonce}|r")
                resp = jsonify({"p": enc})
                resp.headers["Cache-Control"] = "no-store"
                return resp
            return wrapper
        return deco


class ApiError(Exception):
    def __init__(self, code, msg, **extra):
        self.code, self.msg, self.extra = code, msg, extra


# ---------------------------------------------------------------- admin auth
class AdminAuth:
    IDLE = 15 * 60
    MAX_FAILS = 3
    LOCK_SECS = 24 * 3600

    def __init__(self, ctx):
        self.ctx = ctx
        s = ctx.settings
        self.user = s.admin_user
        self.pw_hash = s.admin_password_hash or (generate_password_hash(s.admin_password) if s.admin_password else "")
        self.session = None  # single active session
        self.lock = threading.Lock()

    @property
    def enabled(self):
        return bool(self.pw_hash)

    @staticmethod
    def server_fp():
        return sha256_hex(request.headers.get("User-Agent", "") + "|" + request.headers.get("Accept-Language", ""))[:32]

    def _lock_keys(self, ip, fp):
        return [("fp", sha256_hex("c" + fp)[:32]), ("sv", self.server_fp()), ("ip", sha256_hex(ip)[:32])]

    def locked_until(self, ip, fp):
        now = now_ts()
        best = 0
        for kind, k in self._lock_keys(ip, fp):
            rec = self.ctx.db.get(f"admin_locks/{kind}_{k}") or {}
            if rec.get("until", 0) > now:
                best = max(best, rec["until"])
        return best

    def _record(self, ip, fp, ok, user):
        db = self.ctx.db
        db.put(f"admin_login_logs/{today_str()}/{push_id()}",
               {"ts": now_ts(), "ip": ip, "fp": fp[:64], "ua": request.headers.get("User-Agent", "")[:200],
                "user": user[:40], "ok": ok})
        for kind, k in self._lock_keys(ip, fp):
            path = f"admin_locks/{kind}_{k}"
            if ok:
                db.delete(path)
                continue
            rec = db.get(path) or {}
            fails = rec.get("fails", 0) + 1
            rec = {"fails": fails, "until": now_ts() + self.LOCK_SECS if fails >= self.MAX_FAILS else 0}
            db.put(path, rec)

    def login(self, username, password, fp):
        ip = self.ctx.client_ip()
        until = self.locked_until(ip, fp)
        if until:
            return None, {"locked_until": until}
        ok = (self.enabled and const_eq(username, self.user) and check_password_hash(self.pw_hash, password))
        self._record(ip, fp, ok, username)
        if not ok:
            time.sleep(0.4)
            return None, {"error": "Invalid credentials"}
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        with self.lock:
            self.session = {"sid": sha256_hex(sid), "csrf": csrf, "ip": ip, "last": time.time(), "user": username}
        return {"sid": sid, "csrf": csrf}, None

    def current(self):
        sid = request.cookies.get("lys_sid", "")
        with self.lock:
            s = self.session
            if not s or not sid or not const_eq(sha256_hex(sid), s["sid"]):
                return None
            if time.time() - s["last"] > self.IDLE:
                self.session = None
                return None
            s["last"] = time.time()
            return dict(s)

    def logout(self):
        with self.lock:
            self.session = None

    def required(self, fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            s = self.current()
            if not s:
                return jsonify({"error": "unauthorized"}), 401
            if request.method not in ("GET", "HEAD"):
                if not const_eq(request.headers.get("X-CSRF-Token", ""), s["csrf"]):
                    return jsonify({"error": "csrf"}), 403
                origin = request.headers.get("Origin")
                if origin and origin.split("://", 1)[-1] != request.host:
                    return jsonify({"error": "origin"}), 403
            g.admin = s
            return fn(*a, **kw)
        return wrapper
