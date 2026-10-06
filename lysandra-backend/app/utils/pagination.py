"""
Cursor-based pagination over a Firebase RTDB list-of-pushed-children node.
Firebase push IDs are lexicographically sortable by creation time, so
ordering by key gives newest-first naturally. Used for history, notifications,
and every admin "load more" / drilldown list.
"""
from app.firebase_client import ref


def get_page(path: str, limit: int = 20, cursor: str | None = None):
    """
    Returns (items, next_cursor) where items is a list of (key, value) dicts,
    newest first. Pass next_cursor back in as `cursor` to get the next
    (older) page; next_cursor is None when there's nothing more.
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
