"""Admin operations: users, billing overrides, platform stats."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.core.database import db_service
from app.core.plans import PLANS
from app.services.billing_service import BillingService
from app.services.user_service import UserService


def _serialize_user(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return row
    out = dict(row)
    for key in ("id",):
        if key in out and out[key] is not None:
            out[key] = str(out[key])
    for key in ("created_at", "updated_at", "plan_period_end", "plan_updated_at"):
        if key in out and out[key] is not None and hasattr(out[key], "isoformat"):
            out[key] = out[key].isoformat()
    out.pop("hashed_password", None)
    out.pop("plaid_access_token", None)
    return out


class AdminService:
    def __init__(self) -> None:
        self.users = UserService()
        self.billing = BillingService()

    async def list_users(
        self,
        *,
        search: Optional[str] = None,
        plan: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        subscription_status: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
    ) -> Dict[str, Any]:
        page = max(1, page)
        limit = min(max(1, limit), 100)
        offset = (page - 1) * limit

        conditions: List[str] = []
        params: List[Any] = []
        idx = 1

        if search:
            conditions.append(
                f"(email ILIKE ${idx} OR full_name ILIKE ${idx} OR "
                f"COALESCE(business_name, '') ILIKE ${idx})"
            )
            params.append(f"%{search.strip()}%")
            idx += 1

        if plan:
            conditions.append(f"plan = ${idx}")
            params.append(plan)
            idx += 1

        if role:
            conditions.append(f"role = ${idx}")
            params.append(role)
            idx += 1

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1

        if subscription_status:
            conditions.append(f"subscription_status = ${idx}")
            params.append(subscription_status)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_row = await db_service.execute_one(
            f"SELECT COUNT(*)::int AS total FROM users {where}",
            *params,
        )
        total = (count_row or {}).get("total", 0)

        params.extend([limit, offset])
        rows = await db_service.execute_query(
            f"""
            SELECT id, email, full_name, phone_number, business_name,
                   business_type, country, currency, is_active, role,
                   plan, subscription_status, plan_period_end, plan_updated_at,
                   paystack_customer_code, paystack_subscription_code,
                   created_at, updated_at
            FROM users
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        return {
            "items": [_serialize_user(r) for r in (rows or [])],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit) if total else 1,
        }

    async def get_user(self, user_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        user = await self.users.get_user_by_id(user_id)
        if not user:
            return None

        tx_count = await db_service.execute_one(
            "SELECT COUNT(*)::int AS c FROM transactions WHERE user_id = $1",
            user_id,
        )
        bank_count = await db_service.execute_one(
            "SELECT COUNT(*)::int AS c FROM bank_accounts WHERE user_id = $1",
            user_id,
        )
        recent_events = await db_service.execute_query(
            """
            SELECT id, event_type, paystack_reference, plan, amount_kobo, created_at
            FROM billing_events
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 20
            """,
            user_id,
        )

        serialized = _serialize_user(user)
        serialized["transaction_count"] = (tx_count or {}).get("c", 0)
        serialized["bank_account_count"] = (bank_count or {}).get("c", 0)
        serialized["recent_billing_events"] = [
            {
                **e,
                "id": str(e["id"]),
                "created_at": e["created_at"].isoformat()
                if e.get("created_at") and hasattr(e["created_at"], "isoformat")
                else e.get("created_at"),
            }
            for e in (recent_events or [])
        ]
        return serialized

    async def update_user(
        self,
        *,
        user_id: uuid.UUID,
        admin_id: uuid.UUID,
        is_active: Optional[bool] = None,
        role: Optional[str] = None,
        plan: Optional[str] = None,
        subscription_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = await self.users.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if user_id == admin_id:
            if is_active is False:
                raise ValueError("You cannot deactivate your own account")
            if role == "user":
                raise ValueError("You cannot demote your own admin role")

        if role is not None:
            if role not in ("user", "admin"):
                raise ValueError("Invalid role")
            await self.users.set_user_role(user_id, role)

        if is_active is not None:
            await self.users.set_user_active(user_id, is_active)

        if plan is not None or subscription_status is not None:
            if plan is not None and plan not in PLANS:
                raise ValueError(f"Invalid plan: {plan}")
            new_plan = plan if plan is not None else user.get("plan") or "free"
            new_status = (
                subscription_status
                if subscription_status is not None
                else user.get("subscription_status") or "active"
            )
            await self.billing._update_subscription(
                user_id=user_id,
                plan=new_plan,
                subscription_status=new_status,
                period_end=user.get("plan_period_end"),
                customer_code=None,
                subscription_code=None,
                authorization_code=None,
            )
            await self.billing._log_event(
                user_id=user_id,
                event_type="admin_plan_override",
                reference=None,
                plan=new_plan,
                amount_kobo=None,
                payload={
                    "admin_id": str(admin_id),
                    "previous_plan": user.get("plan"),
                    "previous_status": user.get("subscription_status"),
                    "new_plan": new_plan,
                    "new_status": new_status,
                },
            )

        updated = await self.get_user(user_id)
        if not updated:
            raise ValueError("User not found after update")
        return updated

    async def cancel_subscription(
        self,
        *,
        user_id: uuid.UUID,
        admin_id: uuid.UUID,
        downgrade_to_free: bool = False,
    ) -> Dict[str, Any]:
        user = await self.users.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        result = await self.billing.cancel_subscription(user)

        if downgrade_to_free:
            await self.billing.downgrade_to_free(user_id)
            await self.billing._log_event(
                user_id=user_id,
                event_type="admin_plan_override",
                reference=None,
                plan="free",
                amount_kobo=None,
                payload={
                    "admin_id": str(admin_id),
                    "action": "cancel_and_downgrade",
                    "previous_plan": user.get("plan"),
                },
            )
        else:
            await self.billing._log_event(
                user_id=user_id,
                event_type="admin_subscription_cancel",
                reference=user.get("paystack_subscription_code"),
                plan=user.get("plan"),
                amount_kobo=None,
                payload={"admin_id": str(admin_id), "result": result},
            )

        updated = await self.get_user(user_id)
        if not updated:
            raise ValueError("User not found after cancel")
        return {"user": updated, "cancel": result}

    async def list_billing_events(
        self,
        *,
        search: Optional[str] = None,
        event_type: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
    ) -> Dict[str, Any]:
        page = max(1, page)
        limit = min(max(1, limit), 100)
        offset = (page - 1) * limit

        conditions: List[str] = []
        params: List[Any] = []
        idx = 1

        if event_type:
            conditions.append(f"be.event_type = ${idx}")
            params.append(event_type)
            idx += 1

        if search:
            conditions.append(
                f"(u.email ILIKE ${idx} OR u.full_name ILIKE ${idx} OR "
                f"COALESCE(be.paystack_reference, '') ILIKE ${idx})"
            )
            params.append(f"%{search.strip()}%")
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_row = await db_service.execute_one(
            f"""
            SELECT COUNT(*)::int AS total
            FROM billing_events be
            LEFT JOIN users u ON u.id = be.user_id
            {where}
            """,
            *params,
        )
        total = (count_row or {}).get("total", 0)

        params.extend([limit, offset])
        rows = await db_service.execute_query(
            f"""
            SELECT be.id, be.user_id, be.event_type, be.paystack_reference,
                   be.plan, be.amount_kobo, be.created_at,
                   u.email AS user_email, u.full_name AS user_full_name
            FROM billing_events be
            LEFT JOIN users u ON u.id = be.user_id
            {where}
            ORDER BY be.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        items = []
        for r in rows or []:
            items.append(
                {
                    "id": str(r["id"]),
                    "user_id": str(r["user_id"]) if r.get("user_id") else None,
                    "event_type": r["event_type"],
                    "paystack_reference": r.get("paystack_reference"),
                    "plan": r.get("plan"),
                    "amount_kobo": r.get("amount_kobo"),
                    "created_at": r["created_at"].isoformat()
                    if r.get("created_at") and hasattr(r["created_at"], "isoformat")
                    else r.get("created_at"),
                    "user_email": r.get("user_email"),
                    "user_full_name": r.get("user_full_name"),
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit) if total else 1,
        }

    async def get_stats(self) -> Dict[str, Any]:
        totals = await db_service.execute_one(
            """
            SELECT
                COUNT(*)::int AS total_users,
                COUNT(*) FILTER (WHERE is_active)::int AS active_users,
                COUNT(*) FILTER (WHERE role = 'admin')::int AS admin_users,
                COUNT(*) FILTER (WHERE plan != 'free')::int AS paid_users
            FROM users
            """
        )
        by_plan = await db_service.execute_query(
            """
            SELECT plan, COUNT(*)::int AS count
            FROM users
            GROUP BY plan
            ORDER BY count DESC
            """
        )
        by_status = await db_service.execute_query(
            """
            SELECT subscription_status, COUNT(*)::int AS count
            FROM users
            GROUP BY subscription_status
            ORDER BY count DESC
            """
        )
        tx_totals = await db_service.execute_one(
            "SELECT COUNT(*)::int AS total_transactions FROM transactions"
        )
        revenue = await db_service.execute_one(
            """
            SELECT COALESCE(SUM(amount_kobo), 0)::bigint AS revenue_kobo
            FROM billing_events
            WHERE event_type = 'plan_activated' AND amount_kobo IS NOT NULL
            """
        )
        recent_signups = await db_service.execute_query(
            """
            SELECT id, email, full_name, plan, role, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 8
            """
        )

        return {
            "total_users": (totals or {}).get("total_users", 0),
            "active_users": (totals or {}).get("active_users", 0),
            "admin_users": (totals or {}).get("admin_users", 0),
            "paid_users": (totals or {}).get("paid_users", 0),
            "total_transactions": (tx_totals or {}).get("total_transactions", 0),
            "revenue_kobo": int((revenue or {}).get("revenue_kobo") or 0),
            "users_by_plan": [
                {"plan": r["plan"], "count": r["count"]} for r in (by_plan or [])
            ],
            "users_by_subscription_status": [
                {"status": r["subscription_status"], "count": r["count"]}
                for r in (by_status or [])
            ],
            "recent_signups": [_serialize_user(r) for r in (recent_signups or [])],
        }
