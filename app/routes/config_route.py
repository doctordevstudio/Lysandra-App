"""
GET /api/v1/config -- app-launch config (ad unit ids, feature flags,
maintenance mode, latest version, etc). Signed-request only, so this
can't be scraped for your ad unit IDs / feature flags by randoms.

POST /internal/reload-config -- called by the admin panel right after a
settings save, so changes go live immediately instead of waiting for the
periodic refresh.
"""
from fastapi import APIRouter, Header, HTTPException, Request

from app.firebase_client import config_cache
from app.security import verify_app_identity, verify_signed_request
from app.config import settings
from app.utils.logging_util import log_maintenance_hit

router = APIRouter()

# Keys that are safe to hand to the client. Never return the whole
# config_cache -- it may contain admin-only fields later.
PUBLIC_CONFIG_KEYS = [
    "startio_app_id", "startio_banner_id", "startio_interstitial_id", "startio_rewarded_id", "startio_native_id",
    "monetag_zone_id", "monetag_direct_link_url",
    "ads_enabled",
    "carousel_enabled", "dialog_enabled",
    "maintenance_mode", "maintenance_message_html",
    "latest_version", "update_channel_url",
    "terms_html", "privacy_html",
    "customer_support_telegram", "developer_telegram", "developer_name",
    "developer_bio", "developer_image_url", "developer_rate",
    "theme_default", "theme_allow_toggle",
]


@router.get("/api/v1/config")
async def get_config(request: Request, x_device_id: str = Header(default="")):
    body_raw = await request.body()
    verify_signed_request(request, body_raw)
    verify_app_identity(request)

    data = config_cache.all()
    if data.get("maintenance_mode") and x_device_id:
        ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
        log_maintenance_hit(x_device_id, ip)

    return {k: data.get(k) for k in PUBLIC_CONFIG_KEYS if k in data}


@router.post("/internal/reload-config")
async def reload_config(x_admin_token: str = Header(default="")):
    if not settings.ADMIN_RELOAD_TOKEN or x_admin_token != settings.ADMIN_RELOAD_TOKEN:
        raise HTTPException(403, "Forbidden")
    config_cache.refresh()
    return {"reloaded": True, "at": config_cache.last_refresh}
