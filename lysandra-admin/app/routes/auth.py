"""
Admin login/logout. Single active session per username, 15-min sliding
expiry, 3-failed-attempts -> 24h lockout keyed by client fingerprint.
"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings
from app.firebase_client import ref
from app.security import (create_session, destroy_session, fingerprint_hash, is_locked,
                           record_failed_attempt, reset_attempts, verify_password)
from app.utils.admin_log import log_admin_action

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str
    fp: str  # client-computed fingerprint (see static/js/fingerprint.js)


def _client_ip(request: Request) -> str:
    return request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()


@router.post("/api/admin/login")
async def login(payload: LoginBody, request: Request, response: Response):
    ip = _client_ip(request)
    fp_hash = fingerprint_hash(payload.fp, ip)

    locked, locked_until = is_locked(fp_hash)
    if locked:
        raise HTTPException(423, {"locked": True, "locked_until": locked_until})

    user_data = ref(f"/admin_auth/users/{payload.username}").get()
    ok = bool(user_data) and verify_password(payload.password, user_data.get("password_hash", ""))

    ref(f"/admin_auth/login_attempts/{payload.username}").push({
        "ip": ip, "fingerprint": fp_hash, "success": ok,
        "ts": int(__import__("time").time() * 1000),
    })

    if not ok:
        record_failed_attempt(fp_hash)
        log_admin_action(payload.username, "login_failed", ip)
        raise HTTPException(401, "Invalid username or password")

    reset_attempts(fp_hash)
    token = create_session(payload.username, ip, fp_hash)
    log_admin_action(payload.username, "login_success", ip)

    cookie_kwargs = dict(httponly=True, samesite="strict", secure=settings.COOKIE_SECURE,
                          max_age=settings.SESSION_TTL_MINUTES * 60)
    response.set_cookie("admin_user", payload.username, **cookie_kwargs)
    response.set_cookie("admin_token", token, **cookie_kwargs)
    return {"username": payload.username, "session_ttl_minutes": settings.SESSION_TTL_MINUTES}


@router.post("/api/admin/logout")
async def logout(request: Request, response: Response):
    username = request.cookies.get("admin_user")
    if username:
        destroy_session(username)
        log_admin_action(username, "logout", _client_ip(request))
    response.delete_cookie("admin_user")
    response.delete_cookie("admin_token")
    return {"logged_out": True}
