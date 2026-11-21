import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import load_settings
from app.errors import ChatError, error_payload, error_status
from app.routes import attachments, chat, jobs

logger = logging.getLogger(__name__)

app = FastAPI(title="Rivet AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(load_settings().allowed_origins),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-Id"],
    max_age=600,
)

app.include_router(chat.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")


def _error_response(code: str) -> JSONResponse:
    return JSONResponse(error_payload(code), status_code=error_status(code))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(ChatError)
async def handle_chat_error(_: Request, exc: ChatError) -> JSONResponse:
    return _error_response(exc.code)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response("bad_request")


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    # traceback stays in the log; the client only gets a generic code
    logger.exception("Unhandled error in Rivet AI API")
    return _error_response("server_error")
