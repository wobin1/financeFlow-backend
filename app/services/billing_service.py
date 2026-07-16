"""Paystack billing service — checkout, verify, webhooks, cancel."""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.database import db_service
from app.core.plans import PAID_PLAN_IDS, PLANS, get_plan

logger = logging.getLogger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"


class BillingService:
    def __init__(self) -> None:
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.public_key = settings.PAYSTACK_PUBLIC_KEY

    def _headers(self) -> Dict[str, str]:
        if not self.secret_key:
            raise ValueError("Paystack is not configured (PAYSTACK_SECRET_KEY missing)")
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def _plan_code(self, plan_id: str) -> Optional[str]:
        mapping = {
            "starter": settings.PAYSTACK_PLAN_STARTER,
            "growth": settings.PAYSTACK_PLAN_GROWTH,
            "business": settings.PAYSTACK_PLAN_BUSINESS,
        }
        return mapping.get(plan_id) or None

    async def initialize_checkout(
        self,
        *,
        user: Dict[str, Any],
        plan_id: str,
        callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        if plan_id not in PAID_PLAN_IDS:
            raise ValueError("Select a paid plan to checkout")

        plan = get_plan(plan_id)
        user_id = str(user["id"])
        email = user["email"]
        cb = callback_url or f"{settings.FRONTEND_URL.rstrip('/')}/billing/success"

        payload: Dict[str, Any] = {
            "email": email,
            "amount": plan.amount_kobo,
            "currency": "NGN",
            "callback_url": cb,
            "metadata": {
                "user_id": user_id,
                "plan": plan_id,
                "custom_fields": [
                    {"display_name": "Plan", "variable_name": "plan", "value": plan.name},
                ],
            },
        }

        plan_code = self._plan_code(plan_id)
        if plan_code:
            payload["plan"] = plan_code

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{PAYSTACK_BASE}/transaction/initialize",
                headers=self._headers(),
                json=payload,
            )
            data = resp.json()
            if resp.status_code >= 400 or not data.get("status"):
                message = data.get("message") or "Failed to initialize Paystack payment"
                raise ValueError(message)

        result = data["data"]
        await self._log_event(
            user_id=uuid.UUID(user_id),
            event_type="checkout_initialized",
            reference=result.get("reference"),
            plan=plan_id,
            amount_kobo=plan.amount_kobo,
            payload=result,
        )
        return {
            "authorization_url": result["authorization_url"],
            "access_code": result["access_code"],
            "reference": result["reference"],
            "plan": plan.to_dict(),
            "public_key": self.public_key,
        }

    async def verify_transaction(self, reference: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{PAYSTACK_BASE}/transaction/verify/{reference}",
                headers=self._headers(),
            )
            data = resp.json()
            if resp.status_code >= 400 or not data.get("status"):
                raise ValueError(data.get("message") or "Verification failed")

        tx = data["data"]
        if tx.get("status") != "success":
            raise ValueError(f"Payment not successful (status={tx.get('status')})")

        user_id, plan_id = self._extract_user_and_plan(tx)
        if not user_id or not plan_id:
            raise ValueError("Payment metadata missing user or plan")

        subscription = await self.activate_plan(
            user_id=user_id,
            plan_id=plan_id,
            reference=reference,
            paystack_data=tx,
        )
        return subscription

    def verify_webhook_signature(self, body: bytes, signature: Optional[str]) -> bool:
        if not self.secret_key or not signature:
            return False
        digest = hmac.new(
            self.secret_key.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    async def handle_webhook(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("charge.success", "subscription.create"):
            user_id, plan_id = self._extract_user_and_plan(data)
            reference = data.get("reference") or data.get("id")
            if user_id and plan_id:
                await self.activate_plan(
                    user_id=user_id,
                    plan_id=plan_id,
                    reference=str(reference) if reference else None,
                    paystack_data=data,
                )
                return {"handled": True, "action": "activated", "plan": plan_id}

        if event in ("subscription.disable", "subscription.not_renew", "invoice.payment_failed"):
            customer = (data.get("customer") or {}) if isinstance(data, dict) else {}
            customer_code = customer.get("customer_code") or data.get("customer_code")
            email = customer.get("email") or data.get("customer_email")
            user = await self._find_user(customer_code=customer_code, email=email)
            if user:
                # Keep access until period end; mark cancelled / past_due
                new_status = "past_due" if "failed" in event else "cancelled"
                await self._update_subscription(
                    user_id=user["id"],
                    plan=user.get("plan") or "free",
                    subscription_status=new_status,
                    period_end=user.get("plan_period_end"),
                    customer_code=user.get("paystack_customer_code"),
                    subscription_code=user.get("paystack_subscription_code"),
                    authorization_code=user.get("paystack_authorization_code"),
                )
                await self._log_event(
                    user_id=user["id"],
                    event_type=event,
                    reference=str(data.get("reference") or data.get("subscription_code") or ""),
                    plan=user.get("plan"),
                    amount_kobo=None,
                    payload=data,
                )
                return {"handled": True, "action": new_status}

        return {"handled": False, "event": event}

    async def activate_plan(
        self,
        *,
        user_id: uuid.UUID,
        plan_id: str,
        reference: Optional[str],
        paystack_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = get_plan(plan_id)
        if plan.id == "free":
            raise ValueError("Cannot activate free via Paystack")

        # Idempotent: skip if this payment already activated a plan
        if reference:
            existing = await db_service.execute_one(
                """
                SELECT id FROM billing_events
                WHERE paystack_reference = $1 AND event_type = 'plan_activated'
                """,
                reference,
            )
            if existing:
                user = await db_service.execute_one(
                    """
                    SELECT id, email, plan, subscription_status, plan_period_end,
                           paystack_customer_code, paystack_subscription_code
                    FROM users WHERE id = $1
                    """,
                    user_id,
                )
                return {
                    "already_processed": True,
                    "plan": get_plan(user.get("plan") if user else plan_id).to_dict(),
                    "subscription_status": user.get("subscription_status") if user else "active",
                    "plan_period_end": user.get("plan_period_end").isoformat()
                    if user and user.get("plan_period_end")
                    else None,
                }

        customer = paystack_data.get("customer") or {}
        authorization = paystack_data.get("authorization") or {}
        customer_code = customer.get("customer_code")
        auth_code = authorization.get("authorization_code")
        subscription_code = (
            paystack_data.get("subscription_code")
            or (paystack_data.get("subscription") or {}).get("subscription_code")
        )

        period_end = datetime.utcnow() + timedelta(days=30)
        # Prefer Paystack next_payment_date when present
        next_payment = paystack_data.get("next_payment_date")
        if next_payment:
            try:
                period_end = datetime.fromisoformat(str(next_payment).replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                pass

        await self._update_subscription(
            user_id=user_id,
            plan=plan_id,
            subscription_status="active",
            period_end=period_end,
            customer_code=customer_code,
            subscription_code=subscription_code,
            authorization_code=auth_code,
        )

        amount = paystack_data.get("amount")
        await self._log_event(
            user_id=user_id,
            event_type="plan_activated",
            reference=reference,
            plan=plan_id,
            amount_kobo=int(amount) if amount is not None else plan.amount_kobo,
            payload=paystack_data,
        )

        return {
            "already_processed": False,
            "plan": plan.to_dict(),
            "subscription_status": "active",
            "plan_period_end": period_end.isoformat(),
        }

    async def cancel_subscription(self, user: Dict[str, Any]) -> Dict[str, Any]:
        user_id = user["id"] if isinstance(user["id"], uuid.UUID) else uuid.UUID(str(user["id"]))
        sub_code = user.get("paystack_subscription_code")
        email_token = None

        if sub_code and self.secret_key:
            # Fetch subscription to get email_token, then disable
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    get_resp = await client.get(
                        f"{PAYSTACK_BASE}/subscription/{sub_code}",
                        headers=self._headers(),
                    )
                    get_data = get_resp.json()
                    if get_data.get("status"):
                        email_token = get_data["data"].get("email_token")

                    if email_token:
                        disable_resp = await client.post(
                            f"{PAYSTACK_BASE}/subscription/disable",
                            headers=self._headers(),
                            json={"code": sub_code, "token": email_token},
                        )
                        disable_data = disable_resp.json()
                        if not disable_data.get("status"):
                            logger.warning(
                                "Paystack disable failed: %s", disable_data.get("message")
                            )
            except Exception as exc:
                logger.exception("Failed to disable Paystack subscription: %s", exc)

        await self._update_subscription(
            user_id=user_id,
            plan=user.get("plan") or "free",
            subscription_status="cancelled",
            period_end=user.get("plan_period_end") or datetime.utcnow() + timedelta(days=1),
            customer_code=user.get("paystack_customer_code"),
            subscription_code=sub_code,
            authorization_code=user.get("paystack_authorization_code"),
        )

        await self._log_event(
            user_id=user_id,
            event_type="subscription_cancelled",
            reference=sub_code,
            plan=user.get("plan"),
            amount_kobo=None,
            payload={"local": True},
        )

        return {
            "message": "Subscription cancelled. Access continues until the current period ends.",
            "subscription_status": "cancelled",
            "plan_period_end": (user.get("plan_period_end") or datetime.utcnow()).isoformat()
            if isinstance(user.get("plan_period_end"), datetime)
            else user.get("plan_period_end"),
        }

    async def downgrade_to_free(self, user_id: uuid.UUID) -> None:
        await self._update_subscription(
            user_id=user_id,
            plan="free",
            subscription_status="active",
            period_end=None,
            customer_code=None,
            subscription_code=None,
            authorization_code=None,
        )

    def _extract_user_and_plan(
        self, data: Dict[str, Any]
    ) -> tuple[Optional[uuid.UUID], Optional[str]]:
        metadata = data.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = {}

        user_id_raw = metadata.get("user_id")
        plan_id = metadata.get("plan")

        # Fallback: plan code amount match (weak) — skip
        if not plan_id:
            plan_obj = data.get("plan") or {}
            plan_name = (plan_obj.get("name") or "").lower()
            for pid, p in PLANS.items():
                if pid != "free" and p.name.lower() in plan_name:
                    plan_id = pid
                    break

        user_uuid = None
        if user_id_raw:
            try:
                user_uuid = uuid.UUID(str(user_id_raw))
            except ValueError:
                user_uuid = None

        return user_uuid, plan_id if plan_id in PLANS else None

    async def _find_user(
        self,
        *,
        customer_code: Optional[str],
        email: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if customer_code:
            row = await db_service.execute_one(
                """
                SELECT id, email, plan, subscription_status, plan_period_end,
                       paystack_customer_code, paystack_subscription_code,
                       paystack_authorization_code
                FROM users WHERE paystack_customer_code = $1
                """,
                customer_code,
            )
            if row:
                return row
        if email:
            return await db_service.execute_one(
                """
                SELECT id, email, plan, subscription_status, plan_period_end,
                       paystack_customer_code, paystack_subscription_code,
                       paystack_authorization_code
                FROM users WHERE email = $1
                """,
                email,
            )
        return None

    async def _update_subscription(
        self,
        *,
        user_id: uuid.UUID,
        plan: str,
        subscription_status: str,
        period_end: Optional[datetime],
        customer_code: Optional[str],
        subscription_code: Optional[str],
        authorization_code: Optional[str],
    ) -> None:
        await db_service.execute_command(
            """
            UPDATE users SET
                plan = $1,
                subscription_status = $2,
                plan_period_end = $3,
                paystack_customer_code = COALESCE($4, paystack_customer_code),
                paystack_subscription_code = COALESCE($5, paystack_subscription_code),
                paystack_authorization_code = COALESCE($6, paystack_authorization_code),
                plan_updated_at = $7,
                updated_at = $7
            WHERE id = $8
            """,
            plan,
            subscription_status,
            period_end,
            customer_code,
            subscription_code,
            authorization_code,
            datetime.utcnow(),
            user_id,
        )

    async def _log_event(
        self,
        *,
        user_id: Optional[uuid.UUID],
        event_type: str,
        reference: Optional[str],
        plan: Optional[str],
        amount_kobo: Optional[int],
        payload: Any,
    ) -> None:
        import json

        try:
            await db_service.execute_command(
                """
                INSERT INTO billing_events (
                    id, user_id, event_type, paystack_reference, plan, amount_kobo, payload, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                """,
                uuid.uuid4(),
                user_id,
                event_type,
                reference,
                plan,
                amount_kobo,
                json.dumps(payload, default=str),
                datetime.utcnow(),
            )
        except Exception:
            logger.exception("Failed to log billing event")
