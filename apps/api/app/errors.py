from typing import Final

FRIENDLY_ERRORS: Final[dict[str, str]] = {
    "rate_limit": "Oops! It seems you've reached the rate limit. Please try again later.",
    "timeout": "That request took too long. Please try again.",
    "network": "Rivet AI can't reach the model right now. Please try again in a moment.",
    "unavailable": "Rivet AI is unavailable right now. Please try again in a moment.",
    "server_error": "Something went wrong while generating that reply. Please try again.",
    "bad_request": "That message couldn't be processed. Try rephrasing it.",
    "missing_config": "Rivet AI isn't fully set up yet. Please try again later.",
}

ERROR_STATUS: Final[dict[str, int]] = {
    "rate_limit": 429,
    "timeout": 504,
    "network": 502,
    "unavailable": 503,
    "server_error": 502,
    "bad_request": 400,
    "missing_config": 500,
}


class ChatError(Exception):
    """A failure safe to show to users; technical detail stays in the server log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.code]

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "error": FRIENDLY_ERRORS[self.code]}


def upstream_error_code(status: int) -> str:
    if status in (402, 429):
        return "rate_limit"
    if status >= 500:
        return "unavailable"
    return "server_error"
