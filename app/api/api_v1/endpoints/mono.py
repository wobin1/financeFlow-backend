from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import secrets
import uuid

from app.api.api_v1.endpoints.auth import get_current_user
from app.services.mono_service import MonoService
from app.core.utils import ensure_uuid, uuid_to_str
from app.services.entitlements import (
    PlanLimitError,
    assert_can_link_bank,
    plan_limit_http,
)

router = APIRouter()


def _assert_owns_mono_account(current_user: dict, account_id: str) -> None:
    """Reject access unless account_id is the caller's linked Mono account.

    Uses 404 for both "not linked" and "not yours" so we do not confirm
    whether an account ID exists for another user (BOLA / IDOR).
    """
    linked = current_user.get("plaid_access_token")
    if not linked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Mono account connected",
        )
    if not secrets.compare_digest(str(linked), str(account_id)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mono account not found",
        )


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
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Exchange Mono authorization code for account access"""
    from app.core.rate_limit import enforce_rate_limit

    enforce_rate_limit(request, bucket="mono-auth", limit=10, window_seconds=60)
    service = MonoService()
    already_linked = bool(current_user.get("plaid_access_token"))

    try:
        await assert_can_link_bank(current_user, replacing=already_linked)
    except PlanLimitError as e:
        raise plan_limit_http(e)
    
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
        from app.core.errors import http_error
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "Failed to connect Mono account",
            log_exc=e,
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
            detail="Failed to get account info"
        )

@router.get("/account/{account_id}/info")
async def get_specific_account_info(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get specific account information by ID"""
    _assert_owns_mono_account(current_user, account_id)
    service = MonoService()
    
    try:
        account_info = await service.get_account_info(account_id)
        return account_info

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get account info"
        )

@router.get("/account/{account_id}/balance")
async def get_account_balance(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get account balance"""
    _assert_owns_mono_account(current_user, account_id)
    service = MonoService()
    
    try:
        balance_info = await service.get_account_balance(account_id)
        return balance_info

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get account balance"
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
    _assert_owns_mono_account(current_user, account_id)
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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get transactions"
        )

@router.post("/account/sync")
async def sync_transactions(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Sync transactions from Mono to our database"""
    from app.core.rate_limit import enforce_rate_limit

    enforce_rate_limit(request, bucket="mono-sync", limit=5, window_seconds=60)
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
            detail="Failed to sync transactions"
        )

@router.get("/account/{account_id}/identity")
async def get_account_identity(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get account holder identity information"""
    _assert_owns_mono_account(current_user, account_id)
    service = MonoService()
    
    try:
        identity_info = await service.get_account_identity(account_id)
        return identity_info

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get identity info"
        )

@router.get("/account/{account_id}/income")
async def get_account_income(
    account_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get account income analysis"""
    _assert_owns_mono_account(current_user, account_id)
    service = MonoService()
    
    try:
        income_info = await service.get_account_income(account_id)
        return income_info

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get income info"
        )

@router.post("/webhook")
async def handle_mono_webhook(request: Request):
    """Handle Mono webhook events"""
    import json

    service = MonoService()
    payload = await request.body()
    signature = request.headers.get("mono-webhook-signature", "")
    header_secret = request.headers.get("mono-webhook-secret", "")

    if not await service.verify_webhook(
        payload,
        signature=signature,
        header_secret=header_secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        webhook_data = json.loads(payload.decode())
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    try:
        return await service.handle_webhook(webhook_data)
    except HTTPException:
        raise
    except Exception as e:
        from app.core.errors import http_error

        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Webhook processing failed",
            log_exc=e,
        )


@router.get("/categories")
async def get_nigerian_categories():
    """Get Nigerian business categories for CAC compliance"""
    from app.services.mono_service import NIGERIAN_BUSINESS_CATEGORIES

    return {
        "categories": NIGERIAN_BUSINESS_CATEGORIES,
        "description": "Nigerian business categories compliant with CAC requirements",
    }
