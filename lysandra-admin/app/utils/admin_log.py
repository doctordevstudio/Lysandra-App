import time

from app.firebase_client import ref
from app.utils.dates import today_key


def log_admin_action(username: str, action: str, ip: str, details: dict | None = None) -> None:
    ref(f"/admin_logs/{today_key()}").push({
        "username": username, "action": action, "ip": ip,
        "details": details or {}, "ts": int(time.time() * 1000),
    })
