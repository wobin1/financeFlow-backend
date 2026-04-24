from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import hashlib
import secrets
import base64
from app.core.config import settings

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def get_password_hash(password: str) -> str:
    """Hash password using PBKDF2 with SHA-256"""
    # Generate a random salt
    salt = secrets.token_bytes(32)
    
    # Hash the password with PBKDF2
    pwdhash = hashlib.pbkdf2_hmac('sha256', 
                                  password.encode('utf-8'), 
                                  salt, 
                                  100000)  # 100,000 iterations
    
    # Combine salt and hash, then base64 encode
    combined = salt + pwdhash
    return base64.b64encode(combined).decode('ascii')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against PBKDF2 hash"""
    try:
        # Decode the stored hash
        combined = base64.b64decode(hashed_password.encode('ascii'))
        
        # Extract salt (first 32 bytes) and hash (rest)
        salt = combined[:32]
        stored_hash = combined[32:]
        
        # Hash the provided password with the same salt
        pwdhash = hashlib.pbkdf2_hmac('sha256',
                                      plain_password.encode('utf-8'),
                                      salt,
                                      100000)  # Same number of iterations
        
        # Compare hashes using constant-time comparison
        return secrets.compare_digest(stored_hash, pwdhash)
    except Exception:
        return False

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
        return email
    except JWTError:
        return None
