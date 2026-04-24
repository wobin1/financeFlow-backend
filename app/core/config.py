from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Database
    DATABASE_URL: str
    
    # AI Services
    GEMINI_API_KEY: str
    
    # Banking - Plaid (Global)
    PLAID_CLIENT_ID: Optional[str] = None
    PLAID_SECRET: Optional[str] = None
    PLAID_ENV: str = "sandbox"
    
    # Banking - Mono (Nigeria)
    MONO_SECRET_KEY: Optional[str] = None
    MONO_PUBLIC_KEY: Optional[str] = None
    MONO_ENV: str = "test"  # test or live
    MONO_WEBHOOK_SECRET: Optional[str] = None
    
    # Messaging
    TWILIO_SID: Optional[str] = None
    TWILIO_TOKEN: Optional[str] = None
    TWILIO_PHONE_NUMBER: Optional[str] = None
    
    # Termii (Alternative messaging for Nigeria)
    TERMII_API_KEY: Optional[str] = None
    TERMII_SENDER_ID: Optional[str] = None
    TERMII_CHANNEL: Optional[str] = None
    
    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    
    class Config:
        env_file = ".env"

settings = Settings()
