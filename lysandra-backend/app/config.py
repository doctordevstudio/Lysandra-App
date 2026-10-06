"""
Central environment/config loader. Nothing sensitive is hardcoded anywhere
in this codebase -- everything comes from environment variables so the repo
can be public/shared without leaking secrets.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _list_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


class Settings:
    PORT: int = int(os.getenv("PORT", "8000"))
    ENV: str = os.getenv("ENV", "production")

    AES_KEY_B64: str = os.getenv("AES_KEY_B64", "")
    HMAC_SECRET: str = os.getenv("HMAC_SECRET", "")
    REQUEST_TTL_SECONDS: int = int(os.getenv("REQUEST_TTL_SECONDS", "90"))

    EXPECTED_APK_CERT_SHA256: str = os.getenv("EXPECTED_APK_CERT_SHA256", "").lower().replace(":", "")
    ALLOWED_PACKAGE_NAMES: list[str] = _list_env("ALLOWED_PACKAGE_NAMES")

    FIREBASE_SERVICE_ACCOUNT_JSON: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    FIREBASE_SERVICE_ACCOUNT_FILE: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE", "")
    FIREBASE_DB_URL: str = os.getenv("FIREBASE_DB_URL", "")

    ADMIN_RELOAD_TOKEN: str = os.getenv("ADMIN_RELOAD_TOKEN", "")
    CONFIG_REFRESH_SECONDS: int = int(os.getenv("CONFIG_REFRESH_SECONDS", "60"))

    YOUTUBE_PROXIES: list[str] = _list_env("YOUTUBE_PROXIES")

    ADMIN_PANEL_ORIGINS: list[str] = _list_env("ADMIN_PANEL_ORIGINS")

    def validate(self):
        missing = [
            n for n in ("AES_KEY_B64", "HMAC_SECRET", "FIREBASE_DB_URL")
            if not getattr(self, n)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill them in."
            )


settings = Settings()
