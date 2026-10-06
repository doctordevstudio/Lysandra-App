"""
Lysandra backend entrypoint.

Run locally:   uvicorn app.main:app --reload --port 8000
Run on Render: start command = uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.firebase_client import config_cache, config_refresh_loop, init_firebase
from app.routes.ads import router as ads_router
from app.routes.carousel_dialog import router as carousel_dialog_router
from app.routes.config_route import router as config_router
from app.routes.fetch import router as fetch_router
from app.routes.notifications import router as notifications_router

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


app = FastAPI(title="Lysandra Backend", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
# docs disabled in prod on purpose -- no need to advertise the API surface publicly.

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ADMIN_PANEL_ORIGINS,  # the app itself doesn't need CORS -- it's not a browser
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(fetch_router)
app.include_router(config_router)
app.include_router(notifications_router)
app.include_router(carousel_dialog_router)
app.include_router(ads_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces / internals to clients (OWASP A05/A09).
    if settings.ENV != "production":
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
