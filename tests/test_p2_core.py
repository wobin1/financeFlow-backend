"""Unit tests for currency, datetime, security, Mono webhook, and FIRS money helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.currency import normalize_currency
from app.core.datetime_utils import as_lagos_date, parse_iso_to_utc, to_aware_utc, utc_now
from app.core.logging_utils import redact_sensitive
from app.core.security import (
    create_access_token,
    get_password_hash,
    revoke_token,
    verify_password,
    verify_token,
)
from app.services.firs_service import _money, _period_bounds
from app.services.mono_service import MonoService
from app.api.api_v1.endpoints.mono import _assert_owns_mono_account
from fastapi import HTTPException


def test_normalize_currency_accepts_supported():
    assert normalize_currency("ngn") == "NGN"
    assert normalize_currency("USD") == "USD"


def test_normalize_currency_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_currency("BTC")


def test_lagos_date_crosses_utc_midnight():
    # 23:30 UTC on Dec 31 is 00:30 Africa/Lagos on Jan 1
    dt = parse_iso_to_utc("2025-12-31T23:30:00+00:00")
    assert as_lagos_date(dt).isoformat() == "2026-01-01"


def test_to_aware_utc_converts_offset():
    naiveish = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert to_aware_utc(naiveish).tzinfo is not None
    assert utc_now().tzinfo is not None


def test_password_hash_roundtrip_and_legacy():
    import base64
    import hashlib
    import secrets

    modern = get_password_hash("correct-horse")
    assert modern.startswith("pbkdf2_sha256$")
    assert verify_password("correct-horse", modern)
    assert not verify_password("wrong", modern)

    # Legacy format: base64(salt + hash) @ 100k iterations
    salt = secrets.token_bytes(32)
    legacy_hash = hashlib.pbkdf2_hmac("sha256", b"legacy-pass", salt, 100_000)
    legacy = base64.b64encode(salt + legacy_hash).decode("ascii")
    assert verify_password("legacy-pass", legacy)
    assert not verify_password("nope", legacy)


def test_jwt_revoke():
    token = create_access_token({"sub": "user@example.com"})
    assert verify_token(token) == "user@example.com"
    assert revoke_token(token) is True
    assert verify_token(token) is None


def test_mono_webhook_header_secret(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MONO_WEBHOOK_SECRET", "whsec_test")
    service = MonoService()

    import asyncio

    ok = asyncio.run(service.verify_webhook(b"{}", header_secret="whsec_test"))
    bad = asyncio.run(service.verify_webhook(b"{}", header_secret="wrong"))
    assert ok is True
    assert bad is False


def test_assert_owns_mono_account():
    user = {"plaid_access_token": "acc_123"}
    _assert_owns_mono_account(user, "acc_123")
    with pytest.raises(HTTPException) as exc:
        _assert_owns_mono_account(user, "acc_other")
    assert exc.value.status_code == 404


def test_firs_money_and_period():
    assert _money(Decimal("12.346")) == "12.35"
    assert _money(Decimal("10")) == "10.00"
    start, end = _period_bounds(2026, 2)
    assert start.isoformat() == "2026-02-01"
    assert end.isoformat() == "2026-02-28"


def test_redact_sensitive_payload():
    payload = {
        "amount": 100,
        "authorization": {"authorization_code": "AUTH_x", "last4": "1234"},
        "customer": {"email": "a@b.com", "token": "tok"},
    }
    redacted = redact_sensitive(payload)
    assert redacted["amount"] == 100
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["customer"]["email"] == "a@b.com"
    assert redacted["customer"]["token"] == "[REDACTED]"
