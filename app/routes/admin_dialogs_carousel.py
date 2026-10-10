"""
Admin CRUD for Dialogs and Carousel -- identical shape (image/message,
click url, sort order with auto-shift on insert), so handled together.
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
from app.utils.reorder import shift_and_insert

router = APIRouter()


class DialogIn(BaseModel):
    message_html: str
    image_url: str | None = None
    click_url: str | None = None
    sort_order: int = 0


class CarouselIn(BaseModel):
    image_url: str
    click_url: str | None = None
    sort_order: int = 0


def _register_crud(node: str, model):
    async def list_items(admin=Depends(require_admin)):
        raw = ref(f"/{node}").get() or {}
        items = [{"id": k, **v} for k, v in raw.items()]
        items.sort(key=lambda i: i.get("sort_order", 0))
        return {"items": items}

    async def create_item(payload: model, request: Request, admin=Depends(require_admin)):
        new_ref = ref(f"/{node}").push()
        body = payload.model_dump()
        body.update({"enabled": True, "total_view": 0, "total_click": 0, "created_at": int(time.time() * 1000)})
        new_ref.set(body)
        shift_and_insert(node, payload.sort_order, new_ref.key)
        log_admin_action(admin, f"{node}_create", request.client.host, {"id": new_ref.key})
        return {"id": new_ref.key}

    async def update_item(item_id: str, payload: dict, request: Request, admin=Depends(require_admin)):
        allowed = {"message_html", "image_url", "click_url", "enabled", "sort_order"}
        update = {k: v for k, v in payload.items() if k in allowed}
        if not update:
            raise HTTPException(400, "Nothing to update")
        if "sort_order" in update:
            shift_and_insert(node, update["sort_order"], item_id)
        ref(f"/{node}/{item_id}").update(update)
        log_admin_action(admin, f"{node}_update", request.client.host, {"id": item_id, **update})
        return {"updated": True}

    async def delete_item(item_id: str, request: Request, admin=Depends(require_admin)):
        ref(f"/{node}/{item_id}").delete()
        log_admin_action(admin, f"{node}_delete", request.client.host, {"id": item_id})
        return {"deleted": True}

    async def viewers(item_id: str, which: str = "view", cursor: str | None = None, admin=Depends(require_admin)):
        if which not in ("view", "click"):
            raise HTTPException(400, "which must be 'view' or 'click'")
        items, next_cursor = get_page(f"/logs/{node}_{which}/{item_id}", limit=20, cursor=cursor)
        return {"items": items, "next_cursor": next_cursor}

    async def clicks_summary(range: str = "today", start: str | None = None, end: str | None = None,
                              admin=Depends(require_admin)):
        date_keys = None if range == "all" else resolve_range(range, start, end)
        views = sum_flat(f"/stats/{node}_view", date_keys)
        clicks = sum_flat(f"/stats/{node}_click", date_keys)
        return {"views": views, "clicks": clicks}

    router.get(f"/api/admin/{node}")(list_items)
    router.post(f"/api/admin/{node}")(create_item)
    router.patch(f"/api/admin/{node}/{{item_id}}")(update_item)
    router.delete(f"/api/admin/{node}/{{item_id}}")(delete_item)
    router.get(f"/api/admin/{node}/{{item_id}}/viewers")(viewers)
    router.get(f"/api/admin/{node}/clicks-summary")(clicks_summary)


_register_crud("dialogs", DialogIn)
_register_crud("carousel", CarouselIn)
