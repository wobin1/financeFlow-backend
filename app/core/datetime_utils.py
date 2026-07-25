"""Timezone-aware datetime helpers for FinanceFlow."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
LAGOS = ZoneInfo("Africa/Lagos")


def utc_now() -> datetime:
    """Current time as timezone-aware UTC."""
    return datetime.now(UTC)


def to_aware_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC.

    Naive values are treated as UTC (legacy writers used utcnow()).
    Aware values are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_lagos_date(value: datetime) -> date:
    """Calendar date in Africa/Lagos for the given instant."""
    return to_aware_utc(value).astimezone(LAGOS).date()


def parse_iso_to_utc(value: str) -> datetime:
    """Parse an ISO-8601 string into timezone-aware UTC."""
    normalized = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return to_aware_utc(parsed)
