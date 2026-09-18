"""Phone number helpers. Import-safe (used by the seed script too).

Identity everywhere is the wa_id: E.164 digits without '+', e.g. 919820011223.
"""

import re
from typing import Annotated

from pydantic import StringConstraints

# Lenient on formatting (+, spaces, dashes, brackets); compare via to_wa_id()
PhoneStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\+?[\d\s\-()]{8,20}$"),
]


def to_wa_id(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def to_display_phone(phone: str) -> str:
    """Keep the operator's spacing, but always lead with '+'."""
    phone = phone.strip()
    return phone if phone.startswith("+") else f"+{phone}"
