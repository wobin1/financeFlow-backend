"""Request correlation IDs and structured logging helpers."""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

_SENSITIVE_KEY = re.compile(
    r"(password|secret|token|authorization|authorization_code|card|cvv|bvn|pin)",
    re.I,
)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get("-")  # type: ignore[attr-defined]
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] cid=%(correlation_id)s %(message)s",
        )
    for handler in root.handlers:
        handler.addFilter(CorrelationIdFilter())


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = cid
            return response
        finally:
            correlation_id_var.reset(token)


def redact_sensitive(data: Any) -> Any:
    """Recursively redact sensitive keys from dict/list payloads before logging/storage."""
    if isinstance(data, dict):
        out: Dict[str, Any] = {}
        for key, value in data.items():
            if _SENSITIVE_KEY.search(str(key)):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_sensitive(value)
        return out
    if isinstance(data, list):
        return [redact_sensitive(item) for item in data]
    return data


def audit_log(event: str, **fields: Any) -> None:
    """Emit a security-relevant audit event.

    Retention: keep application/audit logs for at least 90 days in production
    (configure in your log shipper). Billing event payloads are redacted at write
    time; prune `billing_events` older than 24 months via ops job.
    """
    logger = logging.getLogger("financeflow.audit")
    safe = {k: redact_sensitive(v) for k, v in fields.items()}
    parts = " ".join(f"{k}={v!r}" for k, v in safe.items())
    logger.info("event=%s %s", event, parts)
