"""Firebase Realtime Database access over the plain REST `/.json` API.

The database URL only ever lives in the FIREBASE_DB_URL environment variable on
the server – it is never sent to the app or the admin browser.

`MemoryDB` implements the identical interface (including server-side
`{".sv": {"increment": n}}` and `$key` range queries) so the whole backend can
be run and tested without Firebase.
"""
import copy
import json
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _norm(path):
    return "/".join(p for p in str(path).split("/") if p)


class DBError(Exception):
    pass


class RTDB:
    def __init__(self, base_url, secret="", timeout=8):
        if not base_url:
            raise DBError("FIREBASE_DB_URL is not configured")
        self.base = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout
        self.s = requests.Session()
        retry = Retry(total=2, backoff_factor=0.3, status_forcelist=(502, 503, 504),
                      allowed_methods=None)
        self.s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=32))

    def _u(self, path):
        p = _norm(path)
        return f"{self.base}/{p}.json" if p else f"{self.base}/.json"

    def _params(self, extra=None):
        p = dict(extra or {})
        if self.secret:
            p["auth"] = self.secret
        return p

    def _req(self, method, path, params=None, data=None):
        try:
            r = self.s.request(method, self._u(path), params=self._params(params),
                               data=None if data is None else json.dumps(data), timeout=self.timeout)
        except requests.RequestException as e:
            raise DBError(f"db network error: {e.__class__.__name__}")
        if r.status_code >= 400:
            raise DBError(f"db error {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else None

    def get(self, path, order_by_key=False, start_at=None, end_at=None, limit_first=None, shallow=False):
        q = {}
        if shallow:
            q["shallow"] = "true"
        if order_by_key:
            q["orderBy"] = json.dumps("$key")
            if start_at is not None:
                q["startAt"] = json.dumps(start_at)
            if end_at is not None:
                q["endAt"] = json.dumps(end_at)
            if limit_first is not None:
                q["limitToFirst"] = str(int(limit_first))
        return self._req("GET", path, q)

    def put(self, path, value):
        return self._req("PUT", path, data=value)

    def patch(self, path, value):
        return self._req("PATCH", path, data=value)

    def delete(self, path):
        return self._req("DELETE", path)

    def increment(self, path, n=1):
        parent, _, key = _norm(path).rpartition("/")
        self._req("PATCH", parent, data={key: {".sv": {"increment": n}}})


class MemoryDB:
    def __init__(self):
        self.root = {}
        self.lock = threading.RLock()

    # -- helpers
    def _walk(self, path, create=False):
        node = self.root
        parts = [p for p in _norm(path).split("/") if p]
        for p in parts:
            if not isinstance(node, dict):
                return None
            if p not in node:
                if not create:
                    return None
                node[p] = {}
            node = node[p]
        return node

    @staticmethod
    def _prune(v):
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                x = MemoryDB._prune(x)
                if x is not None:
                    out[k] = x
            return out or None
        return v

    def _apply_sv(self, existing, v):
        if isinstance(v, dict) and ".sv" in v:
            inc = v[".sv"].get("increment", 0)
            return (existing if isinstance(existing, (int, float)) else 0) + inc
        if isinstance(v, dict):
            return {k: self._apply_sv((existing or {}).get(k) if isinstance(existing, dict) else None, x)
                    for k, x in v.items()}
        return v

    # -- API
    def get(self, path, order_by_key=False, start_at=None, end_at=None, limit_first=None, shallow=False):
        with self.lock:
            node = self._walk(path)
            node = copy.deepcopy(node)
        if node is None:
            return None
        if shallow and isinstance(node, dict):
            return {k: True for k in node}
        if order_by_key and isinstance(node, dict):
            keys = sorted(node.keys())
            if start_at is not None:
                keys = [k for k in keys if k >= start_at]
            if end_at is not None:
                keys = [k for k in keys if k <= end_at]
            if limit_first is not None:
                keys = keys[:int(limit_first)]
            return {k: node[k] for k in keys} or None
        return node

    def put(self, path, value):
        with self.lock:
            parts = [p for p in _norm(path).split("/") if p]
            value = self._prune(copy.deepcopy(value))
            if not parts:
                self.root = value or {}
                return value
            parent = self._walk("/".join(parts[:-1]), create=value is not None)
            if parent is None:
                return value
            if value is None:
                parent.pop(parts[-1], None)
            else:
                value = self._apply_sv(parent.get(parts[-1]), value)
                parent[parts[-1]] = value
            self._cleanup(parts[:-1])
            return value

    def patch(self, path, value):
        with self.lock:
            for k, v in (value or {}).items():
                self.put(_norm(path) + "/" + k if _norm(path) else k, v)
            return value

    def delete(self, path):
        return self.put(path, None)

    def increment(self, path, n=1):
        with self.lock:
            cur = self._walk(path)
            self.put(path, (cur if isinstance(cur, (int, float)) else 0) + n)

    def _cleanup(self, parts):
        # remove empty parents like Firebase does
        for i in range(len(parts), 0, -1):
            node = self._walk("/".join(parts[:i]))
            if isinstance(node, dict) and not node:
                parent = self._walk("/".join(parts[:i - 1])) if i > 1 else self.root
                if isinstance(parent, dict):
                    parent.pop(parts[i - 1], None)
            else:
                break
