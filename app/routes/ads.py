"""
App reports every ad lifecycle event here so the admin dashboard can break
down interstitial/rewarded counts by platform (Start.io / Monetag) and by
triggering action (fetch / watch / download / page-switch).
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.security import verify_app_identity, verify_signed_request
from app.utils.logging_util import log_ad_event

router = APIRouter()


class AdEvent(BaseModel):
    device_id: str
    ad_type: str      # interstitial | rewarded | banner | native
    platform: str      # startio | monetag
    action: str        # fetch | watch | download | page_switch | ...
    page: str = ""


@router.post("/api/v1/ads/event")
async def report_ad_event(payload: AdEvent, request: Request):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)
    ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
    log_ad_event(payload.device_id, ip, payload.ad_type, payload.platform, payload.action, payload.page)
    return {"logged": True}
