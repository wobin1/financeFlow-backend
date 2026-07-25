"""ISO 4217 currency validation helpers."""

from __future__ import annotations

from typing import Optional

# Supported reporting currencies. Expand deliberately — aggregates never mix codes.
SUPPORTED_CURRENCIES = frozenset(
    {
        "NGN",
        "USD",
        "EUR",
        "GBP",
        "GHS",
        "KES",
        "ZAR",
        "CAD",
        "XOF",
        "XAF",
    }
)
DEFAULT_CURRENCY = "NGN"


def normalize_currency(code: Optional[str], *, default: str = DEFAULT_CURRENCY) -> str:
    """Return an uppercase ISO 4217 code or raise ValueError."""
    raw = (code or default).strip().upper()
    if not raw:
        raw = default
    if raw not in SUPPORTED_CURRENCIES:
        raise ValueError(
            f"Unsupported currency '{code}'. Allowed: {', '.join(sorted(SUPPORTED_CURRENCIES))}"
        )
    return raw
