"""Unit tests for email auth helpers (no DB required)."""

import asyncio

from app.core.security import generate_url_token, hash_url_token
from app.services.email_service import email_service
from app.services.zoho_mail_service import ZohoMailService


def test_generate_url_token_is_unique_and_urlsafe():
    tokens = {generate_url_token() for _ in range(100)}
    assert len(tokens) == 100
    for token in tokens:
        # token_urlsafe output only uses URL-safe base64 characters
        assert all(c.isalnum() or c in "-_" for c in token)
        assert len(token) >= 32


def test_hash_url_token_is_deterministic_and_sized():
    raw = generate_url_token()
    first = hash_url_token(raw)
    second = hash_url_token(raw)
    assert first == second
    assert first != hash_url_token(generate_url_token())
    # sha256 hex digest fits the VARCHAR(64) column
    assert len(first) == 64


def test_zoho_service_unconfigured_by_default():
    service = ZohoMailService()
    assert service.is_configured is False


def test_email_service_disabled_returns_false_without_raising():
    # EMAILS_ENABLED defaults to False in tests, so sends are logged, not sent.
    sent = asyncio.run(
        email_service.send_verification_email(
            to_address="user@example.com",
            name="Ada",
            verify_url="https://app.example.com/verify-email?token=abc",
        )
    )
    assert sent is False


def test_verification_email_html_contains_link_and_escapes_name():
    from app.services import email_service as email_module

    captured = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return True

    original = email_module.email_service._send
    email_module.email_service._send = fake_send  # type: ignore[assignment]
    try:
        asyncio.run(
            email_module.email_service.send_verification_email(
                to_address="user@example.com",
                name="<script>",
                verify_url="https://app.example.com/verify-email?token=abc123",
            )
        )
    finally:
        email_module.email_service._send = original  # type: ignore[assignment]

    html = captured["html_content"]
    assert "https://app.example.com/verify-email?token=abc123" in html
    assert "<script>" not in html  # name is HTML-escaped
    assert "&lt;script&gt;" in html
