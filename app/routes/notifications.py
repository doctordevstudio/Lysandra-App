"""
App-facing notification endpoints. Admin CRUD for notifications lives in the
separate admin-panel service, writing to the same /notifications node.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.firebase_client import ref
from app.security import verify_app_identity, verify_signed_request
from app.utils.engagement import record_click, record_view
from app.utils.pagination import get_page

router = APIRouter()


@router.get("/api/v1/notifications")
async def list_notifications(request: Request, cursor: str | None = None, device_id: str = ""):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)

    items, next_cursor = get_page("/notifications", limit=20, cursor=cursor)
    items = [i for i in items if i.get("enabled", True)]
    return {"items": items, "next_cursor": next_cursor}


class EngagementBody(BaseModel):
    device_id: str
    notification_id: str


@router.post("/api/v1/notifications/seen")
async def mark_seen(payload: EngagementBody, request: Request):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)
    ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
    recorded = record_view("notifications", payload.notification_id, payload.device_id, ip)
    return {"recorded": recorded}


@router.post("/api/v1/notifications/clicked")
async def mark_clicked(payload: EngagementBody, request: Request):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)
    ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
    recorded = record_click("notifications", payload.notification_id, payload.device_id, ip)
    click_url = (ref(f"/notifications/{payload.notification_id}/click_url").get() or "")
    return {"recorded": recorded, "click_url": click_url}
