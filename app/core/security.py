"""Password hashing, JWT helpers, and logout revocation."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

from jose import JWTError, jwt

from app.core.config import settings

# OWASP-aligned PBKDF2-HMAC-SHA256 work factor (with legacy verify path).
PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 100_000
_HASH_PREFIX = "pbkdf2_sha256"


class _TokenDenylist:
    """In-memory JWT jti denylist (single-process). Expired entries are pruned."""

    def __init__(self) -> None:
        self._entries: dict[str, float] = {}
        self._lock = Lock()

    def revoke(self, jti: str, exp: float) -> None:
        with self._lock:
            self._entries[jti] = exp
            self._prune_locked()

    def is_revoked(self, jti: Optional[str]) -> bool:
        if not jti:
            return False
        with self._lock:
            self._prune_locked()
            return jti in self._entries

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [k for k, exp in self._entries.items() if exp <= now]
        for k in expired:
            del self._entries[k]


token_denylist = _TokenDenylist()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=15)
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "iat": now, "jti": jti})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_password_hash(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a versioned encoding."""
    if len(password.encode("utf-8")) > 256:
        raise ValueError("Password is too long")
    salt = secrets.token_bytes(32)
    pwdhash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"{_HASH_PREFIX}${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(pwdhash).decode('ascii')}"
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against versioned or legacy PBKDF2 hashes."""
    try:
        if hashed_password.startswith(f"{_HASH_PREFIX}$"):
            _, iter_s, salt_b64, hash_b64 = hashed_password.split("$", 3)
            iterations = int(iter_s)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            stored_hash = base64.b64decode(hash_b64.encode("ascii"))
            pwdhash = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt,
                iterations,
            )
            return secrets.compare_digest(stored_hash, pwdhash)

        # Legacy: raw base64(salt + hash) with 100k iterations
        combined = base64.b64decode(hashed_password.encode("ascii"))
        salt = combined[:32]
        stored_hash = combined[32:]
        pwdhash = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt,
            LEGACY_PBKDF2_ITERATIONS,
        )
        return secrets.compare_digest(stored_hash, pwdhash)
    except Exception:
        return False


def verify_token(token: str) -> Optional[str]:
    """Return subject email if token is valid and not revoked."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        jti = payload.get("jti")
        if token_denylist.is_revoked(jti):
            return None
        email = payload.get("sub")
        if email is None:
            return None
        return str(email)
    except JWTError:
        return None


def revoke_token(token: str) -> bool:
    """Revoke a JWT until its natural expiry. Returns False if token is invalid."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not jti or exp is None:
            return False
        token_denylist.revoke(str(jti), float(exp))
        return True
    except JWTError:
        return False
