from pydantic import SecretStr
from pydantic_settings import BaseSettings

from config.base import model_config


class DatabaseConfig(BaseSettings):
    """Read by Alembic, so migrations don't need the full app env."""

    database_url: SecretStr

    model_config = model_config
