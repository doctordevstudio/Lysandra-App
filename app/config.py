"""
Central environment/config loader for the whole service (app-facing API +
admin panel, one process). Nothing sensitive is hardcoded anywhere in this
codebase -- everything comes from environment variables so the repo can be
public/shared without leaking secrets.
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

    # ---- App-facing API (crypto, request signing) ----
    AES_KEY_B64: str = os.getenv("AES_KEY_B64", "")
    HMAC_SECRET: str = os.getenv("HMAC_SECRET", "")
    REQUEST_TTL_SECONDS: int = int(os.getenv("REQUEST_TTL_SECONDS", "90"))
    EXPECTED_APK_CERT_SHA256: str = os.getenv("EXPECTED_APK_CERT_SHA256", "").lower().replace(":", "")
    ALLOWED_PACKAGE_NAMES: list[str] = _list_env("ALLOWED_PACKAGE_NAMES")
    YOUTUBE_PROXIES: list[str] = _list_env("YOUTUBE_PROXIES")
    CONFIG_REFRESH_SECONDS: int = int(os.getenv("CONFIG_REFRESH_SECONDS", "60"))

    # ---- Firebase (shared by both the app-facing API and the admin panel) ----
    FIREBASE_SERVICE_ACCOUNT_JSON: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    FIREBASE_SERVICE_ACCOUNT_FILE: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE", "")
    FIREBASE_DB_URL: str = os.getenv("FIREBASE_DB_URL", "")

    # ---- Admin panel (raw env-var login, session, lockout) ----
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")
    SESSION_TTL_MINUTES: int = int(os.getenv("SESSION_TTL_MINUTES", "15"))
    LOCKOUT_MAX_ATTEMPTS: int = int(os.getenv("LOCKOUT_MAX_ATTEMPTS", "3"))
    LOCKOUT_DURATION_HOURS: int = int(os.getenv("LOCKOUT_DURATION_HOURS", "24"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

    def validate(self):
        missing = [
            n for n in ("AES_KEY_B64", "HMAC_SECRET", "FIREBASE_DB_URL",
                        "ADMIN_USERNAME", "ADMIN_PASSWORD", "SESSION_SECRET")
            if not getattr(self, n)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill them in."
            )


settings = Settings()
