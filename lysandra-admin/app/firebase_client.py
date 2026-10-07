import json

import firebase_admin
from firebase_admin import credentials, db

from app.config import settings


def init_firebase() -> None:
    if firebase_admin._apps:
        return
    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        raw = settings.FIREBASE_SERVICE_ACCOUNT_JSON.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            snippet = raw[:20].replace("\n", "\\n")
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON "
                f"({e}). The value starts with: {snippet!r} -- it must start "
                "with '{' and end with '}' and nothing else. A common cause "
                "is accidentally copying a line number or an extra quote "
                "along with the JSON when pasting it into Render's env var "
                "box; re-copy just the JSON itself, or use "
                "FIREBASE_SERVICE_ACCOUNT_FILE with a Render Secret File "
                "instead to avoid this entirely."
            ) from e
        cred = credentials.Certificate(parsed)
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
