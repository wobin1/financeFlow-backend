"""Plan definitions and entitlement helpers for FinanceFlow billing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    amount_ngn: int
    description: str
    max_banks: Optional[int]  # None = unlimited
    max_transactions_per_month: Optional[int]  # None = unlimited
    ai_categorization: bool
    firs_access: bool
    firs_export: bool
    advanced_analytics: bool
    priority_support: bool

    @property
    def amount_kobo(self) -> int:
        return self.amount_ngn * 100

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["amount_kobo"] = self.amount_kobo
        data["currency"] = "NGN"
        data["interval"] = "monthly"
        data["features"] = [
            (
                "No bank linking"
                if self.max_banks == 0
                else (
                    f"{self.max_banks} bank account"
                    if self.max_banks == 1
                    else (
                        f"{self.max_banks} bank accounts"
                        if self.max_banks is not None
                        else "Unlimited bank accounts"
                    )
                )
            ),
            (
                f"{self.max_transactions_per_month} transactions / month"
                if self.max_transactions_per_month is not None
                else "Unlimited transactions"
            ),
            "AI categorization" if self.ai_categorization else "Manual categorization only",
            "FIRS filing prep" if self.firs_access else "No FIRS access",
            "FIRS CSV export" if self.firs_export else None,
            "Advanced analytics" if self.advanced_analytics else "Basic dashboard",
            "Priority support" if self.priority_support else None,
        ]
        data["features"] = [f for f in data["features"] if f]
        return data


PLANS: Dict[str, Plan] = {
    "free": Plan(
        id="free",
        name="Free",
        amount_ngn=0,
        description="Get started with essentials.",
        max_banks=0,
        max_transactions_per_month=50,
        ai_categorization=False,
        firs_access=False,
        firs_export=False,
        advanced_analytics=False,
        priority_support=False,
    ),
    "starter": Plan(
        id="starter",
        name="Starter",
        amount_ngn=3500,
        description="Unlimited manual tracking with FIRS prep.",
        max_banks=0,
        max_transactions_per_month=None,
        ai_categorization=False,
        firs_access=True,
        firs_export=False,
        advanced_analytics=False,
        priority_support=False,
    ),
    "growth": Plan(
        id="growth",
        name="Growth",
        amount_ngn=10000,
        description="Bank sync, AI, and fuller tax tooling.",
        max_banks=2,
        max_transactions_per_month=None,
        ai_categorization=True,
        firs_access=True,
        firs_export=True,
        advanced_analytics=True,
        priority_support=False,
    ),
    "business": Plan(
        id="business",
        name="Business",
        amount_ngn=20000,
        description="More linked accounts with priority support.",
        max_banks=5,
        max_transactions_per_month=None,
        ai_categorization=True,
        firs_access=True,
        firs_export=True,
        advanced_analytics=True,
        priority_support=True,
    ),
}

PAID_PLAN_IDS = ("starter", "growth", "business")


def get_plan(plan_id: Optional[str]) -> Plan:
    if not plan_id or plan_id not in PLANS:
        return PLANS["free"]
    return PLANS[plan_id]


def list_plans() -> list[Dict[str, Any]]:
    return [PLANS[pid].to_dict() for pid in ("free", "starter", "growth", "business")]
