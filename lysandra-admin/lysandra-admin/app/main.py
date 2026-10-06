"""
Lysandra Admin Panel entrypoint.

Run locally:   uvicorn app.main:app --reload --port 8001
Run on Render: start command = uvicorn app.main:app --host 0.0.0.0 --port $PORT
First run:     python -m scripts.create_admin   (creates your login)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.firebase_client import init_firebase
from app.routes.auth import router as auth_router
from app.routes.block import router as block_router
from app.routes.dashboard import router as dashboard_router
from app.routes.dialogs_carousel import router as dialogs_carousel_router
from app.routes.notifications import router as notifications_router
from app.routes.settings import router as settings_router
from app.security import validate_and_touch_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    init_firebase()
    yield


app = FastAPI(title="Lysandra Admin", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)
app.include_router(dialogs_carousel_router)
app.include_router(block_router)
app.include_router(settings_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if settings.ENV != "production":
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _is_logged_in(request: Request) -> bool:
    username = request.cookies.get("admin_user")
    token = request.cookies.get("admin_token")
    return bool(username and token and validate_and_touch_session(username, token))


# ---- HTML pages (static files, gated here rather than by StaticFiles directly) ----

PAGES = ["dashboard", "notifications", "dialogs", "carousel", "block", "settings"]


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


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
