"""
Dashboard: user counts, fetch/ads/blocked totals by range, drilldown lists,
top-50 users, per-user detail.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import require_admin
from app.firebase_client import ref
from app.utils.aggregate import sum_flat, sum_nested
from app.utils.dates import resolve_range, today_key, yesterday_key
from app.utils.pagination import get_page

router = APIRouter()


def _keys_or_none(range_type: str, start, end):
    return None if range_type == "all" else resolve_range(range_type, start, end)


@router.get("/api/admin/dashboard/summary")
async def summary(range: str = "today", start: str | None = None, end: str | None = None,
                   admin=Depends(require_admin)):
    try:
        date_keys = _keys_or_none(range, start, end)
    except ValueError as e:
        raise HTTPException(400, str(e))

    new_users = sum_flat("/stats/new_users_count", date_keys)

    # /stats/fetch/<date>/{success|failed} is one level deeper than sum_flat handles,
    # so it's summed explicitly here rather than via the generic helper.
    fetch_success_total = 0
    fetch_failed_total = 0
    if date_keys is None:
        all_fetch = ref("/stats/fetch").get() or {}
        for day_node in all_fetch.values():
            if isinstance(day_node, dict):
                fetch_success_total += day_node.get("success", 0) or 0
                fetch_failed_total += day_node.get("failed", 0) or 0
    else:
        for d in date_keys:
            day_node = ref(f"/stats/fetch/{d}").get() or {}
            fetch_success_total += day_node.get("success", 0) or 0
            fetch_failed_total += day_node.get("failed", 0) or 0

    blocked_hits = sum_flat("/stats/blocked", date_keys)
    maintenance_hits = sum_flat("/stats/maintenance_count", date_keys)
    ads_breakdown = sum_nested("/stats/ads", date_keys)  # {ad_type: {platform: {action: count}}}

    total_users = ref("/stats/total_users_count").get() or 0

    today_active = set((ref(f"/stats/daily_active/{today_key()}").get() or {}).keys())
    yesterday_active = set((ref(f"/stats/daily_active/{yesterday_key()}").get() or {}).keys())
    yesterday_active_today_count = len(today_active & yesterday_active)

    return {
        "range": range,
        "date_keys": date_keys,  # None means "all time"; frontend uses the last entry as the drilldown default date
        "new_users": new_users,
        "total_users": total_users,
        "yesterday_active_today": yesterday_active_today_count,
        "fetch_success": fetch_success_total,
        "fetch_failed": fetch_failed_total,
        "blocked_hits": blocked_hits,
        "maintenance_hits": maintenance_hits,
        "ads_breakdown": ads_breakdown,
    }


@router.get("/api/admin/dashboard/drilldown")
async def drilldown(category: str, date: str, cursor: str | None = None, limit: int = 20,
                     admin=Depends(require_admin)):
    """
    category one of: new_users | fetch_success | fetch_failed | blocked | maintenance
                      | notifications_view | notifications_click | dialogs_view | dialogs_click
                      | carousel_view | carousel_click
    date must be a specific YYYY-MM-DD (IST). For "all time"/"custom range" totals shown on
    the summary card, the admin picks an individual date here to see that day's user list --
    see README "Drilldown pagination" for why it's per-day rather than range-flattened.
    """
    path_map = {
        "new_users": f"/logs/new_users/{date}",
        "fetch_success": f"/logs/fetch/{date}",
        "fetch_failed": f"/logs/fetch/{date}",
        "blocked": f"/logs/blocked/{date}",
        "maintenance": f"/logs/maintenance/{date}",
        "notifications_view": f"/logs/notifications_view_daily/{date}",
        "notifications_click": f"/logs/notifications_click_daily/{date}",
        "dialogs_view": f"/logs/dialogs_view_daily/{date}",
        "dialogs_click": f"/logs/dialogs_click_daily/{date}",
        "carousel_view": f"/logs/carousel_view_daily/{date}",
        "carousel_click": f"/logs/carousel_click_daily/{date}",
    }
    if category not in path_map:
        raise HTTPException(400, "Unknown category")

    items, next_cursor = get_page(path_map[category], limit=limit, cursor=cursor)
    if category == "fetch_success":
        items = [i for i in items if i.get("success") is True]
    elif category == "fetch_failed":
        items = [i for i in items if i.get("success") is False]

    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/admin/dashboard/ads-drilldown")
async def ads_drilldown(date: str, ad_type: str, platform: str, action: str,
                         cursor: str | None = None, limit: int = 20, admin=Depends(require_admin)):
    items, next_cursor = get_page(f"/logs/ads/{date}", limit=limit, cursor=cursor)
    composite = f"{ad_type}_{platform}_{action}"
    items = [i for i in items if i.get("composite") == composite]
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/admin/dashboard/top-users")
async def top_users(limit: int = 50, admin=Depends(require_admin)):
    raw = ref("/stats/user_fetch_count").order_by_value().limit_to_last(limit).get() or {}
    device_ids = sorted(raw.keys(), key=lambda k: raw[k], reverse=True)

    results = []
    for device_id in device_ids:
        ads = ref(f"/stats/user_ads_count/{device_id}").get() or {}
        device_info = ref(f"/devices/{device_id}").get() or {}
        results.append({
            "device_id": device_id,
            "fetch_count": raw[device_id],
            "interstitial_watched": ads.get("interstitial", 0),
            "rewarded_watched": ads.get("rewarded", 0),
            "last_ip": device_info.get("last_ip"),
            "last_seen": device_info.get("last_seen"),
        })
    return {"items": results}


@router.get("/api/admin/dashboard/user/{device_id}")
async def user_detail(device_id: str, admin=Depends(require_admin)):
    device = ref(f"/devices/{device_id}").get()
    if not device:
        raise HTTPException(404, "Unknown device")
    history = device.get("history", {})
    history_list = sorted(history.values(), key=lambda h: h.get("ts", 0), reverse=True) if isinstance(history, dict) else []
    return {
        "device_id": device_id,
        "first_seen": device.get("first_seen"),
        "last_seen": device.get("last_seen"),
        "last_ip": device.get("last_ip"),
        "ip_history": history_list,
        "fetch_count": ref(f"/stats/user_fetch_count/{device_id}").get() or 0,
        "ads_watched": ref(f"/stats/user_ads_count/{device_id}").get() or {},
    }
