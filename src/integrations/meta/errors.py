import httpx

# "Re-engagement message": free-form send outside the 24h window
WINDOW_CLOSED_CODE = 131047


class MetaApiError(Exception):
    """A failed Graph API call. Integration-level — services decide whether it
    becomes an AppError (sync paths) or a failed message row (background)."""

    def __init__(self, *, code: int | None, title: str, http_status: int | None = None):
        self.code = code
        self.title = title
        self.http_status = http_status
        super().__init__(f"Meta API error {code}: {title}")

    @property
    def is_window_closed(self) -> bool:
        return self.code == WINDOW_CLOSED_CODE

    @classmethod
    def from_response(cls, resp: httpx.Response) -> MetaApiError:
        try:
            error = resp.json().get("error") or {}
        except ValueError:
            error = {}
        return cls(
            code=error.get("code"),
            title=(
                error.get("error_user_title")
                or error.get("message")
                or f"HTTP {resp.status_code}"
            ),
            http_status=resp.status_code,
        )
