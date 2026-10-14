import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from .config import IST

DEVICE_RE = re.compile(r"^[a-f0-9]{16,64}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def now_ist():
    return datetime.now(IST)


def now_ts():
    return int(time.time())


def today_str(offset_days=0):
    return (now_ist() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def ts_to_date(ts):
    return datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d")


def fmt_ist(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %I:%M %p")


def valid_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def date_range(d_from, d_to, max_days=370):
    a = datetime.strptime(d_from, "%Y-%m-%d")
    b = datetime.strptime(d_to, "%Y-%m-%d")
    if b < a:
        a, b = b, a
    out = []
    while a <= b and len(out) < max_days:
        out.append(a.strftime("%Y-%m-%d"))
        a += timedelta(days=1)
    return out


_push_lock = threading.Lock()
_push_last = [0, 0]


def push_id():
    """Strictly increasing, unique, time-sortable id (safe as a Firebase key)."""
    with _push_lock:
        ms = int(time.time() * 1000)
        if ms <= _push_last[0]:
            _push_last[1] += 1
            ms = _push_last[0]
        else:
            _push_last[0], _push_last[1] = ms, 0
        return f"{ms:013d}{_push_last[1]:03d}{secrets.token_hex(2)}"


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def const_eq(a, b):
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def clamp(s, n):
    s = "" if s is None else str(s)
    return s[:n]


def safe_key(s):
    return re.sub(r"[.$#\[\]/\s]", "_", str(s))[:120]


def to_int(v, default=0, lo=None, hi=None):
    try:
        n = int(v)
    except Exception:
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n
