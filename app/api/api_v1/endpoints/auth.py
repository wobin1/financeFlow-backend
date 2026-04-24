from datetime import timedelta
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional
import uuid

from app.core.config import settings
from app.core.security import create_access_token, verify_token
from app.services.user_service import UserService

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

# Pydantic models
class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str
    phone_number: Optional[str] = None
    business_name: Optional[str] = None
    cac_number: Optional[str] = None
    tin_number: Optional[str] = None
    business_type: Optional[str] = None
    country: str = "NG"
    currency: str = "NGN"

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

class Token(BaseModel):
    access_token: str
    token_type: str

# Dependency to get current user
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
    
    return user

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserCreate):
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
            currency=user_data.currency
        )
        
        return UserResponse(
            id=str(user['id']),
            email=user['email'],
            full_name=user['full_name'],
            phone_number=user['phone_number'],
            business_name=user['business_name'],
            cac_number=user['cac_number'],
            tin_number=user['tin_number'],
            business_type=user['business_type'],
            country=user['country'],
            currency=user['currency'],
            is_active=user['is_active']
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_service = UserService()
    
    user = await user_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['email']}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user['id']),
        email=current_user['email'],
        full_name=current_user['full_name'],
        phone_number=current_user['phone_number'],
        business_name=current_user['business_name'],
        cac_number=current_user['cac_number'],
        tin_number=current_user['tin_number'],
        business_type=current_user['business_type'],
        country=current_user['country'],
        currency=current_user['currency'],
        is_active=current_user['is_active']
    )
