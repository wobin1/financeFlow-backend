from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional

from app.core.config import settings
from app.core.currency import normalize_currency
from app.core.logging_utils import audit_log
from app.core.rate_limit import enforce_rate_limit
from app.core.security import create_access_token, revoke_token, verify_token
from app.services.user_service import UserService

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    business_name: Optional[str] = Field(default=None, max_length=255)
    cac_number: Optional[str] = Field(default=None, max_length=50)
    tin_number: Optional[str] = Field(default=None, max_length=50)
    business_type: Optional[str] = Field(default=None, max_length=100)
    country: str = Field(default="NG", max_length=10)
    currency: str = Field(default="NGN", max_length=10)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    phone_number: Optional[str] = None
    business_name: Optional[str] = None
    cac_number: Optional[str] = None
    tin_number: Optional[str] = None
    business_type: Optional[str] = None
    country: str
    currency: str
    is_active: bool
    role: str = "user"


class Token(BaseModel):
    access_token: str
    token_type: str


def _to_user_response(user: dict) -> UserResponse:
    return UserResponse(
        id=str(user["id"]),
        email=user["email"],
        full_name=user["full_name"],
        phone_number=user.get("phone_number"),
        business_name=user.get("business_name"),
        cac_number=user.get("cac_number"),
        tin_number=user.get("tin_number"),
        business_type=user.get("business_type"),
        country=user.get("country") or "NG",
        currency=user.get("currency") or "NGN",
        is_active=bool(user.get("is_active", True)),
        role=user.get("role") or "user",
    )


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    email = verify_token(token)
    if email is None:
        raise credentials_exception

    user_service = UserService()
    user = await user_service.get_user_by_email(email)
    if user is None:
        raise credentials_exception

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    return user


async def get_current_admin(current_user: dict = Depends(get_current_user)):
    if (current_user.get("role") or "user") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


@router.post("/register", response_model=UserResponse)
async def register(request: Request, user_data: UserCreate):
    enforce_rate_limit(request, bucket="auth-register", limit=5, window_seconds=60)
    user_service = UserService()

    try:
        user = await user_service.create_user(
            email=user_data.email,
            full_name=user_data.full_name,
            password=user_data.password,
            phone_number=user_data.phone_number,
            business_name=user_data.business_name,
            cac_number=user_data.cac_number,
            tin_number=user_data.tin_number,
            business_type=user_data.business_type,
            country=user_data.country,
            currency=user_data.currency,
        )
        audit_log("auth.register", email=user_data.email, user_id=str(user["id"]))
        return _to_user_response(user)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    enforce_rate_limit(request, bucket="auth-login", limit=10, window_seconds=60)
    user_service = UserService()

    user = await user_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        audit_log("auth.login_failed", email=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.get("is_active", True):
        audit_log("auth.login_deactivated", email=user.get("email"), user_id=str(user["id"]))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    audit_log("auth.login_success", email=user["email"], user_id=str(user["id"]))

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    revoked = revoke_token(token)
    audit_log("auth.logout", revoked=revoked)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return _to_user_response(current_user)
