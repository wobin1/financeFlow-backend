"""Low-level Zoho Mail REST API transport.

Handles OAuth2 access-token refresh (cached in-process), sending-account
resolution, and the actual message POST. Higher-level templated emails live in
``email_service.py``.

Docs: https://www.zoho.com/mail/help/api/post-send-an-email.html
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Refresh a little before the real expiry to avoid edge-of-expiry failures.
_TOKEN_SKEW_SECONDS = 60


class ZohoMailError(RuntimeError):
    """Raised when the Zoho Mail API cannot fulfil a request."""


class ZohoMailService:
    """Thin async client around the Zoho Mail REST API."""

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._access_token_expiry: float = 0.0
        self._account_id: Optional[str] = settings.ZOHO_ACCOUNT_ID
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(
            settings.ZOHO_CLIENT_ID
            and settings.ZOHO_CLIENT_SECRET
            and settings.ZOHO_REFRESH_TOKEN
            and settings.ZOHO_FROM_ADDRESS
        )

    async def _get_access_token(self) -> str:
        now = time.time()
        with self._lock:
            if self._access_token and now < self._access_token_expiry:
                return self._access_token

        token_url = f"{settings.ZOHO_ACCOUNTS_URL.rstrip('/')}/oauth/v2/token"
        # Use form body (not query params) so httpx access logs never print secrets.
        form = {
            "refresh_token": settings.ZOHO_REFRESH_TOKEN,
            "client_id": settings.ZOHO_CLIENT_ID,
            "client_secret": settings.ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(token_url, data=form)

        try:
            data = resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise ZohoMailError("Zoho token endpoint returned a non-JSON response") from exc

        access_token = data.get("access_token")
        if resp.status_code >= 400 or not access_token:
            # data may contain {"error": "invalid_client"} etc. Never log secrets.
            raise ZohoMailError(f"Zoho token refresh failed: {data.get('error', resp.status_code)}")

        expires_in = int(data.get("expires_in", 3600))
        with self._lock:
            self._access_token = access_token
            self._access_token_expiry = time.time() + max(expires_in - _TOKEN_SKEW_SECONDS, 0)
        return access_token

    async def _get_account_id(self, access_token: str) -> str:
        if self._account_id:
            return self._account_id

        # Prefer pinning ZOHO_ACCOUNT_ID — the listing endpoint needs
        # ZohoMail.accounts.READ, while sending only needs messages.CREATE.
        url = f"{settings.ZOHO_MAIL_API_URL.rstrip('/')}/api/accounts"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            )

        try:
            payload = resp.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise ZohoMailError("Zoho accounts endpoint returned a non-JSON response") from exc

        if resp.status_code >= 400:
            description = self._extract_error(payload) or str(resp.status_code)
            raise ZohoMailError(
                f"Zoho accounts lookup failed ({resp.status_code}: {description}). "
                "Set ZOHO_ACCOUNT_ID in .env to skip this call, or regenerate "
                "the refresh token with scope ZohoMail.accounts.READ,"
                "ZohoMail.messages.CREATE."
            )

        accounts = payload.get("data") or []
        if not accounts:
            raise ZohoMailError(
                "No Zoho Mail accounts available for this token. "
                "Set ZOHO_ACCOUNT_ID in .env."
            )

        account_id = str(accounts[0].get("accountId"))
        self._account_id = account_id
        return account_id

    @staticmethod
    def _extract_error(payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        status_block = payload.get("status")
        if isinstance(status_block, dict):
            desc = status_block.get("description") or ""
        else:
            desc = ""
        data = payload.get("data")
        more = ""
        if isinstance(data, dict):
            more = data.get("moreInfo") or data.get("errorCode") or ""
        elif isinstance(data, str):
            more = data
        parts = [p for p in (desc, more, payload.get("error") if isinstance(payload.get("error"), str) else "") if p]
        return " — ".join(str(p) for p in parts)

    async def send(
        self,
        *,
        to_address: str,
        subject: str,
        html_content: str,
    ) -> None:
        """Send an HTML email. Raises ZohoMailError on failure."""
        if not self.is_configured:
            raise ZohoMailError("Zoho Mail is not configured")

        from_address = (settings.ZOHO_FROM_ADDRESS or "").strip().strip("'\"")
        account_id = (self._account_id or settings.ZOHO_ACCOUNT_ID or "").strip().strip("'\"")
        self._account_id = account_id or self._account_id

        access_token = await self._get_access_token()
        account_id = await self._get_account_id(access_token)

        url = f"{settings.ZOHO_MAIL_API_URL.rstrip('/')}/api/accounts/{account_id}/messages"
        body = {
            "fromAddress": from_address,
            "toAddress": to_address,
            "subject": subject,
            "content": html_content,
            "mailFormat": "html",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Zoho-oauthtoken {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=body,
            )

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        # Zoho returns {"status": {"code": 200, ...}, "data": {...}} on success.
        status_block = payload.get("status") if isinstance(payload, dict) else None
        status_code = status_block.get("code") if isinstance(status_block, dict) else None

        if resp.status_code >= 400 or (status_code is not None and int(status_code) >= 400):
            message = self._extract_error(payload) or str(resp.status_code)
            raise ZohoMailError(
                f"Zoho send failed: {message}. "
                f"Check that ZOHO_FROM_ADDRESS ({from_address}) is a mailbox on "
                f"accountId {account_id}, and that ZOHO_MAIL_API_URL matches your "
                "Zoho data center."
            )


zoho_mail_service = ZohoMailService()
