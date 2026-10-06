"""
Admin auth: bcrypt password hashing, single-active-session enforcement with
15-minute sliding expiry, and fingerprint-based lockout after 3 failed logins.
"""
import hashlib
import secrets
import time

import bcrypt

from app.config import settings
from app.firebase_client import ref


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


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
