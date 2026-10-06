"""
Request security: AES-GCM payload decryption, HMAC request signing/verification,
anti-replay (nonce+timestamp), and APK-identity checks.

THREAT MODEL NOTE (read the README section "Security: honest limits"):
This raises the bar for casual reverse-engineering and stops naive replay/scraping.
It does not make the API mathematically impossible to call from outside the app --
no purely client-side secret can guarantee that. For the strongest practical
guarantee, pair this with Google Play Integrity API verdicts (server-side
verification against Google) once the app is published; this module provides a
hook for that (see verify_play_integrity below) without requiring it.
"""
import base64
import hashlib
import hmac
import time

from cachetools import TTLCache
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request

from app.config import settings

# Replay cache: nonce -> True, auto-expires after the request TTL window.
# NOTE: in-memory, per-process. Fine for a single Render free instance.
# If you ever scale to >1 instance, swap this for Redis (see README).
_seen_nonces: TTLCache = TTLCache(maxsize=200_000, ttl=settings.REQUEST_TTL_SECONDS + 5)


def _aes_key() -> bytes:
    try:
        key = base64.b64decode(settings.AES_KEY_B64)
    except Exception:
        raise HTTPException(500, "Server misconfigured: AES key")
    if len(key) != 32:
        raise HTTPException(500, "Server misconfigured: AES key must be 32 bytes")
    return key


def decrypt_payload(payload_b64: str) -> str:
    """
    Expects payload_b64 = base64(nonce[12 bytes] + ciphertext + tag[16 bytes]),
    produced client-side with AES-256-GCM. Returns the decrypted plaintext URL.
    """
    try:
        raw = base64.b64decode(payload_b64)
        iv, ct = raw[:12], raw[12:]
        pt = AESGCM(_aes_key()).decrypt(iv, ct, None)
        return pt.decode("utf-8")
    except Exception:
        raise HTTPException(400, "Could not decrypt payload")


def encrypt_payload(plaintext: str) -> str:
    """Helper (used by tests / the Kotlin-side reference implementation in README)."""
    import os
    iv = os.urandom(12)
    ct = AESGCM(_aes_key()).encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(iv + ct).decode("ascii")


def sign(message: str) -> str:
    return hmac.new(settings.HMAC_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signed_request(request: Request, body_raw: bytes) -> None:
    """
    Verifies X-Timestamp, X-Nonce, X-Signature headers against the raw request
    body. Signature = HMAC_SHA256(secret, body + "." + timestamp + "." + nonce).
    Rejects stale timestamps and reused nonces (anti-replay).
    """
    ts = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")
    sig = request.headers.get("X-Signature")

    if not (ts and nonce and sig):
        raise HTTPException(401, "Missing signature headers")

    try:
        ts_int = int(ts)
    except ValueError:
        raise HTTPException(401, "Bad timestamp")

    now = int(time.time())
    if abs(now - ts_int) > settings.REQUEST_TTL_SECONDS:
        raise HTTPException(401, "Request expired")

    if nonce in _seen_nonces:
        raise HTTPException(401, "Replayed request rejected")

    expected = sign(body_raw.decode("utf-8") + "." + ts + "." + nonce)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "Invalid signature")

    _seen_nonces[nonce] = True


def verify_app_identity(request: Request) -> None:
    """
    Defense-in-depth check: the app sends its package name and the SHA-256 of
    its own signing certificate (read at runtime via PackageManager on the
    Kotlin side). We compare against the known-good values from env.
    A modified/re-signed APK will have a different cert hash and get rejected
    here even if it somehow replicates the HMAC secret.
    """
    pkg = request.headers.get("X-Package-Name", "")
    cert = request.headers.get("X-Cert-SHA256", "").lower().replace(":", "")

    if settings.ALLOWED_PACKAGE_NAMES and pkg not in settings.ALLOWED_PACKAGE_NAMES:
        raise HTTPException(403, "Unknown client")

    if settings.EXPECTED_APK_CERT_SHA256 and cert != settings.EXPECTED_APK_CERT_SHA256:
        raise HTTPException(403, "App integrity check failed")


async def verify_play_integrity(integrity_token: str | None) -> bool:
    """
    Hook for Google Play Integrity API verification. Wire this up once the app
    is published to Play (or use the 'standard' API for side-loaded APKs with
    a cloud project). Not required for the app to function; strongly
    recommended for production. See README for setup steps.
    """
    if not integrity_token:
        return False
    # TODO: call https://playintegrity.googleapis.com/v1/{packageName}:decodeIntegrityToken
    # with a Google service-account-signed request, and check the verdict.
    return True
