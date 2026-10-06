"""
Shared sort-order shifting for Dialogs and Carousel: inserting a new item at
sort_order N pushes every existing item with sort_order >= N up by one, per
the admin panel spec.
"""
from app.firebase_client import ref


def shift_and_insert(node: str, new_sort_order: int, item_id: str) -> None:
    all_items = ref(f"/{node}").get() or {}
    for existing_id, data in all_items.items():
        if existing_id == item_id:
            continue
        existing_order = data.get("sort_order", 0)
        if existing_order >= new_sort_order:
            ref(f"/{node}/{existing_id}/sort_order").set(existing_order + 1)
