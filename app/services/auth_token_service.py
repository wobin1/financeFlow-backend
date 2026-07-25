"""Single-use, expiring, hashed tokens for email verification and password reset."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from app.core.database import db_service
from app.core.datetime_utils import utc_now
from app.core.security import generate_url_token, hash_url_token

PURPOSE_EMAIL_VERIFY = "email_verify"
PURPOSE_PASSWORD_RESET = "password_reset"


class AuthTokenService:
    """Create and consume opaque auth tokens backed by the ``auth_tokens`` table."""

    async def create_token(
        self,
        user_id: uuid.UUID,
        purpose: str,
        ttl_minutes: int,
    ) -> str:
        """Issue a new token, invalidating any prior unused tokens of the same purpose.

        Returns the raw token (only stored hashed).
        """
        raw_token = generate_url_token()
        token_hash = hash_url_token(raw_token)
        now = utc_now()
        expires_at = now + timedelta(minutes=ttl_minutes)

        queries = [
            (
                # Invalidate outstanding tokens so only the newest link works.
                """
                UPDATE auth_tokens
                SET used_at = $1
                WHERE user_id = $2 AND purpose = $3 AND used_at IS NULL
                """,
                (now, user_id, purpose),
            ),
            (
                """
                INSERT INTO auth_tokens (id, user_id, purpose, token_hash, expires_at, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                (uuid.uuid4(), user_id, purpose, token_hash, expires_at, now),
            ),
        ]
        await db_service.execute_transaction(queries)
        return raw_token

    async def consume_token(self, raw_token: str, purpose: str) -> Optional[uuid.UUID]:
        """Validate and atomically consume a token. Returns the user_id or None."""
        if not raw_token:
            return None

        token_hash = hash_url_token(raw_token)
        now = utc_now()
        query = """
            UPDATE auth_tokens
            SET used_at = $1
            WHERE token_hash = $2
              AND purpose = $3
              AND used_at IS NULL
              AND expires_at > $1
            RETURNING user_id
        """
        row = await db_service.execute_one(query, now, token_hash, purpose)
        if not row:
            return None
        return row["user_id"]


auth_token_service = AuthTokenService()
