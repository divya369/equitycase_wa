from pydantic import Field
from pydantic_settings import BaseSettings

from config.base import model_config


class SeedConfig(BaseSettings):
    """Read only by `python -m scripts.seed`."""

    business_phone_number_id: str = Field(min_length=1)
    # Only needed for template management (P11); sending uses phone_number_id
    business_waba_id: str | None = None
    business_display_phone: str = Field(min_length=1)
    business_verified_name: str = ""
    owner_phone: str = Field(pattern=r"^\+\d{8,15}$")
    owner_name: str = "You"

    model_config = model_config
