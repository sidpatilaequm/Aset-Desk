import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    database_url = os.getenv("DATABASE_URL", "mysql+pymysql://assetdesk:assetdesk@127.0.0.1:3306/assetdesk?charset=utf8mb4")
    secret_key = os.getenv("SECRET_KEY", "dev-insecure-change-me")
    base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    admin_emails = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
    upload_dir = Path(os.getenv("UPLOAD_DIR", "./uploads")).resolve()
    dev_login = _bool("DEV_LOGIN")
    cookie_secure = _bool("COOKIE_SECURE")
    ms_tenant_id = os.getenv("MS_TENANT_ID", "")
    ms_client_id = os.getenv("MS_CLIENT_ID", "")
    ms_client_secret = os.getenv("MS_CLIENT_SECRET", "")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "20"))

    @property
    def microsoft_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
