"""In-memory config cache. Loaded once, refreshed every time the admin saves
settings, so normal traffic never reads the config from the database."""
import copy
import threading

from .defaults import DEFAULT_CONFIG

PATH = "config"


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class ConfigStore:
    def __init__(self, db):
        self.db = db
        self._lock = threading.RLock()
        self._cfg = None
        self.version = 0

    def load(self):
        stored = self.db.get(PATH) or {}
        cfg = _merge(DEFAULT_CONFIG, stored)
        # Lists are stored as dicts by Firebase if they have gaps; ours are always dense lists.
        with self._lock:
            self._cfg = cfg
            self.version += 1
        if not stored:
            self.db.put(PATH, cfg)
        return cfg

    @property
    def cfg(self):
        if self._cfg is None:
            self.load()
        return self._cfg

    def get(self, section, key=None, default=None):
        sec = self.cfg.get(section, {})
        if key is None:
            return sec
        return sec.get(key, default)

    def save_section(self, section, value):
        with self._lock:
            new = copy.deepcopy(self.cfg)
            new[section] = _merge(DEFAULT_CONFIG.get(section, {}), value) if isinstance(value, dict) else value
            self.db.put(f"{PATH}/{section}", new[section])
            self._cfg = new
            self.version += 1
        return new[section]
