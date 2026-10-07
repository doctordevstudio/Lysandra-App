"""
Admin auth: credentials are the raw ADMIN_USERNAME / ADMIN_PASSWORD env vars
(no stored hash, no Firebase-held account, no setup script -- just set them
on Render and log in). Session management (single active session, 15-min
sliding expiry) and fingerprint-based lockout after 3 failed logins are
unchanged by that.
"""
import hashlib
import hmac
import secrets
import time

from app.config import settings
from app.firebase_client import ref


def verify_admin_credentials(username: str, password: str) -> bool:
    """Constant-time comparison against the raw env-var credentials, so a
    mistyped password can't be distinguished by response timing from a
    correct one -- doesn't change where the credentials live, just how
    they're compared."""
    username_ok = hmac.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode())
    password_ok = hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())
    return username_ok and password_ok


def fingerprint_hash(raw_fp: str, ip: str) -> str:
    """Lockout key = hash of the client-computed fingerprint alone (not IP) --
    the spec locks the *device*, independent of which IP it's coming from."""
    return hashlib.sha256(raw_fp.encode()).hexdigest()


def is_locked(fp_hash: str) -> tuple[bool, int]:
    data = ref(f"/admin_auth/lockouts/{fp_hash}").get() or {}
    locked_until = data.get("locked_until", 0)
    now_ms = int(time.time() * 1000)
    return locked_until > now_ms, locked_until


def record_failed_attempt(fp_hash: str) -> None:
    lock_ref = ref(f"/admin_auth/lockouts/{fp_hash}")
    data = lock_ref.get() or {}
    failed = data.get("failed_count", 0) + 1
    update = {"failed_count": failed, "last_failed": int(time.time() * 1000)}
    if failed >= settings.LOCKOUT_MAX_ATTEMPTS:
        update["locked_until"] = int(time.time() * 1000) + settings.LOCKOUT_DURATION_HOURS * 3600 * 1000
    lock_ref.update(update)


def reset_attempts(fp_hash: str) -> None:
    ref(f"/admin_auth/lockouts/{fp_hash}").set({"failed_count": 0})


def create_session(username: str, ip: str, fp_hash: str) -> str:
    """Overwrites any existing session for this username -- enforces
    'only one active session at a time' per admin account."""
    token = secrets.token_urlsafe(32)
    now_ms = int(time.time() * 1000)
    ref(f"/admin_auth/sessions/{username}").set({
        "token": token, "created_at": now_ms, "last_activity": now_ms,
        "ip": ip, "fingerprint": fp_hash,
    })
    return token


def validate_and_touch_session(username: str, token: str) -> bool:
    """Checks token match + 15-min sliding inactivity window. Refreshes
    last_activity on every successful call (sliding expiry, not fixed)."""
    sess_ref = ref(f"/admin_auth/sessions/{username}")
    data = sess_ref.get() or {}
    if not data or data.get("token") != token:
        return False
    now_ms = int(time.time() * 1000)
    if now_ms - data.get("last_activity", 0) > settings.SESSION_TTL_MINUTES * 60 * 1000:
        sess_ref.delete()
        return False
    sess_ref.child("last_activity").set(now_ms)
    return True


def destroy_session(username: str) -> None:
    ref(f"/admin_auth/sessions/{username}").delete()
