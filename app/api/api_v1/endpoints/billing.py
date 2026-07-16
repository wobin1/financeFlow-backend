"""Billing / subscription API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from typing import Optional

from app.api.api_v1.endpoints.auth import get_current_user
from app.core.plans import list_plans
from app.core.utils import ensure_uuid
from app.services.billing_service import BillingService
from app.services.entitlements import get_usage
from app.services.user_service import UserService

router = APIRouter()


class CheckoutRequest(BaseModel):
    plan: str
    callback_url: Optional[str] = None


@router.get("/plans")
async def get_plans():
    """Public list of billing plans."""
    return {"plans": list_plans()}


@router.get("/subscription")
async def get_subscription(current_user: dict = Depends(get_current_user)):
    """Current plan, status, and usage for the authenticated user."""
    # Refresh user so billing columns are present after migration
    user_service = UserService()
    user = await user_service.get_user_by_id(ensure_uuid(current_user["id"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await get_usage(user)


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    current_user: dict = Depends(get_current_user),
):
    service = BillingService()
    try:
        return await service.initialize_checkout(
            user=current_user,
            plan_id=body.plan,
            callback_url=body.callback_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Paystack error: {str(e)}",
        )


@router.get("/verify")
async def verify_payment(
    reference: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    service = BillingService()
    try:
        result = await service.verify_transaction(reference)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Verification failed: {str(e)}",
        )


@router.post("/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user)):
    user_service = UserService()
    user = await user_service.get_user_by_id(ensure_uuid(current_user["id"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if (user.get("plan") or "free") == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No paid subscription to cancel",
        )

    service = BillingService()
    return await service.cancel_subscription(user)


@router.post("/webhook")
async def paystack_webhook(request: Request):
    """Paystack webhook — no auth; verified via signature header."""
    body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    service = BillingService()

    if not service.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event") or ""
    data = payload.get("data") or {}

    result = await service.handle_webhook(event, data)
    return {"status": "ok", **result}
