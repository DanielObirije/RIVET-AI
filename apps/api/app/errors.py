from typing import Final

FRIENDLY_ERRORS: Final[dict[str, str]] = {
    "rate_limit": "Oops! It seems you've reached the rate limit. Please try again later.",
    "timeout": "That request took too long. Please try again.",
    "network": "Rivet AI can't reach the model right now. Please try again in a moment.",
    "unavailable": "Rivet AI is unavailable right now. Please try again in a moment.",
    "server_error": "Something went wrong while generating that reply. Please try again.",
    "bad_request": "That message couldn't be processed. Try rephrasing it.",
    "missing_config": "Rivet AI isn't fully set up yet. Please try again later.",
    "not_found": "That request is no longer available.",
    "enqueue_failed": "Rivet AI couldn't start that request. Please try again in a moment.",
    "not_retryable": "That reply already finished, so there is nothing to retry.",
    "unsupported_file": "That file type isn't supported. Attach a PDF or JPEG file.",
    "file_too_large": "That file is too large. Please attach a smaller file.",
    "forbidden": "That attachment isn't available for this request.",
    "attachment_not_ready": "That upload hasn't finished yet. Try again in a moment.",
    "attachment_missing": "That attachment is no longer available.",
    "attachment_unreadable": "I couldn't read that file. It may be corrupt or a scanned document.",
    "image_unsupported": "The current AI model can't read images. Attach a PDF instead.",
    "storage_unavailable": "File storage isn't available right now. Please try again.",
}

ERROR_STATUS: Final[dict[str, int]] = {
    "rate_limit": 429,
    "timeout": 504,
    "network": 502,
    "unavailable": 503,
    "server_error": 502,
    "bad_request": 400,
    "missing_config": 500,
    "not_found": 404,
    "enqueue_failed": 503,
    "not_retryable": 409,
    "unsupported_file": 400,
    "file_too_large": 400,
    "forbidden": 403,
    "attachment_not_ready": 409,
    "attachment_missing": 404,
    "attachment_unreadable": 422,
    "image_unsupported": 415,
    "storage_unavailable": 503,
}


class ChatError(Exception):
    """A failure safe to show to users; technical detail stays in the server log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def error_status(code: str) -> int:
    return ERROR_STATUS[code]


def error_payload(code: str) -> dict[str, str]:
    return {"code": code, "error": FRIENDLY_ERRORS[code]}
