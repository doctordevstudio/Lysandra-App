"""
App-facing "supported platforms" list for the Apps tab -- name, icon, sort
order, highlight flag. Admin CRUD lives in the admin panel (reuses the same
generic pattern as dialogs/carousel -- see lysandra-admin's
dialogs_carousel.py for how to add a `_register_crud("supported_apps", ...)`
call there if you want a UI for this; until then it can be edited directly
in the Firebase console under /supported_apps).
"""
from fastapi import APIRouter, Request

from app.firebase_client import ref
from app.security import verify_app_identity, verify_signed_request

router = APIRouter()


@router.get("/api/v1/platforms")
async def list_platforms(request: Request):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)

    raw = ref("/supported_apps").get() or {}
    items = [{"id": k, **v} for k, v in raw.items() if v.get("enabled", True)]
    items.sort(key=lambda i: i.get("sort_order", 0))
    return {"items": items}
