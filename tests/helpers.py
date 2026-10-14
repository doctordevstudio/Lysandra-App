import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRET = "test-secret-123"
APK = "ab" * 32


class AppClient:
    """Mirrors exactly what the Android client does (see net/SecureApi.kt)."""

    def __init__(self, flask_client, dev=None, secret=SECRET, apk=APK):
        self.c = flask_client
        self.dev = dev or secrets.token_hex(16)
        master = hashlib.sha256(secret.encode()).digest()
        self.sig_key = hmac.new(master, b"sig", hashlib.sha256).digest()
        self.aes = AESGCM(hmac.new(master, b"enc", hashlib.sha256).digest())
        self.apk = apk

    def call(self, path, data=None, ts=None, nonce=None, tamper=False, ip="1.2.3.4"):
        path = "/api/v1" + path
        ts = str(ts or int(time.time()))
        nonce = nonce or secrets.token_hex(12)
        iv = secrets.token_bytes(12)
        ct = self.aes.encrypt(iv, json.dumps(data or {}).encode(), f"{path}|{ts}|{nonce}".encode())
        body = base64.b64encode(iv + ct).decode()
        msg = "\n".join(["POST", path, ts, nonce, self.dev, self.apk, hashlib.sha256(body.encode()).hexdigest()])
        sig = hmac.new(self.sig_key, msg.encode(), hashlib.sha256).hexdigest()
        if tamper:
            sig = "0" * 64
        r = self.c.post(path, data=body, headers={"X-L-Ts": ts, "X-L-Nonce": nonce, "X-L-Dev": self.dev,
                                                   "X-L-Apk": self.apk, "X-L-Sig": sig, "CF-Connecting-IP": ip,
                                                   "Content-Type": "text/plain"})
        j = r.get_json()
        if r.status_code == 200 and "p" in j:
            raw = base64.b64decode(j["p"])
            out = json.loads(self.aes.decrypt(raw[:12], raw[12:], f"{path}|{ts}|{nonce}|r".encode()))
            return r.status_code, out
        return r.status_code, j


def png_bytes(w=400, h=600):
    from PIL import Image
    import io
    im = Image.new("RGB", (w, h), (30, 80, 200))
    for x in range(0, w, 7):
        for y in range(0, h, 11):
            im.putpixel((x, y), (x % 255, y % 255, (x * y) % 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()
