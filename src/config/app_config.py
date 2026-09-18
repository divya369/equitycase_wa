import structlog
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

from config.base import model_config

logger = structlog.get_logger("app_config")


class AppConfig(BaseSettings):
    # App
    app_name: str = Field(min_length=1)
    app_env: str = Field(min_length=1)
    app_host: str = Field(min_length=1)
    app_port: int = Field(gt=0, le=65535)

    # Database
    database_url: SecretStr
    db_echo: bool = False

    # Auth
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_ttl_hours: int = Field(default=720, gt=0)
    dev_static_otp: SecretStr | None = None

    # Meta WhatsApp Cloud API — secrets stay in env, never in the DB
    meta_access_token: SecretStr
    meta_app_secret: SecretStr
    meta_verify_token: SecretStr
    meta_api_version: str = Field(pattern=r"^v\d+\.\d+$")
    meta_graph_base_url: str = "https://graph.facebook.com"
    meta_http_timeout_seconds: float = 10.0
    meta_otp_template_name: str | None = None
    meta_otp_template_lang: str = "en"

    # FCM
    firebase_credentials: str | None = None

    # S3 / R2 media storage
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_public_base_url: str | None = None

    model_config = model_config

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}


def load_app_config() -> AppConfig:
    try:
        return AppConfig()
    except Exception as e:
        logger.error(f"Failed to load app config: {e}")
        raise RuntimeError("Failed to load app config") from e


app_config = load_app_config()
