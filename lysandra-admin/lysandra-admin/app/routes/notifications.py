"""
Admin CRUD for notifications + their analytics. The app-facing list/seen/
clicked endpoints live in the main backend; this only writes/reads the same
/notifications node and reads the /logs/notifications_* nodes it produces.
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.deps import require_admin
from app.firebase_client import ref
from app.utils.admin_log import log_admin_action
from app.utils.aggregate import sum_flat
from app.utils.dates import resolve_range
from app.utils.pagination import get_page

router = APIRouter()

# Note: notifications/dialogs/carousel are read live by the main backend on
# every app request (no config-cache layer for these), so creating/editing
# here takes effect immediately -- unlike /config settings, there's no
# reload-config call needed.


class NotificationIn(BaseModel):
    title: str
    message: str
    image_url: str | None = None
    click_url: str | None = None


@router.get("/api/admin/notifications")
async def list_notifications(cursor: str | None = None, admin=Depends(require_admin)):
    items, next_cursor = get_page("/notifications", limit=20, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor}


@router.post("/api/admin/notifications")
async def create_notification(payload: NotificationIn, request: Request, admin=Depends(require_admin)):
    now_ms = int(time.time() * 1000)
    new_ref = ref("/notifications").push({
        "title": payload.title, "message": payload.message, "image_url": payload.image_url,
        "click_url": payload.click_url, "enabled": True, "total_view": 0, "total_click": 0,
        "created_at": now_ms,
    })
    log_admin_action(admin, "notification_create", request.client.host, {"id": new_ref.key})
    return {"id": new_ref.key}


@router.patch("/api/admin/notifications/{notif_id}")
async def update_notification(notif_id: str, payload: dict, request: Request, admin=Depends(require_admin)):
    allowed = {"title", "message", "image_url", "click_url", "enabled"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Nothing to update")
    ref(f"/notifications/{notif_id}").update(update)
    log_admin_action(admin, "notification_update", request.client.host, {"id": notif_id, **update})
    return {"updated": True}


@router.delete("/api/admin/notifications/{notif_id}")
async def delete_notification(notif_id: str, request: Request, admin=Depends(require_admin)):
    ref(f"/notifications/{notif_id}").delete()
    log_admin_action(admin, "notification_delete", request.client.host, {"id": notif_id})
    return {"deleted": True}


@router.get("/api/admin/notifications/{notif_id}/stats")
async def notification_stats(notif_id: str, admin=Depends(require_admin)):
    data = ref(f"/notifications/{notif_id}").get() or {}
    return {
        "total_view": data.get("total_view", 0),
        "total_click": data.get("total_click", 0),
    }


@router.get("/api/admin/notifications/{notif_id}/viewers")
async def notification_viewers(notif_id: str, which: str = "view", cursor: str | None = None,
                                admin=Depends(require_admin)):
    if which not in ("view", "click"):
        raise HTTPException(400, "which must be 'view' or 'click'")
    items, next_cursor = get_page(f"/logs/notifications_{which}/{notif_id}", limit=20, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/admin/notifications/clicks-summary")
async def clicks_summary(range: str = "today", start: str | None = None, end: str | None = None,
                          admin=Depends(require_admin)):
    date_keys = None if range == "all" else resolve_range(range, start, end)
    views = sum_flat("/stats/notifications_view", date_keys)
    clicks = sum_flat("/stats/notifications_click", date_keys)
    return {"views": views, "clicks": clicks}
