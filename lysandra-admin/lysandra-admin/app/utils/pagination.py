from app.firebase_client import ref


def get_page(path: str, limit: int = 20, cursor: str | None = None):
    """
    Cursor pagination over a Firebase push-id-keyed node. Newest first.
    Mirrors the main backend's helper -- duplicated here since this is a
    separately deployed service.
    """
    q = ref(path).order_by_key()
    if cursor:
        raw = q.end_at(cursor).limit_to_last(limit + 1).get() or {}
        keys = sorted(raw.keys())
        keys = [k for k in keys if k != cursor]
        keys = keys[-limit:] if len(keys) > limit else keys
    else:
        raw = q.limit_to_last(limit).get() or {}
        keys = sorted(raw.keys())

    items = [{"key": k, **(raw[k] if isinstance(raw[k], dict) else {"value": raw[k]})} for k in reversed(keys)]
    next_cursor = keys[0] if keys else None
    return items, next_cursor
