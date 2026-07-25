"""HTTP helpers for sanitized, consistent API errors."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def http_error(
    status_code: int,
    message: str,
    *,
    log_exc: BaseException | None = None,
) -> HTTPException:
    """Build an HTTPException and optionally log the underlying exception."""
    if log_exc is not None:
        logger.exception("%s", message, exc_info=log_exc)
    return HTTPException(status_code=status_code, detail=message)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic 500 without leaking internals to clients."""
    logger.exception(
        "Unhandled error on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
