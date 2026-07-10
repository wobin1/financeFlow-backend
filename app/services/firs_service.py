"""
FIRS filing prep — aggregates transactions into copy-ready tax worksheet figures.

Figures are draft estimates from bank transactions. Users must review before filing
on the FIRS TaxPro-Max portal.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
import calendar
import re
import uuid

from app.core.database import db_service

VAT_RATE = Decimal("0.075")
CIT_RATE = Decimal("0.30")

# Canonical slug keys used across Mono sync / AI
INCOME_CATEGORIES: Set[str] = {
    "sales_revenue",
    "service_revenue",
    "rental_income",
    "interest_income",
    "dividend_income",
    "other_income",
    "Sales Revenue",
    "Service Revenue",
    "Rental Income",
    "Interest Income",
    "Dividend Income",
    "Other Income",
}

INPUT_VAT_EXPENSE_CATEGORIES: Set[str] = {
    "cost_of_goods_sold",
    "raw_materials",
    "office_supplies",
    "marketing_advertising",
    "professional_fees",
    "utilities",
    "repairs_maintenance",
    "transport_logistics",
    "communication",
    "Cost of Goods Sold",
    "Raw Materials",
    "Office Supplies",
    "Marketing and Advertising",
    "Professional Fees",
    "Utilities",
    "Repairs and Maintenance",
    "Transport and Logistics",
    "Communication",
}

OPERATING_EXPENSE_CATEGORIES: Set[str] = INPUT_VAT_EXPENSE_CATEGORIES | {
    "salaries_wages",
    "rent_expense",
    "insurance",
    "depreciation",
    "bank_charges",
    "training_development",
    "entertainment",
    "travel_expenses",
    "Salaries and Wages",
    "Rent Expense",
    "Insurance",
    "Depreciation",
    "Bank Charges",
    "Training and Development",
    "Entertainment",
    "Travel Expenses",
}

TAX_CATEGORY_ALIASES = {
    "vat_payable": "vat",
    "VAT Payable": "vat",
    "withholding_tax": "wht",
    "Withholding Tax": "wht",
    "company_income_tax": "cit",
    "Company Income Tax": "cit",
    "personal_income_tax": "paye",
    "Personal Income Tax": "paye",
}

WHT_NARRATION_PATTERNS = [
    re.compile(r"\bwht\b", re.I),
    re.compile(r"withhold", re.I),
    re.compile(r"tax\s*deduct", re.I),
]

VAT_NARRATION_PATTERNS = [
    re.compile(r"\bvat\b", re.I),
    re.compile(r"value\s*added", re.I),
]

FIRS_NARRATION_PATTERNS = [
    re.compile(r"\bfirs\b", re.I),
    re.compile(r"taxpromax", re.I),
    re.compile(r"tax\s*pro", re.I),
]


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _period_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _detect_tax_hint(description: str, category: Optional[str]) -> Optional[str]:
    text = description or ""
    if category and category in TAX_CATEGORY_ALIASES:
        return TAX_CATEGORY_ALIASES[category]

    for pattern in VAT_NARRATION_PATTERNS:
        if pattern.search(text):
            return "vat"
    for pattern in WHT_NARRATION_PATTERNS:
        if pattern.search(text):
            return "wht"
    for pattern in FIRS_NARRATION_PATTERNS:
        if pattern.search(text):
            return "firs_payment"
    return None


def _serialize_transaction(row: Dict[str, Any]) -> Dict[str, Any]:
    amount = _decimal(row.get("amount"))
    description = row.get("raw_description") or row.get("merchant_name") or ""
    category = row.get("category")
    tax_hint = _detect_tax_hint(description, category)
    vat_raw = row.get("vat_deductible")
    wht_raw = row.get("wht_applicable")
    wht_rate = row.get("wht_rate")

    return {
        "id": str(row.get("id")),
        "merchant_name": row.get("merchant_name"),
        "amount": _money(amount),
        "transaction_date": row.get("transaction_date").isoformat()
        if hasattr(row.get("transaction_date"), "isoformat")
        else str(row.get("transaction_date")),
        "category": category,
        "status": row.get("status"),
        "raw_description": description,
        "tax_hint": tax_hint,
        "vat_deductible": None if vat_raw is None else bool(vat_raw),
        "wht_applicable": None if wht_raw is None else bool(wht_raw),
        "wht_rate": float(wht_rate) if wht_rate is not None else None,
        "is_income": amount > 0,
        "is_expense": amount < 0,
    }


def _is_vat_deductible(tx: Dict[str, Any]) -> bool:
    """Explicit flag wins; otherwise fall back to VAT-eligible expense categories."""
    flag = tx.get("vat_deductible")
    if flag is True:
        return True
    if flag is False:
        return False
    category = tx.get("category") or ""
    return category in INPUT_VAT_EXPENSE_CATEGORIES


def _wht_amount_for_tx(tx: Dict[str, Any]) -> Optional[Decimal]:
    """
    Return WHT amount for a transaction, or None if not WHT-related.

    - Category/narration WHT remittance lines: amount IS the WHT
    - wht_applicable payments: WHT = gross × rate
    """
    amount = _decimal(tx["amount"])
    if amount >= 0:
        return None

    category = tx.get("category") or ""
    hint = tx.get("tax_hint")
    description = tx.get("raw_description") or ""
    flag = tx.get("wht_applicable")

    is_remittance_line = (
        hint == "wht"
        or category in {"withholding_tax", "Withholding Tax"}
        or any(p.search(description) for p in WHT_NARRATION_PATTERNS)
    )

    if flag is False and not is_remittance_line:
        return None

    if is_remittance_line and flag is not True:
        return abs(amount)

    if flag is True or (flag is None and is_remittance_line):
        if flag is True:
            rate = _decimal(tx.get("wht_rate") or 5) / Decimal("100")
            return (abs(amount) * rate).quantize(Decimal("0.01"))
        return abs(amount)

    return None


class FirsService:
    """Build FIRS prep worksheets from stored transactions."""

    async def _get_user_profile(self, user_id: uuid.UUID) -> Dict[str, Any]:
        query = """
            SELECT id, email, full_name, business_name, cac_number, tin_number,
                   business_type, country, currency
            FROM users
            WHERE id = $1
        """
        row = await db_service.execute_one(query, user_id)
        if not row:
            raise ValueError("User not found")
        return row

    async def _get_period_transactions(
        self,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT id, merchant_name, amount, currency, transaction_date,
                   raw_description, category, status,
                   vat_deductible, wht_applicable, wht_rate
            FROM transactions
            WHERE user_id = $1
              AND transaction_date >= $2
              AND transaction_date <= $3
            ORDER BY transaction_date ASC, created_at ASC
        """
        rows = await db_service.execute_query(query, user_id, start_date, end_date)
        return [_serialize_transaction(row) for row in rows]

    def _build_vat_worksheet(
        self,
        transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        taxable_supplies = Decimal("0")
        vatable_purchases = Decimal("0")
        vat_paid_to_firs = Decimal("0")
        vat_related: List[Dict[str, Any]] = []
        deductible_items: List[Dict[str, Any]] = []

        for tx in transactions:
            amount = _decimal(tx["amount"])
            category = tx.get("category") or ""
            hint = tx.get("tax_hint")

            if hint == "vat" and amount < 0:
                vat_paid_to_firs += abs(amount)
                vat_related.append(tx)
                continue

            if amount > 0 and (
                category in INCOME_CATEGORIES
                or category.endswith("Revenue")
                or category.endswith("Income")
            ):
                taxable_supplies += amount
                continue

            if amount < 0 and _is_vat_deductible(tx):
                vatable_purchases += abs(amount)
                deductible_items.append(tx)

        output_vat = (taxable_supplies * VAT_RATE).quantize(Decimal("0.01"))
        input_vat = (vatable_purchases * VAT_RATE).quantize(Decimal("0.01"))
        net_vat_payable = (output_vat - input_vat - vat_paid_to_firs).quantize(Decimal("0.01"))

        fields = [
            {
                "key": "taxable_supplies",
                "label": "Total value of taxable supplies (₦)",
                "value": _money(taxable_supplies),
                "portal_hint": "VAT return — taxable sales / supplies",
            },
            {
                "key": "output_vat",
                "label": "Output VAT @ 7.5% (₦)",
                "value": _money(output_vat),
                "portal_hint": "VAT on sales / output tax",
            },
            {
                "key": "vatable_purchases",
                "label": "Total value of vatable purchases (₦)",
                "value": _money(vatable_purchases),
                "portal_hint": "Purchases marked VAT deductible",
            },
            {
                "key": "input_vat",
                "label": "Input VAT @ 7.5% (₦)",
                "value": _money(input_vat),
                "portal_hint": "VAT on purchases / input tax",
            },
            {
                "key": "vat_already_remitted",
                "label": "VAT already remitted to FIRS (₦)",
                "value": _money(vat_paid_to_firs),
                "portal_hint": "Prior VAT payments in this period",
            },
            {
                "key": "net_vat_payable",
                "label": "Net VAT payable (₦)",
                "value": _money(net_vat_payable),
                "portal_hint": "Amount due to FIRS (TaxPro-Max VAT form)",
            },
        ]

        return {
            "title": "VAT Return Worksheet",
            "rate": "7.5%",
            "fields": fields,
            "summary": {
                "taxable_supplies": _money(taxable_supplies),
                "output_vat": _money(output_vat),
                "vatable_purchases": _money(vatable_purchases),
                "input_vat": _money(input_vat),
                "vat_remitted": _money(vat_paid_to_firs),
                "net_vat_payable": _money(net_vat_payable),
            },
            "supporting_transactions": vat_related,
            "deductible_transactions": deductible_items[:50],
            "notes": [
                "Turn on 'VAT deductible' when categorizing purchases that include reclaimable VAT.",
                "If unset, supplies/utilities-style categories are treated as VAT-eligible by default.",
                "Turn the toggle off to exclude a purchase from input VAT.",
                "Assumes standard-rated supplies at 7.5%.",
            ],
        }

    def _build_wht_worksheet(
        self,
        transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        wht_withheld = Decimal("0")
        wht_items: List[Dict[str, Any]] = []

        for tx in transactions:
            wht_amount = _wht_amount_for_tx(tx)
            if wht_amount is None:
                continue

            wht_withheld += wht_amount
            wht_items.append({
                **tx,
                "wht_amount": _money(wht_amount),
                "wht_basis": (
                    "rate"
                    if tx.get("wht_applicable") is True
                    else "remittance_line"
                ),
            })

        fields = [
            {
                "key": "total_wht_withheld",
                "label": "Total WHT withheld / estimated (₦)",
                "value": _money(wht_withheld),
                "portal_hint": "WHT schedule — total tax withheld at source",
            },
            {
                "key": "wht_transaction_count",
                "label": "Number of WHT transactions",
                "value": len(wht_items),
                "portal_hint": "Count of WHT lines in period",
            },
        ]

        return {
            "title": "WHT Remittance Worksheet",
            "fields": fields,
            "summary": {
                "total_wht_withheld": _money(wht_withheld),
                "transaction_count": len(wht_items),
            },
            "line_items": wht_items,
            "notes": [
                "Mark payments as 'WHT applicable' and pick a rate (e.g. 5% or 10%).",
                "Estimated WHT = payment amount × rate.",
                "Lines categorized as Withholding Tax are treated as the WHT amount itself.",
                "Match each line to the correct WHT schedule on TaxPro-Max.",
            ],
        }

    def _build_cit_worksheet(
        self,
        transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        total_revenue = Decimal("0")
        total_expenses = Decimal("0")
        operating_expenses = Decimal("0")
        tax_payments = Decimal("0")

        revenue_breakdown: Dict[str, Decimal] = {}
        expense_breakdown: Dict[str, Decimal] = {}

        for tx in transactions:
            amount = _decimal(tx["amount"])
            category = tx.get("category") or "uncategorized"
            hint = tx.get("tax_hint")

            if hint in {"vat", "wht", "firs_payment"} and amount < 0:
                tax_payments += abs(amount)
                continue

            if amount > 0:
                total_revenue += amount
                revenue_breakdown[category] = revenue_breakdown.get(category, Decimal("0")) + amount
            elif amount < 0:
                expense_amount = abs(amount)
                total_expenses += expense_amount
                expense_breakdown[category] = expense_breakdown.get(category, Decimal("0")) + expense_amount
                if category in OPERATING_EXPENSE_CATEGORIES:
                    operating_expenses += expense_amount

        profit_before_tax = (total_revenue - total_expenses).quantize(Decimal("0.01"))
        estimated_cit = max(Decimal("0"), (profit_before_tax * CIT_RATE)).quantize(Decimal("0.01"))
        cit_already_paid = Decimal("0")

        for tx in transactions:
            if tx.get("category") in {"company_income_tax", "Company Income Tax"} and _decimal(tx["amount"]) < 0:
                cit_already_paid += abs(_decimal(tx["amount"]))

        fields = [
            {
                "key": "total_revenue",
                "label": "Total revenue / turnover (₦)",
                "value": _money(total_revenue),
                "portal_hint": "CIT return — gross income / turnover",
            },
            {
                "key": "total_expenses",
                "label": "Total expenses (₦)",
                "value": _money(total_expenses),
                "portal_hint": "Total deductible expenses (review disallowables)",
            },
            {
                "key": "operating_expenses",
                "label": "Operating expenses (₦)",
                "value": _money(operating_expenses),
                "portal_hint": "Core operating costs excluding tax payments",
            },
            {
                "key": "profit_before_tax",
                "label": "Profit before tax (₦)",
                "value": _money(profit_before_tax),
                "portal_hint": "Assessable profit (before adjustments)",
            },
            {
                "key": "estimated_cit",
                "label": f"Estimated CIT @ {int(CIT_RATE * 100)}% (₦)",
                "value": _money(estimated_cit),
                "portal_hint": "Draft CIT liability — verify against FIRS rate bands",
            },
            {
                "key": "cit_already_paid",
                "label": "CIT already paid (₦)",
                "value": _money(cit_already_paid),
                "portal_hint": "Prior CIT payments in period",
            },
            {
                "key": "net_cit_payable",
                "label": "Net CIT payable (₦)",
                "value": _money(max(Decimal("0"), estimated_cit - cit_already_paid)),
                "portal_hint": "Balance due on annual CIT return",
            },
        ]

        return {
            "title": "Company Income Tax (CIT) Prep Worksheet",
            "rate": f"{int(CIT_RATE * 100)}% (default large company rate)",
            "fields": fields,
            "summary": {
                "total_revenue": _money(total_revenue),
                "total_expenses": _money(total_expenses),
                "profit_before_tax": _money(profit_before_tax),
                "estimated_cit": _money(estimated_cit),
                "cit_paid": _money(cit_already_paid),
            },
            "revenue_breakdown": {k: _money(v) for k, v in sorted(revenue_breakdown.items(), key=lambda x: -x[1])},
            "expense_breakdown": {k: _money(v) for k, v in sorted(expense_breakdown.items(), key=lambda x: -x[1])},
            "notes": [
                "Small companies (< ₦25M turnover) may qualify for 0% CIT — verify eligibility.",
                "Medium companies may pay 20%. This worksheet uses 30% as a conservative default.",
                "Adjust for capital allowances, depreciation, and non-deductible expenses.",
                "CIT is filed annually — use monthly figures as a running estimate only.",
            ],
        }

    def _build_checklist(self, profile: Dict[str, Any], transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pending = sum(1 for tx in transactions if tx.get("status") == "pending")
        uncategorized = sum(1 for tx in transactions if not tx.get("category"))

        items = [
            {
                "id": "tin",
                "label": "Tax Identification Number (TIN) on file",
                "done": bool(profile.get("tin_number")),
                "action": "Add your TIN in business profile settings",
            },
            {
                "id": "cac",
                "label": "CAC registration number on file",
                "done": bool(profile.get("cac_number")),
                "action": "Add CAC number for corporate filings",
            },
            {
                "id": "business_name",
                "label": "Registered business name on file",
                "done": bool(profile.get("business_name")),
                "action": "Set business name to match FIRS records",
            },
            {
                "id": "transactions",
                "label": "Transactions imported for this period",
                "done": len(transactions) > 0,
                "action": "Connect bank and sync transactions",
            },
            {
                "id": "categorized",
                "label": "All transactions categorized",
                "done": uncategorized == 0,
                "action": f"Review {uncategorized} uncategorized transaction(s)",
            },
            {
                "id": "confirmed",
                "label": "AI categories reviewed and confirmed",
                "done": pending == 0,
                "action": f"Confirm {pending} pending transaction(s) on Transactions page",
            },
        ]
        return items

    async def get_filing_prep(
        self,
        user_id: uuid.UUID,
        year: int,
        month: int,
    ) -> Dict[str, Any]:
        start_date, end_date = _period_bounds(year, month)
        profile = await self._get_user_profile(user_id)
        transactions = await self._get_period_transactions(user_id, start_date, end_date)

        vat = self._build_vat_worksheet(transactions)
        wht = self._build_wht_worksheet(transactions)
        cit = self._build_cit_worksheet(transactions)
        checklist = self._build_checklist(profile, transactions)

        period_label = start_date.strftime("%B %Y")
        ready = all(item["done"] for item in checklist[:3]) and len(transactions) > 0

        return {
            "period": {
                "year": year,
                "month": month,
                "label": period_label,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "taxpayer": {
                "business_name": profile.get("business_name") or profile.get("full_name"),
                "tin_number": profile.get("tin_number"),
                "cac_number": profile.get("cac_number"),
                "business_type": profile.get("business_type"),
                "currency": profile.get("currency") or "NGN",
            },
            "readiness": {
                "ready_for_review": ready,
                "checklist": checklist,
                "transaction_count": len(transactions),
            },
            "vat": vat,
            "wht": wht,
            "cit": cit,
            "disclaimer": (
                "Draft figures generated from bank transactions. "
                "Review all values against invoices and FIRS guidelines before filing on TaxPro-Max."
            ),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    async def export_csv(
        self,
        user_id: uuid.UUID,
        year: int,
        month: int,
    ) -> str:
        data = await self.get_filing_prep(user_id, year, month)
        lines = [
            "FinanceFlow FIRS Filing Prep Export",
            f"Period,{data['period']['label']}",
            f"Business,{data['taxpayer']['business_name']}",
            f"TIN,{data['taxpayer']['tin_number'] or 'N/A'}",
            "",
            "Section,Field,Value (NGN),Portal Hint",
        ]

        for section_key in ("vat", "wht", "cit"):
            section = data[section_key]
            for field in section["fields"]:
                lines.append(
                    f"{section['title']},{field['label']},{field['value']},{field.get('portal_hint', '')}"
                )

        lines.extend(["", "Disclaimer", data["disclaimer"]])
        return "\n".join(lines)
