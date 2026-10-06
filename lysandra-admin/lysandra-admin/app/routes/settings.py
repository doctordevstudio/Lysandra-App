"""
Full app config editor: ad network credentials + enable/disable, theme,
Terms/Privacy/Support/Developer content, maintenance mode. Every save
pushes /config/* to Firebase AND pokes the main backend's
/internal/reload-config so changes go live immediately (no 60s wait).
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import settings
from app.deps import require_admin
from app.firebase_client import ref
from app.utils.admin_log import log_admin_action

router = APIRouter()

ALLOWED_SETTINGS_KEYS = {
    # Ads
    "ads_enabled", "startio_enabled", "monetag_enabled",
    "startio_app_id", "startio_banner_id", "startio_interstitial_id",
    "startio_rewarded_id", "startio_native_id",
    "monetag_zone_id", "monetag_direct_link_url",
    # Content toggles
    "carousel_enabled", "dialog_enabled",
    # Theme
    "theme_default", "theme_allow_toggle",
    # Legal / support / developer (editable HTML/text, shown in-app)
    "terms_html", "privacy_html",
    "customer_support_telegram", "developer_telegram", "developer_name",
    "developer_bio", "developer_image_url", "developer_rate",
    # Versioning / update nudge
    "latest_version", "update_channel_url",
    # YouTube extraction
    "youtube_proxies",
    # Maintenance
    "maintenance_mode", "maintenance_message_html",
}


async def _reload_main_backend():
    if not settings.MAIN_BACKEND_RELOAD_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(settings.MAIN_BACKEND_RELOAD_URL,
                               headers={"X-Admin-Token": settings.MAIN_BACKEND_ADMIN_TOKEN})
    except Exception:
        pass  # best effort -- the main backend's own periodic refresh will pick it up anyway


@router.get("/api/admin/settings")
async def get_settings(admin=Depends(require_admin)):
    data = ref("/config").get() or {}
    data.pop("blocked_domains", None)  # managed on its own page
    return data


@router.patch("/api/admin/settings")
async def update_settings(payload: dict, request: Request, admin=Depends(require_admin)):
    update = {k: v for k, v in payload.items() if k in ALLOWED_SETTINGS_KEYS}
    if not update:
        raise HTTPException(400, "Nothing valid to update")
    ref("/config").update(update)
    await _reload_main_backend()
    log_admin_action(admin, "settings_update", request.client.host, {"keys": list(update.keys())})
    return {"updated": list(update.keys())}
