"""
Event + device logging to Firebase RTDB, for the admin panel's analytics
needs (today/yesterday/all-time/custom-range counts, per-device history,
top-N users, ad-event breakdowns, etc.)

Path convention used everywhere in this file:
  /logs/<category>/<date>/<push_id>   -> individual events, for pagination/drilldown
  /stats/<category>/<date>/...        -> O(1) counters via transaction(), for dashboard numbers
This keeps dashboard reads cheap while still letting the admin panel drill
into "which users" for any number on screen.
"""
import time
from datetime import datetime, timezone

from app.firebase_client import ref

IST_OFFSET_SECONDS = 5.5 * 3600  # admin panel displays times in IST


def _date_key(ts: float | None = None) -> str:
    ts = ts if ts is not None else time.time()
    ist = datetime.fromtimestamp(ts + IST_OFFSET_SECONDS, tz=timezone.utc)
    return ist.strftime("%Y-%m-%d")


def _inc(path: str, by: int = 1) -> None:
    ref(path).transaction(lambda v: (v or 0) + by)


def log_fetch_event(device_id: str, ip: str, domain: str, extractor: str,
                     success: bool, error: str | None = None) -> None:
    day = _date_key()
    entry = {
        "device_id": device_id, "ip": ip, "domain": domain, "extractor": extractor,
        "success": success, "error": error, "ts": int(time.time() * 1000),
    }
    ref(f"/logs/fetch/{day}").push(entry)
    _inc(f"/stats/fetch/{day}/{'success' if success else 'failed'}")
    _inc(f"/stats/user_fetch_count/{device_id}")  # powers "top 50 users by most fetch"


def log_blocked_domain_hit(device_id: str, ip: str, domain: str) -> None:
    day = _date_key()
    ref(f"/logs/blocked/{day}").push({
        "device_id": device_id, "ip": ip, "domain": domain, "ts": int(time.time() * 1000),
    })
    _inc(f"/stats/blocked/{day}")


def log_device_seen(device_id: str, ip: str) -> bool:
    """
    Per-device login history: every time this device hits the backend, append
    ip+timestamp to its history and bump last_seen. Returns True if this is
    the device's first-ever appearance (a "new user"), so callers can log it.
    """
    now_ms = int(time.time() * 1000)
    device_ref = ref(f"/devices/{device_id}")
    existing = device_ref.get()
    is_new = existing is None

    device_ref.child("last_seen").set(now_ms)
    device_ref.child("last_ip").set(ip)
    device_ref.child("history").push({"ip": ip, "ts": now_ms})

    if is_new:
        device_ref.child("first_seen").set(now_ms)
        day = _date_key()
        ref(f"/logs/new_users/{day}").push({"device_id": device_id, "ip": ip, "ts": now_ms})
        _inc(f"/stats/new_users_count/{day}")
        _inc("/stats/total_users_count")

    today = _date_key()
    ref(f"/stats/daily_active/{today}/{device_id}").set(True)  # presence set -> "active today"
    return is_new


def log_ad_event(device_id: str, ip: str, ad_type: str, platform: str, action: str, page: str) -> None:
    """
    ad_type: 'interstitial' | 'rewarded' | 'banner' | 'native'
    platform: 'startio' | 'monetag'
    action: 'fetch' | 'watch' | 'download' | 'page_switch' | ... (whatever triggered it)
    page: which screen/activity triggered it (interstitials specifically need this per spec)
    """
    day = _date_key()
    composite = f"{ad_type}_{platform}_{action}"
    ref(f"/logs/ads/{day}").push({
        "device_id": device_id, "ip": ip, "ad_type": ad_type, "platform": platform,
        "action": action, "page": page, "composite": composite, "ts": int(time.time() * 1000),
    })
    _inc(f"/stats/ads/{day}/{ad_type}/{platform}/{action}")
    if ad_type in ("interstitial", "rewarded"):
        _inc(f"/stats/user_ads_count/{device_id}/{ad_type}")  # powers top-50 ad-watch breakdown


def log_maintenance_hit(device_id: str, ip: str) -> None:
    day = _date_key()
    ref(f"/logs/maintenance/{day}").push({
        "device_id": device_id, "ip": ip, "ts": int(time.time() * 1000),
    })
    _inc(f"/stats/maintenance_count/{day}")
