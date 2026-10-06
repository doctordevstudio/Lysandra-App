from fastapi import Cookie, HTTPException, Request

from app.security import validate_and_touch_session


async def require_admin(request: Request, admin_user: str | None = Cookie(default=None),
                         admin_token: str | None = Cookie(default=None)) -> str:
    # Minimal CSRF mitigation: cookies are SameSite=Strict + httpOnly, and we
    # also require this header, which a plain cross-site form POST can't set.
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise HTTPException(403, "Forbidden")
    if not admin_user or not admin_token:
        raise HTTPException(401, "Not authenticated")
    if not validate_and_touch_session(admin_user, admin_token):
        raise HTTPException(401, "Session expired, please log in again")
    return admin_user
