"""
Admin CRUD for the "supported platforms" grid shown in the app's Apps tab.
Simpler than Dialog/Carousel -- no view/click analytics, just name/icon/url/
sort order/highlight.
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.deps import require_admin
from app.firebase_client import ref
from app.utils.admin_log import log_admin_action
from app.utils.reorder import shift_and_insert

router = APIRouter()


class AppIn(BaseModel):
    name: str
    icon_url: str
    url: str | None = None
    sort_order: int = 0
    highlight: bool = False


@router.get("/api/admin/supported_apps")
async def list_apps(admin=Depends(require_admin)):
    raw = ref("/supported_apps").get() or {}
    items = [{"id": k, **v} for k, v in raw.items()]
    items.sort(key=lambda i: i.get("sort_order", 0))
    return {"items": items}


@router.post("/api/admin/supported_apps")
async def create_app(payload: AppIn, request: Request, admin=Depends(require_admin)):
    new_ref = ref("/supported_apps").push()
    body = payload.model_dump()
    body.update({"enabled": True, "created_at": int(time.time() * 1000)})
    new_ref.set(body)
    shift_and_insert("supported_apps", payload.sort_order, new_ref.key)
    log_admin_action(admin, "supported_apps_create", request.client.host, {"id": new_ref.key})
    return {"id": new_ref.key}


@router.patch("/api/admin/supported_apps/{app_id}")
async def update_app(app_id: str, payload: dict, request: Request, admin=Depends(require_admin)):
    allowed = {"name", "icon_url", "url", "sort_order", "highlight", "enabled"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        raise HTTPException(400, "Nothing to update")
    if "sort_order" in update:
        shift_and_insert("supported_apps", update["sort_order"], app_id)
    ref(f"/supported_apps/{app_id}").update(update)
    log_admin_action(admin, "supported_apps_update", request.client.host, {"id": app_id, **update})
    return {"updated": True}


@router.delete("/api/admin/supported_apps/{app_id}")
async def delete_app(app_id: str, request: Request, admin=Depends(require_admin)):
    ref(f"/supported_apps/{app_id}").delete()
    log_admin_action(admin, "supported_apps_delete", request.client.host, {"id": app_id})
    return {"deleted": True}
