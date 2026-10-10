"""
Full app config editor: ad network credentials + enable/disable, theme,
Terms/Privacy/Support/Developer content, maintenance mode. Every save
pushes /config/* to Firebase AND refreshes the in-memory config_cache that
the app-facing /api/v1/* routes read from, so changes go live immediately
(no waiting for the periodic refresh). This used to be a cross-service
HTTP call to a separate backend process; now that the admin panel and the
backend share one process, it's just a direct function call.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import require_admin
from app.firebase_client import config_cache, ref
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
    config_cache.refresh()
    log_admin_action(admin, "settings_update", request.client.host, {"keys": list(update.keys())})
    return {"updated": list(update.keys())}
