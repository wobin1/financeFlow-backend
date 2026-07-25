from __future__ import annotations

from decimal import Decimal
from typing import Annotated, List, Optional
from datetime import date

from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.api.api_v1.endpoints.auth import get_current_user
from app.core.currency import normalize_currency
from app.core.rate_limit import enforce_rate_limit
from app.services.transaction_service import TransactionService
from app.core.utils import ensure_uuid
from app.services.entitlements import (
    PlanLimitError,
    assert_can_create_transaction,
    assert_feature,
    effective_plan,
    plan_limit_http,
)

router = APIRouter()

MoneyAmount = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
WhtRate = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class TransactionCreate(BaseModel):
    merchant_name: str = Field(..., min_length=1, max_length=255)
    amount: MoneyAmount
    description: str = Field(default="", max_length=2000)
    transaction_date: date
    currency: str = Field(default="NGN", max_length=10)
    plaid_transaction_id: Optional[str] = Field(default=None, max_length=255)
    source: str = Field(default="manual", max_length=20)
    category: Optional[str] = Field(default=None, max_length=100)
    vat_deductible: Optional[bool] = None
    wht_applicable: Optional[bool] = None
    wht_rate: Optional[WhtRate] = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("amount")
    @classmethod
    def amount_not_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("Amount cannot be zero")
        if abs(value) >= Decimal("10000000000"):
            raise ValueError("Amount exceeds supported range")
        return value


class TransactionUpdate(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    category: Optional[str] = Field(default=None, max_length=100)
    vat_deductible: Optional[bool] = None
    wht_applicable: Optional[bool] = None
    wht_rate: Optional[WhtRate] = None


class TransactionResponse(BaseModel):
    id: str
    merchant_name: str
    amount: MoneyAmount
    currency: str
    transaction_date: date
    raw_description: str
    category: Optional[str]
    ai_confidence: Optional[float]
    status: str
    source: str = "bank"
    vat_deductible: Optional[bool] = None
    wht_applicable: Optional[bool] = None
    wht_rate: Optional[MoneyAmount] = None
    created_at: str


class TransactionSummary(BaseModel):
    summary: dict
    currency: str = "NGN"
    categories: List[dict]
    monthly_trends: List[dict]
    recent_transactions: List[dict]


class BulkCategoryItem(BaseModel):
    transaction_id: str = Field(..., min_length=1, max_length=36)
    category: str = Field(..., min_length=1, max_length=100)


class BulkCategoryUpdate(BaseModel):
    updates: List[BulkCategoryItem] = Field(..., min_length=1, max_length=500)


def _to_transaction_response(transaction: dict) -> TransactionResponse:
    wht_rate = transaction.get("wht_rate")
    vat_raw = transaction.get("vat_deductible")
    wht_raw = transaction.get("wht_applicable")
    raw_desc = transaction.get("raw_description") or ""
    return TransactionResponse(
        id=str(transaction["id"]),
        merchant_name=transaction["merchant_name"],
        amount=Decimal(str(transaction["amount"])),
        currency=transaction["currency"],
        transaction_date=transaction["transaction_date"],
        raw_description=raw_desc,
        category=transaction["category"],
        ai_confidence=transaction["ai_confidence"],
        status=transaction["status"],
        source=transaction.get("source") or "bank",
        vat_deductible=None if vat_raw is None else bool(vat_raw),
        wht_applicable=None if wht_raw is None else bool(wht_raw),
        wht_rate=Decimal(str(wht_rate)) if wht_rate is not None else None,
        created_at=transaction["created_at"].isoformat(),
    )

@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    transaction_data: TransactionCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    enforce_rate_limit(request, bucket="tx-create", limit=30, window_seconds=60)
    service = TransactionService()
    source = transaction_data.source if transaction_data.source in ("bank", "manual") else "manual"

    if source == "manual" and not transaction_data.category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category is required for manual transactions",
        )

    try:
        await assert_can_create_transaction(current_user)
    except PlanLimitError as e:
        raise plan_limit_http(e)

    plan = effective_plan(current_user)
    use_ai = plan.ai_categorization and source != "manual"
    
    try:
        transaction = await service.create_transaction(
            user_id=ensure_uuid(current_user['id']),
            merchant_name=transaction_data.merchant_name.strip(),
            amount=transaction_data.amount,
            description=(transaction_data.description or "").strip() or transaction_data.merchant_name.strip(),
            transaction_date=transaction_data.transaction_date,
            currency=transaction_data.currency or current_user.get("currency") or "NGN",
            plaid_transaction_id=transaction_data.plaid_transaction_id,
            source=source,
            category=transaction_data.category,
            vat_deductible=transaction_data.vat_deductible,
            wht_applicable=transaction_data.wht_applicable,
            wht_rate=transaction_data.wht_rate,
            use_ai=use_ai,
        )
        
        return _to_transaction_response(transaction)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create transaction"
        )

@router.get("/", response_model=List[TransactionResponse])
async def get_transactions(
    current_user: dict = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    service = TransactionService()
    
    transactions = await service.get_user_transactions(
        user_id=ensure_uuid(current_user['id']),
        skip=skip,
        limit=limit,
        status=status_filter,
        category=category,
        start_date=start_date,
        end_date=end_date
    )
    
    return [_to_transaction_response(t) for t in transactions]

@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    try:
        transaction = await service.get_transaction_by_id(
            transaction_id=ensure_uuid(transaction_id),
            user_id=ensure_uuid(current_user['id'])
        )
        
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return _to_transaction_response(transaction)
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid transaction ID format"
        )

@router.put("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: str,
    update_data: TransactionUpdate,
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    try:
        transaction = await service.update_transaction_status(
            transaction_id=ensure_uuid(transaction_id),
            status=update_data.status,
            category=update_data.category,
            vat_deductible=update_data.vat_deductible,
            wht_applicable=update_data.wht_applicable,
            wht_rate=update_data.wht_rate,
            user_id=ensure_uuid(current_user['id'])
        )
        
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return _to_transaction_response(transaction)
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid transaction ID format"
        )

@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    try:
        success = await service.delete_transaction(
            transaction_id=ensure_uuid(transaction_id),
            user_id=ensure_uuid(current_user['id'])
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return {"message": "Transaction deleted successfully"}
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid transaction ID format"
        )

@router.get("/summary/dashboard", response_model=TransactionSummary)
async def get_transaction_summary(
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    summary_data = await service.get_transaction_summary(
        user_id=ensure_uuid(current_user['id']),
        currency=current_user.get("currency") or "NGN",
    )
    
    return TransactionSummary(**summary_data)

@router.post("/bulk-update-categories")
async def bulk_update_categories(
    bulk_update: BulkCategoryUpdate,
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    try:
        updated_count = await service.bulk_update_categories(
            user_id=ensure_uuid(current_user['id']),
            updates=[item.model_dump() for item in bulk_update.updates],
        )
        
        return {
            "message": f"Successfully updated {updated_count} transactions",
            "updated_count": updated_count
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update categories"
        )

@router.get("/analytics/spending")
async def get_spending_analytics(
    start_date: date,
    end_date: date,
    current_user: dict = Depends(get_current_user)
):
    try:
        assert_feature(current_user, "advanced_analytics")
    except PlanLimitError as e:
        raise plan_limit_http(e)

    service = TransactionService()
    
    analytics = await service.get_spending_analytics(
        user_id=ensure_uuid(current_user['id']),
        start_date=start_date,
        end_date=end_date,
        currency=current_user.get("currency") or "NGN",
    )
    
    return analytics
