"""IP-based rate limiting (slowapi).

In-memory storage is correct here because the app runs exactly one worker.
Behind ngrok / a proxy the client IP comes from X-Forwarded-For, which uvicorn
trusts for connections from 127.0.0.1 (--forwarded-allow-ips default).

Usage on a route (the endpoint MUST take `request: Request`):

    @router.post("/otp/request")
    @limiter.limit(OTP_RATE_LIMIT)
    async def otp_request(request: Request, ...): ...
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

OTP_RATE_LIMIT = "5/minute;20/hour"

limiter = Limiter(key_func=get_remote_address)
