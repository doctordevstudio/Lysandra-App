import json

import firebase_admin
from firebase_admin import credentials, db

from app.config import settings


def init_firebase() -> None:
    if firebase_admin._apps:
        return
    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        cred = credentials.Certificate(json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON))
    elif settings.FIREBASE_SERVICE_ACCOUNT_FILE:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_FILE)
    else:
        raise RuntimeError("No Firebase service account configured")
    firebase_admin.initialize_app(cred, {"databaseURL": settings.FIREBASE_DB_URL})


_ref_cache: dict = {}


def ref(path: str) -> db.Reference:
    if path not in _ref_cache:
        _ref_cache[path] = db.reference(path)
    return _ref_cache[path]
