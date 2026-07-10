from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime
import uuid

from app.api.api_v1.endpoints.auth import get_current_user
from app.services.transaction_service import TransactionService
from app.core.utils import ensure_uuid, uuid_to_str

router = APIRouter()

# Pydantic models
class TransactionCreate(BaseModel):
    merchant_name: str
    amount: float
    description: str
    transaction_date: date
    currency: str = "NGN"
    plaid_transaction_id: Optional[str] = None

class TransactionUpdate(BaseModel):
    status: Optional[str] = None
    category: Optional[str] = None
    vat_deductible: Optional[bool] = None
    wht_applicable: Optional[bool] = None
    wht_rate: Optional[float] = None

class TransactionResponse(BaseModel):
    id: str
    merchant_name: str
    amount: float
    currency: str
    transaction_date: date
    raw_description: str
    category: Optional[str]
    ai_confidence: Optional[float]
    status: str
    vat_deductible: Optional[bool] = None
    wht_applicable: Optional[bool] = None
    wht_rate: Optional[float] = None
    created_at: str

class TransactionSummary(BaseModel):
    summary: dict
    categories: List[dict]
    monthly_trends: List[dict]
    recent_transactions: List[dict]

class BulkCategoryUpdate(BaseModel):
    updates: List[dict]  # [{"transaction_id": "uuid", "category": "string"}]


def _to_transaction_response(transaction: dict) -> TransactionResponse:
    wht_rate = transaction.get("wht_rate")
    vat_raw = transaction.get("vat_deductible")
    wht_raw = transaction.get("wht_applicable")
    return TransactionResponse(
        id=str(transaction["id"]),
        merchant_name=transaction["merchant_name"],
        amount=float(transaction["amount"]),
        currency=transaction["currency"],
        transaction_date=transaction["transaction_date"],
        raw_description=transaction["raw_description"],
        category=transaction["category"],
        ai_confidence=transaction["ai_confidence"],
        status=transaction["status"],
        vat_deductible=None if vat_raw is None else bool(vat_raw),
        wht_applicable=None if wht_raw is None else bool(wht_raw),
        wht_rate=float(wht_rate) if wht_rate is not None else None,
        created_at=transaction["created_at"].isoformat(),
    )

@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    transaction_data: TransactionCreate,
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    try:
        transaction = await service.create_transaction(
            user_id=ensure_uuid(current_user['id']),
            merchant_name=transaction_data.merchant_name,
            amount=transaction_data.amount,
            description=transaction_data.description,
            transaction_date=transaction_data.transaction_date,
            currency=transaction_data.currency,
            plaid_transaction_id=transaction_data.plaid_transaction_id
        )
        
        return _to_transaction_response(transaction)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create transaction: {str(e)}"
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
        user_id=ensure_uuid(current_user['id'])
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
            updates=bulk_update.updates
        )
        
        return {
            "message": f"Successfully updated {updated_count} transactions",
            "updated_count": updated_count
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update categories: {str(e)}"
        )

@router.get("/analytics/spending")
async def get_spending_analytics(
    start_date: date,
    end_date: date,
    current_user: dict = Depends(get_current_user)
):
    service = TransactionService()
    
    analytics = await service.get_spending_analytics(
        user_id=ensure_uuid(current_user['id']),
        start_date=start_date,
        end_date=end_date
    )
    
    return analytics
