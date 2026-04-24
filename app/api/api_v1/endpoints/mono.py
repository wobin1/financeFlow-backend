from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uuid

from app.api.api_v1.endpoints.auth import get_current_user
from app.services.mono_service import MonoService
from app.core.utils import ensure_uuid, uuid_to_str

router = APIRouter()

# Pydantic models
class MonoAuthRequest(BaseModel):
    code: str

class MonoSyncRequest(BaseModel):
    account_id: Optional[str] = None

class MonoWebhookPayload(BaseModel):
    event: str
    data: Dict[str, Any]

@router.post("/auth")
async def exchange_mono_token(
    auth_request: MonoAuthRequest,
    current_user: dict = Depends(get_current_user)
):
    """Exchange Mono authorization code for account access"""
    service = MonoService()
    
    try:
        result = await service.exchange_token(
            code=auth_request.code,
            user_id=ensure_uuid(current_user['id'])
        )
        
        account_id = result.get("data", {}).get("id")
        return {
            "message": "Mono account connected successfully",
            "account_id": account_id,
            "account": result
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/account/info")
async def get_account_info(
    current_user: dict = Depends(get_current_user)
):
    """Get connected Mono account information"""
    service = MonoService()
    
    try:
        # Get user's account summary (includes Mono account info)
        summary = await service.get_user_account_summary(
            user_id=ensure_uuid(current_user['id'])
        )
        
        if not summary.get("connected"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Mono account connected"
            )
        
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get account info: {str(e)}"
        )

@router.get("/account/{account_id}/info")
async def get_specific_account_info(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get specific account information by ID"""
    service = MonoService()
    
    try:
        account_info = await service.get_account_info(account_id)
        return account_info
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get account info: {str(e)}"
        )

@router.get("/account/{account_id}/balance")
async def get_account_balance(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get account balance"""
    service = MonoService()
    
    try:
        balance_info = await service.get_account_balance(account_id)
        return balance_info
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get account balance: {str(e)}"
        )

@router.get("/account/{account_id}/transactions")
async def get_account_transactions(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
):
    """Get account transactions from Mono"""
    service = MonoService()
    
    try:
        from datetime import datetime
        
        start_date_obj = None
        end_date_obj = None
        
        if start_date:
            start_date_obj = datetime.fromisoformat(start_date).date()
        if end_date:
            end_date_obj = datetime.fromisoformat(end_date).date()
        
        transactions = await service.get_transactions(
            account_id=account_id,
            start_date=start_date_obj,
            end_date=end_date_obj,
            limit=limit
        )
        
        return {
            "transactions": transactions,
            "count": len(transactions)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get transactions: {str(e)}"
        )

@router.post("/account/sync")
async def sync_transactions(
    current_user: dict = Depends(get_current_user)
):
    """Sync transactions from Mono to our database"""
    service = MonoService()
    
    try:
        result = await service.sync_transactions(
            user_id=ensure_uuid(current_user['id'])
        )
        
        return {
            "message": "Transaction sync completed",
            "summary": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync transactions: {str(e)}"
        )

@router.get("/account/{account_id}/identity")
async def get_account_identity(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get account holder identity information"""
    service = MonoService()
    
    try:
        identity_info = await service.get_account_identity(account_id)
        return identity_info
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get identity info: {str(e)}"
        )

@router.get("/account/{account_id}/income")
async def get_account_income(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get account income analysis"""
    service = MonoService()
    
    try:
        income_info = await service.get_account_income(account_id)
        return income_info
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get income info: {str(e)}"
        )

@router.post("/webhook")
async def handle_mono_webhook(request: Request):
    """Handle Mono webhook events"""
    service = MonoService()
    
    try:
        # Get raw payload and signature
        payload = await request.body()
        signature = request.headers.get("mono-webhook-signature", "")
        
        # Verify webhook signature
        if not await service.verify_webhook(payload, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # Parse JSON payload
        import json
        webhook_data = json.loads(payload.decode())
        
        # Handle the webhook
        result = await service.handle_webhook(webhook_data)
        
        return result
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing failed: {str(e)}"
        )

@router.get("/categories")
async def get_nigerian_categories():
    """Get Nigerian business categories for CAC compliance"""
    from app.services.mono_service_raw import NIGERIAN_BUSINESS_CATEGORIES
    
    return {
        "categories": NIGERIAN_BUSINESS_CATEGORIES,
        "description": "Nigerian business categories compliant with CAC requirements"
    }
