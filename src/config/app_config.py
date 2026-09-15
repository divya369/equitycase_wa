import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger("app_config")

model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


class AppConfig(BaseSettings):
    app_name: str = Field(min_length=1)
    app_env: str = Field(min_length=1)
    app_host: str = Field(min_length=1)
    app_port: int = Field(gt=0, le=65535)

    model_config = model_config


def load_app_config() -> AppConfig:
    try:
        return AppConfig()
    except Exception as e:
        logger.error(f"Failed to load app config: {e}")
        raise RuntimeError("Failed to load app config") from e


app_config = load_app_config()
