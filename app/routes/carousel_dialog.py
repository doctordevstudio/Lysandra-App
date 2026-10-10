"""
App-facing Carousel and Dialog endpoints. Both are sort-ordered, admin-CRUD
content types (CRUD lives in the admin-panel service). Grouped in one file
since their app-facing shape is identical.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.firebase_client import ref
from app.security import verify_app_identity, verify_signed_request
from app.utils.engagement import record_click, record_view

router = APIRouter()


def _sorted_enabled(node: str) -> list[dict]:
    raw = ref(f"/{node}").get() or {}
    items = [{"id": k, **v} for k, v in raw.items() if v.get("enabled", True)]
    items.sort(key=lambda i: i.get("sort_order", 0))
    return items


@router.get("/api/v1/carousel")
async def list_carousel(request: Request):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)
    return {"items": _sorted_enabled("carousel")}


@router.get("/api/v1/dialogs")
async def list_dialogs(request: Request):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)
    return {"items": _sorted_enabled("dialogs")}


class EngagementBody(BaseModel):
    device_id: str
    item_id: str


def _make_handlers(entity_type: str):
    async def seen(payload: EngagementBody, request: Request):
        body_raw = await request.body()
        verify_signed_request(request, body_raw)
        verify_app_identity(request)
        ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
        recorded = record_view(entity_type, payload.item_id, payload.device_id, ip)
        return {"recorded": recorded}

    async def clicked(payload: EngagementBody, request: Request):
        body_raw = await request.body()
        verify_signed_request(request, body_raw)
        verify_app_identity(request)
        ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
        recorded = record_click(entity_type, payload.item_id, payload.device_id, ip)
        click_url = ref(f"/{entity_type}/{payload.item_id}/click_url").get() or ""
        return {"recorded": recorded, "click_url": click_url}

    return seen, clicked


_carousel_seen, _carousel_clicked = _make_handlers("carousel")
_dialog_seen, _dialog_clicked = _make_handlers("dialogs")

router.post("/api/v1/carousel/seen")(_carousel_seen)
router.post("/api/v1/carousel/clicked")(_carousel_clicked)
router.post("/api/v1/dialogs/seen")(_dialog_seen)
router.post("/api/v1/dialogs/clicked")(_dialog_clicked)
