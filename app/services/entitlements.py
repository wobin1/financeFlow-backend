"""Subscription entitlement checks and usage counters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from fastapi import HTTPException, status

from app.core.database import db_service
from app.core.plans import Plan, get_plan


class PlanLimitError(Exception):
    """Raised when a plan quota or feature is exceeded."""

    def __init__(self, detail: str, *, upgrade_hint: bool = True):
        self.detail = detail
        self.upgrade_hint = upgrade_hint
        super().__init__(detail)


def _as_naive_utc(value: datetime) -> datetime:
    if getattr(value, "tzinfo", None) is not None:
        return value.replace(tzinfo=None)
    return value


def effective_plan(user: Dict[str, Any]) -> Plan:
    """Resolve the user's active plan, downgrading expired paid access to free."""
    plan_id = user.get("plan") or "free"
    if plan_id == "free":
        return get_plan("free")

    status_value = (user.get("subscription_status") or "active").lower()
    period_end = user.get("plan_period_end")
    now = datetime.utcnow()

    if status_value == "active":
        return get_plan(plan_id)

    # Cancelled / past_due keep access until period end
    if period_end and _as_naive_utc(period_end) > now:
        return get_plan(plan_id)

    return get_plan("free")


async def count_monthly_transactions(user_id: uuid.UUID) -> int:
    query = """
        SELECT COUNT(*)::int AS count
        FROM transactions
        WHERE user_id = $1
          AND created_at >= date_trunc('month', NOW() AT TIME ZONE 'UTC')
    """
    row = await db_service.execute_one(query, user_id)
    return int(row["count"]) if row else 0


async def count_connected_banks(user_id: uuid.UUID) -> int:
    """Count linked banks: legacy Mono token on users + bank_accounts rows."""
    user_row = await db_service.execute_one(
        "SELECT plaid_access_token FROM users WHERE id = $1",
        user_id,
    )
    token_count = 1 if user_row and user_row.get("plaid_access_token") else 0

    bank_row = await db_service.execute_one(
        """
        SELECT COUNT(*)::int AS count
        FROM bank_accounts
        WHERE user_id = $1 AND is_active = true
        """,
        user_id,
    )
    table_count = int(bank_row["count"]) if bank_row else 0

    # Avoid double-counting when only the legacy token is used
    if token_count and table_count == 0:
        return token_count
    if table_count:
        return table_count
    return token_count


async def get_usage(user: Dict[str, Any]) -> Dict[str, Any]:
    user_id = user["id"] if isinstance(user["id"], uuid.UUID) else uuid.UUID(str(user["id"]))
    plan = effective_plan(user)
    tx_used = await count_monthly_transactions(user_id)
    banks_used = await count_connected_banks(user_id)

    return {
        "plan": plan.to_dict(),
        "subscription_status": user.get("subscription_status") or "active",
        "plan_period_end": user.get("plan_period_end").isoformat()
        if user.get("plan_period_end")
        else None,
        "usage": {
            "transactions_this_month": tx_used,
            "transactions_limit": plan.max_transactions_per_month,
            "banks_connected": banks_used,
            "banks_limit": plan.max_banks,
        },
    }


async def assert_can_create_transaction(user: Dict[str, Any]) -> None:
    plan = effective_plan(user)
    if plan.max_transactions_per_month is None:
        return
    user_id = user["id"] if isinstance(user["id"], uuid.UUID) else uuid.UUID(str(user["id"]))
    used = await count_monthly_transactions(user_id)
    if used >= plan.max_transactions_per_month:
        raise PlanLimitError(
            f"Monthly transaction limit reached ({plan.max_transactions_per_month}). "
            "Upgrade your plan to add more."
        )


async def assert_can_link_bank(user: Dict[str, Any], *, replacing: bool = False) -> None:
    plan = effective_plan(user)
    if plan.max_banks is None:
        return
    if plan.max_banks == 0:
        raise PlanLimitError(
            "Bank linking is not included in your plan. Upgrade to Growth or Business to connect a bank."
        )
    if replacing:
        return
    user_id = user["id"] if isinstance(user["id"], uuid.UUID) else uuid.UUID(str(user["id"]))
    used = await count_connected_banks(user_id)
    if used >= plan.max_banks:
        raise PlanLimitError(
            f"Bank account limit reached ({plan.max_banks}). Upgrade to link more accounts."
        )


def assert_feature(user: Dict[str, Any], feature: str) -> None:
    plan = effective_plan(user)
    allowed = {
        "ai_categorization": plan.ai_categorization,
        "firs_access": plan.firs_access,
        "firs_export": plan.firs_export,
        "advanced_analytics": plan.advanced_analytics,
    }.get(feature, False)

    if not allowed:
        labels = {
            "ai_categorization": "AI categorization",
            "firs_access": "FIRS filing",
            "firs_export": "FIRS export",
            "advanced_analytics": "Advanced analytics",
        }
        raise PlanLimitError(
            f"{labels.get(feature, feature)} is not included in the {plan.name} plan. "
            "Upgrade to unlock it."
        )


def plan_limit_http(exc: PlanLimitError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={"message": exc.detail, "upgrade_required": exc.upgrade_hint},
    )
