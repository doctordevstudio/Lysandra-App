import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PORT: int = int(os.getenv("PORT", "8001"))
    ENV: str = os.getenv("ENV", "production")

    FIREBASE_SERVICE_ACCOUNT_JSON: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    FIREBASE_SERVICE_ACCOUNT_FILE: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE", "")
    FIREBASE_DB_URL: str = os.getenv("FIREBASE_DB_URL", "")

    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")
    SESSION_TTL_MINUTES: int = int(os.getenv("SESSION_TTL_MINUTES", "15"))
    LOCKOUT_MAX_ATTEMPTS: int = int(os.getenv("LOCKOUT_MAX_ATTEMPTS", "3"))
    LOCKOUT_DURATION_HOURS: int = int(os.getenv("LOCKOUT_DURATION_HOURS", "24"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

    MAIN_BACKEND_RELOAD_URL: str = os.getenv("MAIN_BACKEND_RELOAD_URL", "")
    MAIN_BACKEND_ADMIN_TOKEN: str = os.getenv("MAIN_BACKEND_ADMIN_TOKEN", "")

    def validate(self):
        missing = [n for n in ("SESSION_SECRET", "FIREBASE_DB_URL") if not getattr(self, n)]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


settings = Settings()
