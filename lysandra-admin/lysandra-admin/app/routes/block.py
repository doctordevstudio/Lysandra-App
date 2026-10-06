"""
Admin management of blocked domains. The main backend reads
/config/blocked_domains (via its config cache) on every /api/v1/fetch call.
"""
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.deps import require_admin
from app.firebase_client import ref
from app.utils.admin_log import log_admin_action
from app.utils.aggregate import sum_flat
from app.utils.dates import resolve_range
from app.utils.pagination import get_page

router = APIRouter()


class BlockIn(BaseModel):
    domains: str          # newline or comma separated, possibly multiple
    message_html: str


@router.get("/api/admin/block")
async def list_blocked(admin=Depends(require_admin)):
    data = ref("/config/blocked_domains").get() or {}
    return {"items": [{"domain": k, **v} for k, v in data.items()]}


@router.post("/api/admin/block")
async def add_blocked(payload: BlockIn, request: Request, admin=Depends(require_admin)):
    raw = payload.domains.replace(",", "\n").splitlines()
    domains = []
    for d in raw:
        d = d.strip().lower()
        if not d:
            continue
        if d.startswith("www."):
            d = d[4:]
        domains.append(d)
    now_ms = int(time.time() * 1000)
    for domain in domains:
        ref(f"/config/blocked_domains/{domain}").set({"message_html": payload.message_html, "added_at": now_ms})
    log_admin_action(admin, "block_add", request.client.host, {"domains": domains})
    return {"blocked": domains}


@router.delete("/api/admin/block/{domain}")
async def remove_blocked(domain: str, request: Request, admin=Depends(require_admin)):
    ref(f"/config/blocked_domains/{domain}").delete()
    log_admin_action(admin, "block_remove", request.client.host, {"domain": domain})
    return {"removed": domain}


@router.get("/api/admin/block/summary")
async def block_summary(range: str = "today", start: str | None = None, end: str | None = None,
                         admin=Depends(require_admin)):
    date_keys = None if range == "all" else resolve_range(range, start, end)
    return {"total_hits": sum_flat("/stats/blocked", date_keys)}


@router.get("/api/admin/block/hits")
async def block_hits(date: str, cursor: str | None = None, admin=Depends(require_admin)):
    items, next_cursor = get_page(f"/logs/blocked/{date}", limit=20, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor}
