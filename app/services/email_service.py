"""Templated transactional emails for auth flows.

Wraps :class:`ZohoMailService` and renders the FinanceFlow-branded HTML. When
email is disabled or unconfigured (e.g. local dev), sends are logged instead of
raising so auth flows keep working; links are logged so developers can copy
them.
"""

from __future__ import annotations

import logging
from html import escape

from app.core.config import settings
from app.services.zoho_mail_service import ZohoMailError, zoho_mail_service

logger = logging.getLogger(__name__)

_BRAND_GREEN = "#1B3A2D"
_BRAND_LIME = "#a3e635"


def _layout(title: str, body_html: str) -> str:
    year = 2026
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;background:#f7f8f5;font-family:Arial,Helvetica,sans-serif;color:#1f2937;">
  <div style="max-width:520px;margin:0 auto;padding:32px 16px;">
    <div style="background:{_BRAND_GREEN};border-radius:16px 16px 0 0;padding:24px 32px;">
      <span style="color:#ffffff;font-size:20px;font-weight:bold;">FinanceFlow</span>
    </div>
    <div style="background:#ffffff;padding:32px;border-radius:0 0 16px 16px;">
      <h1 style="font-size:20px;margin:0 0 16px;color:{_BRAND_GREEN};">{escape(title)}</h1>
      {body_html}
    </div>
    <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:24px;">
      &copy; {year} FinanceFlow. All rights reserved.
    </p>
  </div>
</body>
</html>"""


def _button(url: str, label: str) -> str:
    return (
        f'<a href="{escape(url, quote=True)}" '
        f'style="display:inline-block;background:{_BRAND_GREEN};color:#ffffff;'
        f'text-decoration:none;padding:12px 24px;border-radius:10px;font-weight:bold;'
        f'font-size:14px;">{escape(label)}</a>'
    )


def _paragraph(text: str) -> str:
    return f'<p style="font-size:14px;line-height:1.6;color:#374151;margin:0 0 16px;">{text}</p>'


class EmailService:
    """High-level templated email sender."""

    async def _send(self, *, to_address: str, subject: str, html_content: str, context: str) -> bool:
        if not settings.EMAILS_ENABLED or not zoho_mail_service.is_configured:
            logger.info(
                "Email disabled/unconfigured; skipping %s to %s. Content logged for dev only.",
                context,
                to_address,
            )
            logger.info("[DEV EMAIL] %s -> %s\n%s", context, to_address, html_content)
            return False

        try:
            await zoho_mail_service.send(
                to_address=to_address,
                subject=subject,
                html_content=html_content,
            )
            logger.info("Sent %s email to %s", context, to_address)
            return True
        except ZohoMailError:
            logger.exception("Failed to send %s email to %s", context, to_address)
            return False

    async def send_verification_email(self, *, to_address: str, name: str, verify_url: str) -> bool:
        body = (
            _paragraph(f"Hi {escape(name or 'there')},")
            + _paragraph(
                "Welcome to FinanceFlow. Please confirm your email address to activate "
                "your account and sign in."
            )
            + f'<p style="margin:24px 0;">{_button(verify_url, "Verify my email")}</p>'
            + _paragraph(
                "This link expires in "
                f"{settings.EMAIL_VERIFICATION_TTL_MINUTES // 60} hours. "
                "If you didn't create this account, you can ignore this email."
            )
        )
        return await self._send(
            to_address=to_address,
            subject="Verify your FinanceFlow email",
            html_content=_layout("Confirm your email", body),
            context="verification",
        )

    async def send_welcome_email(self, *, to_address: str, name: str) -> bool:
        body = (
            _paragraph(f"Hi {escape(name or 'there')},")
            + _paragraph(
                "Your email is verified and your FinanceFlow account is ready. You can now "
                "connect your bank, track transactions, and prepare FIRS filings."
            )
            + f'<p style="margin:24px 0;">{_button(settings.FRONTEND_URL + "/dashboard", "Go to dashboard")}</p>'
        )
        return await self._send(
            to_address=to_address,
            subject="Welcome to FinanceFlow",
            html_content=_layout("You're all set", body),
            context="welcome",
        )

    async def send_password_reset_email(self, *, to_address: str, name: str, reset_url: str) -> bool:
        body = (
            _paragraph(f"Hi {escape(name or 'there')},")
            + _paragraph(
                "We received a request to reset your FinanceFlow password. Click below to "
                "choose a new one."
            )
            + f'<p style="margin:24px 0;">{_button(reset_url, "Reset password")}</p>'
            + _paragraph(
                f"This link expires in {settings.PASSWORD_RESET_TTL_MINUTES} minutes. "
                "If you didn't request this, you can safely ignore this email — your "
                "password won't change."
            )
        )
        return await self._send(
            to_address=to_address,
            subject="Reset your FinanceFlow password",
            html_content=_layout("Reset your password", body),
            context="password_reset",
        )

    async def send_password_changed_email(self, *, to_address: str, name: str) -> bool:
        body = (
            _paragraph(f"Hi {escape(name or 'there')},")
            + _paragraph(
                "Your FinanceFlow password was just changed. If this was you, no action is "
                "needed."
            )
            + _paragraph(
                "If you didn't do this, reset your password immediately and contact support."
            )
        )
        return await self._send(
            to_address=to_address,
            subject="Your FinanceFlow password was changed",
            html_content=_layout("Password changed", body),
            context="password_changed",
        )

    async def send_new_login_email(
        self, *, to_address: str, name: str, when: str, ip_address: str
    ) -> bool:
        body = (
            _paragraph(f"Hi {escape(name or 'there')},")
            + _paragraph("We noticed a new sign-in to your FinanceFlow account:")
            + _paragraph(f"<strong>Time:</strong> {escape(when)}<br><strong>IP:</strong> {escape(ip_address)}")
            + _paragraph(
                "If this was you, you can ignore this email. If not, reset your password "
                "right away."
            )
        )
        return await self._send(
            to_address=to_address,
            subject="New sign-in to your FinanceFlow account",
            html_content=_layout("New sign-in detected", body),
            context="new_login",
        )


email_service = EmailService()
