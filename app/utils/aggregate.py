"""
Summing helpers over the main backend's /stats/* counters for a given set
of date-keys (today / yesterday / custom range) or grand-total ("all",
passed as date_keys=None).
"""
from app.firebase_client import ref


def sum_flat(base_path: str, date_keys: list[str] | None) -> int:
    """base_path/<date> is a plain integer counter."""
    if date_keys is None:  # "all time"
        data = ref(base_path).get() or {}
        return sum(v for v in data.values() if isinstance(v, (int, float)))
    total = 0
    for d in date_keys:
        v = ref(f"{base_path}/{d}").get()
        if isinstance(v, (int, float)):
            total += v
    return total


def _merge_into(acc: dict, node: dict) -> dict:
    for k, v in node.items():
        if isinstance(v, dict):
            acc[k] = _merge_into(acc.get(k, {}), v)
        elif isinstance(v, (int, float)):
            acc[k] = acc.get(k, 0) + v
    return acc


def sum_nested(base_path: str, date_keys: list[str] | None) -> dict:
    """base_path/<date>/... is an arbitrarily nested tree of integer counters
    (e.g. /stats/ads/<date>/<ad_type>/<platform>/<action>). Returns the
    merged nested dict, summed across the requested dates."""
    merged: dict = {}
    if date_keys is None:
        data = ref(base_path).get() or {}
        for day_node in data.values():
            if isinstance(day_node, dict):
                _merge_into(merged, day_node)
    else:
        for d in date_keys:
            day_node = ref(f"{base_path}/{d}").get()
            if isinstance(day_node, dict):
                _merge_into(merged, day_node)
    return merged
