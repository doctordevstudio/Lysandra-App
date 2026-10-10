"""
Lysandra -- single service: the app-facing API (/api/v1/*) and the admin
panel (/api/admin/* + its HTML pages), one FastAPI process, one Firebase
client, one config cache.

Run locally:   uvicorn app.main:app --reload --port 8000
Run on Render: start command = uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.admin_security import validate_and_touch_session
from app.config import settings
from app.firebase_client import config_cache, config_refresh_loop, init_firebase

# App-facing routers (talk to the Android app, under /api/v1/*)
from app.routes.ads import router as ads_router
from app.routes.carousel_dialog import router as carousel_dialog_router
from app.routes.config_route import router as config_router
from app.routes.fetch import router as fetch_router
from app.routes.notifications import router as notifications_router
from app.routes.platforms import router as platforms_router

# Admin routers (talk to the admin panel UI, under /api/admin/*)
from app.routes.admin_apps import router as admin_apps_router
from app.routes.admin_auth import router as admin_auth_router
from app.routes.admin_block import router as admin_block_router
from app.routes.admin_dashboard import router as admin_dashboard_router
from app.routes.admin_dialogs_carousel import router as admin_dialogs_carousel_router
from app.routes.admin_notifications import router as admin_notifications_router
from app.routes.admin_settings import router as admin_settings_router

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
_refresh_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    init_firebase()
    config_cache.refresh()
    global _refresh_task
    _refresh_task = asyncio.create_task(config_refresh_loop())
    yield
    if _refresh_task:
        _refresh_task.cancel()


app = FastAPI(title="Lysandra", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
# docs disabled in prod on purpose -- no need to advertise the API surface publicly.

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# No CORS middleware: the admin UI's JS calls /api/admin/* on the same origin
# it was served from (one process now, not two), and the Android app never
# goes through a browser, so CORS was never relevant to it either.

app.include_router(fetch_router)
app.include_router(config_router)
app.include_router(notifications_router)
app.include_router(carousel_dialog_router)
app.include_router(ads_router)
app.include_router(platforms_router)

app.include_router(admin_auth_router)
app.include_router(admin_apps_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_notifications_router)
app.include_router(admin_dialogs_carousel_router)
app.include_router(admin_block_router)
app.include_router(admin_settings_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces / internals to clients (OWASP A05/A09).
    if settings.ENV != "production":
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---- Health check -- MUST be registered before the /{page} catch-all below.
# Starlette matches routes in registration order; a literal route only wins
# over a catch-all pattern if it was added first; in the admin-only version of
# this file, /healthz was added AFTER /{page} and so was actually unreachable
# (swallowed by the catch-all, which 404s anything not in PAGES). Fixed here
# by registering it first.
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---- Admin HTML pages (static files, gated here rather than by StaticFiles directly) ----

PAGES = ["dashboard", "notifications", "dialogs", "carousel", "block", "settings", "apps"]
# "apps" (supported-platforms grid) isn't in the spec's nav drawer list, so it's
# not a sidebar link -- reachable via the "Manage Supported Platforms" link on Settings.


def _is_logged_in(request: Request) -> bool:
    username = request.cookies.get("admin_user")
    token = request.cookies.get("admin_token")
    return bool(username and token and validate_and_touch_session(username, token))


@app.get("/")
async def root(request: Request):
    return RedirectResponse("/dashboard" if _is_logged_in(request) else "/login")


@app.get("/login")
async def login_page(request: Request):
    if _is_logged_in(request):
        return RedirectResponse("/dashboard")
    return FileResponse("static/login.html")


@app.get("/{page}")
async def page(page: str, request: Request):
    if page not in PAGES:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if not _is_logged_in(request):
        return RedirectResponse("/login")
    return FileResponse(f"static/{page}.html")
