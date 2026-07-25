from datetime import timedelta
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional

from app.core.config import settings
from app.core.currency import normalize_currency
from app.core.datetime_utils import utc_now
from app.core.logging_utils import audit_log
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.security import create_access_token, revoke_token, verify_token
from app.services.auth_token_service import (
    PURPOSE_EMAIL_VERIFY,
    PURPOSE_PASSWORD_RESET,
    auth_token_service,
)
from app.services.email_service import email_service
from app.services.user_service import UserService

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def _verify_link(raw_token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={raw_token}"


def _reset_link(raw_token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={raw_token}"


async def _issue_and_send_verification(user: dict) -> None:
    raw_token = await auth_token_service.create_token(
        user["id"],
        PURPOSE_EMAIL_VERIFY,
        settings.EMAIL_VERIFICATION_TTL_MINUTES,
    )
    await email_service.send_verification_email(
        to_address=user["email"],
        name=user.get("full_name") or "",
        verify_url=_verify_link(raw_token),
    )


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
    email_verified: bool = False
    role: str = "user"


class Token(BaseModel):
    access_token: str
    token_type: str


class EmailRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class TokenRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=512)


class PasswordResetRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=512)
    new_password: str = Field(..., min_length=8, max_length=128)


class MessageResponse(BaseModel):
    message: str
    email_sent: bool = False


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
        email_verified=bool(user.get("email_verified", False)),
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
async def register(
    request: Request,
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
):
    enforce_rate_limit(request, bucket="auth-register", limit=5, window_seconds=60)
    user_service = UserService()

    # When email is turned off (e.g. local dev) we can't deliver a verification
    # link, so auto-verify to avoid locking users out of the hard login gate.
    require_verification = settings.EMAILS_ENABLED

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
            email_verified=not require_verification,
        )
        audit_log("auth.register", email=user_data.email, user_id=str(user["id"]))

        if require_verification:
            background_tasks.add_task(_issue_and_send_verification, user)

        return _to_user_response(user)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    background_tasks: BackgroundTasks,
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

    # Hard verification gate: block sign-in until the email is confirmed.
    if settings.EMAILS_ENABLED and not user.get("email_verified", False):
        audit_log("auth.login_unverified", email=user.get("email"), user_id=str(user["id"]))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address before signing in. Check your inbox for the verification link.",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    audit_log("auth.login_success", email=user["email"], user_id=str(user["id"]))

    background_tasks.add_task(
        email_service.send_new_login_email,
        to_address=user["email"],
        name=user.get("full_name") or "",
        when=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        ip_address=client_ip(request),
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    request: Request,
    payload: TokenRequest,
    background_tasks: BackgroundTasks,
):
    enforce_rate_limit(request, bucket="auth-verify", limit=10, window_seconds=60)
    user_id = await auth_token_service.consume_token(payload.token, PURPOSE_EMAIL_VERIFY)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link is invalid or has expired. Request a new one.",
        )

    user_service = UserService()
    await user_service.mark_email_verified(user_id)
    user = await user_service.get_user_by_id(user_id)
    audit_log("auth.email_verified", user_id=str(user_id))

    if user:
        background_tasks.add_task(
            email_service.send_welcome_email,
            to_address=user["email"],
            name=user.get("full_name") or "",
        )

    return MessageResponse(message="Your email has been verified. You can now sign in.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    request: Request,
    payload: EmailRequest,
    background_tasks: BackgroundTasks,
):
    enforce_rate_limit(request, bucket="auth-resend", limit=3, window_seconds=60)
    generic = MessageResponse(
        message="If an unverified account exists for that email, a verification link is on its way.",
        email_sent=settings.EMAILS_ENABLED,
    )

    user_service = UserService()
    user = await user_service.get_user_by_email(payload.email)
    if user and not user.get("email_verified", False) and settings.EMAILS_ENABLED:
        background_tasks.add_task(_issue_and_send_verification, user)

    return generic


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: Request,
    payload: EmailRequest,
    background_tasks: BackgroundTasks,
):
    enforce_rate_limit(request, bucket="auth-forgot", limit=3, window_seconds=60)
    generic = MessageResponse(
        message="If an account exists for that email, a password reset link is on its way.",
        email_sent=settings.EMAILS_ENABLED,
    )

    user_service = UserService()
    user = await user_service.get_user_by_email(payload.email)
    if user and user.get("is_active", True):
        async def _send_reset(u: dict) -> None:
            raw_token = await auth_token_service.create_token(
                u["id"], PURPOSE_PASSWORD_RESET, settings.PASSWORD_RESET_TTL_MINUTES
            )
            await email_service.send_password_reset_email(
                to_address=u["email"],
                name=u.get("full_name") or "",
                reset_url=_reset_link(raw_token),
            )

        audit_log("auth.forgot_password", user_id=str(user["id"]))
        background_tasks.add_task(_send_reset, user)

    return generic


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: Request,
    payload: PasswordResetRequest,
    background_tasks: BackgroundTasks,
):
    enforce_rate_limit(request, bucket="auth-reset", limit=5, window_seconds=60)
    user_id = await auth_token_service.consume_token(payload.token, PURPOSE_PASSWORD_RESET)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    user_service = UserService()
    await user_service.set_password(user_id, payload.new_password)
    user = await user_service.get_user_by_id(user_id)
    audit_log("auth.password_reset", user_id=str(user_id))

    if user:
        background_tasks.add_task(
            email_service.send_password_changed_email,
            to_address=user["email"],
            name=user.get("full_name") or "",
        )

    return MessageResponse(message="Your password has been reset. You can now sign in.")


@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    revoked = revoke_token(token)
    audit_log("auth.logout", revoked=revoked)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return _to_user_response(current_user)
