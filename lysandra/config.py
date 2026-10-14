"""Environment driven settings. Nothing sensitive is ever hard-coded here."""
import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def _bool(name, default=False):
    v = _env(name, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "on")


def _list(name):
    return [x.strip() for x in _env(name).replace("\n", ",").split(",") if x.strip()]


@dataclass
class Settings:
    firebase_db_url: str = ""
    firebase_db_secret: str = ""
    app_secret: str = ""
    allowed_apk_sha256: list = field(default_factory=list)
    package_name: str = "com.drdev.hamza"
    admin_user: str = "admin"
    admin_password: str = ""
    admin_password_hash: str = ""
    admin_path: str = "/lysandra-admin"
    session_secret: str = ""
    telegram_bot_token: str = ""
    telegram_admin_chat_id: str = ""
    telegram_webhook_secret: str = ""
    public_url: str = ""
    youtube_proxies: list = field(default_factory=list)
    youtube_cookies: str = ""
    terabox_api_url: str = ""
    ipintel_provider: str = "none"
    trust_cloudflare: bool = True
    origin_secret: str = ""
    cookie_secure: bool = True
    testing: bool = False
    background_jobs: bool = True

    @classmethod
    def from_env(cls):
        return cls(
            firebase_db_url=_env("FIREBASE_DB_URL").rstrip("/"),
            firebase_db_secret=_env("FIREBASE_DB_SECRET"),
            app_secret=_env("APP_SECRET"),
            allowed_apk_sha256=[x.lower().replace(":", "") for x in _list("ALLOWED_APK_SHA256")],
            package_name=_env("PACKAGE_NAME", "com.drdev.hamza"),
            admin_user=_env("ADMIN_USER", "admin"),
            admin_password=_env("ADMIN_PASSWORD"),
            admin_password_hash=_env("ADMIN_PASSWORD_HASH"),
            admin_path="/" + _env("ADMIN_PATH", "/lysandra-admin").strip("/"),
            session_secret=_env("SESSION_SECRET"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_admin_chat_id=_env("TELEGRAM_ADMIN_CHAT_ID"),
            telegram_webhook_secret=_env("TELEGRAM_WEBHOOK_SECRET"),
            public_url=_env("PUBLIC_URL").rstrip("/"),
            youtube_proxies=_list("YOUTUBE_PROXIES"),
            youtube_cookies=os.environ.get("YT_COOKIES", ""),
            terabox_api_url=_env("TERABOX_API_URL"),
            ipintel_provider=_env("IPINTEL_PROVIDER", "none").lower(),
            trust_cloudflare=_bool("TRUST_CLOUDFLARE", True),
            origin_secret=_env("ORIGIN_SECRET"),
            cookie_secure=_bool("COOKIE_SECURE", True),
        )
