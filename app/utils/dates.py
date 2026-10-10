"""
IST date-range helpers. Every dashboard metric is requested as one of:
today | yesterday | all | custom (start,end) -- this turns that into the
list of date-keys ("YYYY-MM-DD", IST) to sum /stats or scan /logs over.
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def today_key() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def yesterday_key() -> str:
    return (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")


def date_range_keys(start: str, end: str) -> list[str]:
    d0 = datetime.strptime(start, "%Y-%m-%d")
    d1 = datetime.strptime(end, "%Y-%m-%d")
    if d1 < d0:
        d0, d1 = d1, d0
    out = []
    d = d0
    while d <= d1:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def resolve_range(range_type: str, start: str | None = None, end: str | None = None) -> list[str]:
    if range_type == "today":
        return [today_key()]
    if range_type == "yesterday":
        return [yesterday_key()]
    if range_type == "custom":
        if not (start and end):
            raise ValueError("custom range requires start and end (YYYY-MM-DD)")
        return date_range_keys(start, end)
    if range_type == "all":
        return []  # caller interprets empty list as "no date filter, scan everything available"
    raise ValueError(f"unknown range_type: {range_type}")
