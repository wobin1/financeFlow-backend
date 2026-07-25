"""Admin API — user management, billing overrides, platform stats."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.api_v1.endpoints.auth import get_current_admin
from app.core.logging_utils import audit_log
from app.core.utils import ensure_uuid
from app.services.admin_service import AdminService

router = APIRouter()


class AdminUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[str] = Field(None, pattern="^(user|admin)$")
    plan: Optional[str] = Field(None, pattern="^(free|starter|growth|business)$")
    subscription_status: Optional[str] = Field(
        None, pattern="^(active|cancelled|past_due|trialing)$", max_length=32
    )


class AdminCancelSubscription(BaseModel):
    downgrade_to_free: bool = False


@router.get("/stats")
async def admin_stats(admin: dict = Depends(get_current_admin)):
    return await AdminService().get_stats()


@router.get("/users")
async def admin_list_users(
    search: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    subscription_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    return await AdminService().list_users(
        search=search,
        plan=plan,
        role=role,
        is_active=is_active,
        subscription_status=subscription_status,
        page=page,
        limit=limit,
    )


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: str,
    admin: dict = Depends(get_current_admin),
):
    user = await AdminService().get_user(ensure_uuid(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: AdminUserUpdate,
    admin: dict = Depends(get_current_admin),
):
    if all(
        v is None
        for v in (body.is_active, body.role, body.plan, body.subscription_status)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    try:
        result = await AdminService().update_user(
            user_id=ensure_uuid(user_id),
            admin_id=ensure_uuid(admin["id"]),
            is_active=body.is_active,
            role=body.role,
            plan=body.plan,
            subscription_status=body.subscription_status,
        )
        audit_log(
            "admin.user_update",
            admin_id=str(admin["id"]),
            user_id=user_id,
            role=body.role,
            plan=body.plan,
            is_active=body.is_active,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/users/{user_id}/cancel-subscription")
async def admin_cancel_subscription(
    user_id: str,
    body: AdminCancelSubscription = AdminCancelSubscription(),
    admin: dict = Depends(get_current_admin),
):
    try:
        return await AdminService().cancel_subscription(
            user_id=ensure_uuid(user_id),
            admin_id=ensure_uuid(admin["id"]),
            downgrade_to_free=body.downgrade_to_free,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/billing/events")
async def admin_billing_events(
    search: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    return await AdminService().list_billing_events(
        search=search,
        event_type=event_type,
        page=page,
        limit=limit,
    )


@router.get("/billing/subscriptions")
async def admin_billing_subscriptions(
    search: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    subscription_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    """List user subscriptions for billing management."""
    return await AdminService().list_users(
        search=search,
        plan=plan,
        subscription_status=subscription_status,
        page=page,
        limit=limit,
    )
