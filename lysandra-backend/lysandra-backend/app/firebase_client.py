"""
Firebase Realtime Database access, mediated entirely server-side via the
Admin SDK + a service account. The DB URL and credentials never touch the
Android app or the admin panel frontend -- both only ever talk to this
backend's own API.

Also implements the in-memory config cache the app prompt asked for:
config is loaded once at startup and refreshed on a timer (or immediately
via /internal/reload-config called by the admin panel after a save), so
hot-path requests never hit the database directly.
"""
import asyncio
import json
import time

import firebase_admin
from firebase_admin import credentials, db

from app.config import settings

_db_ref_cache: dict[str, db.Reference] = {}


def init_firebase() -> None:
    if firebase_admin._apps:
        return
    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        cred_data = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        cred = credentials.Certificate(cred_data)
    elif settings.FIREBASE_SERVICE_ACCOUNT_FILE:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_FILE)
    else:
        raise RuntimeError("No Firebase service account configured")
    firebase_admin.initialize_app(cred, {"databaseURL": settings.FIREBASE_DB_URL})


def ref(path: str) -> db.Reference:
    if path not in _db_ref_cache:
        _db_ref_cache[path] = db.reference(path)
    return _db_ref_cache[path]


class ConfigCache:
    """
    In-memory snapshot of /config in Firebase. Call .get() from request
    handlers -- it never touches the network. .refresh() re-pulls from
    Firebase and is called on a background timer and on-demand.
    """

    def __init__(self):
        self._data: dict = {}
        self._last_refresh: float = 0

    def refresh(self) -> None:
        snapshot = ref("/config").get() or {}
        self._data = snapshot
        self._last_refresh = time.time()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all(self) -> dict:
        return dict(self._data)

    @property
    def last_refresh(self) -> float:
        return self._last_refresh


config_cache = ConfigCache()


async def config_refresh_loop():
    """Background task: keeps config_cache warm without blocking requests."""
    while True:
        try:
            config_cache.refresh()
        except Exception as e:
            print(f"[config_refresh_loop] refresh failed: {e}")
        await asyncio.sleep(settings.CONFIG_REFRESH_SECONDS)
