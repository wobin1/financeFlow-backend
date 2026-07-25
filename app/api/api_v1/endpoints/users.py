from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional
import uuid

from app.api.api_v1.endpoints.auth import get_current_user
from app.services.user_service import UserService
from app.core.utils import ensure_uuid, uuid_to_str

router = APIRouter()

# Pydantic models
class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    business_name: Optional[str] = Field(default=None, max_length=255)
    cac_number: Optional[str] = Field(default=None, max_length=50)
    tin_number: Optional[str] = Field(default=None, max_length=50)
    business_type: Optional[str] = Field(default=None, max_length=100)

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

class PlaidTokenUpdate(BaseModel):
    access_token: str

@router.get("/profile", response_model=UserResponse)
async def get_user_profile(
    current_user: dict = Depends(get_current_user)
):
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
        is_active=current_user['is_active'],
        role=current_user.get('role') or 'user',
    )

@router.put("/profile", response_model=UserResponse)
async def update_user_profile(
    update_data: UserUpdate,
    current_user: dict = Depends(get_current_user)
):
    service = UserService()
    
    try:
        updated_user = await service.update_user(
            user_id=ensure_uuid(current_user['id']),
            full_name=update_data.full_name,
            phone_number=update_data.phone_number,
            business_name=update_data.business_name,
            cac_number=update_data.cac_number,
            tin_number=update_data.tin_number,
            business_type=update_data.business_type
        )
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserResponse(
            id=str(updated_user['id']),
            email=updated_user['email'],
            full_name=updated_user['full_name'],
            phone_number=updated_user['phone_number'],
            business_name=updated_user['business_name'],
            cac_number=updated_user['cac_number'],
            tin_number=updated_user['tin_number'],
            business_type=updated_user['business_type'],
            country=updated_user['country'],
            currency=updated_user['currency'],
            is_active=updated_user['is_active'],
            role=updated_user.get('role') or current_user.get('role') or 'user',
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )

@router.post("/plaid-token")
async def update_plaid_token(
    token_data: PlaidTokenUpdate,
    current_user: dict = Depends(get_current_user)
):
    service = UserService()
    
    try:
        success = await service.update_plaid_token(
            user_id=ensure_uuid(current_user['id']),
            access_token=token_data.access_token
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {"message": "Plaid token updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update bank token"
        )

@router.post("/deactivate")
async def deactivate_account(
    current_user: dict = Depends(get_current_user)
):
    service = UserService()
    
    try:
        success = await service.deactivate_user(
            user_id=ensure_uuid(current_user['id'])
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {"message": "Account deactivated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate account"
        )
