"""
Shared view/click tracking for the three "engagement" content types the admin
panel manages: notifications, dialogs, carousel. Same rules for all three:
  - first view/click by a device counts; repeats by the same device don't
  - per-item total_view/total_click live on the item itself (cheap to read)
  - every (deduped) view/click is also logged for date-range drilldowns and
    for "which users saw/clicked this" in the admin panel
"""
import time
from datetime import datetime, timezone

from app.firebase_client import ref

IST_OFFSET_SECONDS = 5.5 * 3600


def _date_key(ts: float | None = None) -> str:
    ts = ts if ts is not None else time.time()
    ist = datetime.fromtimestamp(ts + IST_OFFSET_SECONDS, tz=timezone.utc)
    return ist.strftime("%Y-%m-%d")


def record_event(entity_type: str, entity_id: str, device_id: str, ip: str, which: str) -> bool:
    """
    entity_type: 'notifications' | 'dialogs' | 'carousel'
    which: 'view' | 'click'
    Returns True if this was newly recorded (not a dedup no-op).
    """
    seen_ref = ref(f"/engagement_seen/{entity_type}/{which}/{entity_id}/{device_id}")
    if seen_ref.get():
        return False
    seen_ref.set(True)

    now_ms = int(time.time() * 1000)
    day = _date_key()

    ref(f"/{entity_type}/{entity_id}/total_{which}").transaction(lambda v: (v or 0) + 1)
    ref(f"/logs/{entity_type}_{which}/{entity_id}").push({"device_id": device_id, "ip": ip, "ts": now_ms})
    ref(f"/logs/{entity_type}_{which}_daily/{day}").push({
        "entity_id": entity_id, "device_id": device_id, "ip": ip, "ts": now_ms,
    })
    ref(f"/stats/{entity_type}_{which}/{day}").transaction(lambda v: (v or 0) + 1)
    return True


def record_view(entity_type: str, entity_id: str, device_id: str, ip: str) -> bool:
    return record_event(entity_type, entity_id, device_id, ip, "view")


def record_click(entity_type: str, entity_id: str, device_id: str, ip: str) -> bool:
    return record_event(entity_type, entity_id, device_id, ip, "click")
