import httpx
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from decimal import Decimal
from app.core.config import settings
from app.core.database import db_service
from app.core.datetime_utils import utc_now
from app.services.transaction_service import TransactionService
import logging
import uuid

logger = logging.getLogger(__name__)

class MonoService:
    """Mono service using raw SQL for database operations"""
    
    def __init__(self):
        self.secret_key = settings.MONO_SECRET_KEY
        self.public_key = settings.MONO_PUBLIC_KEY
        self.base_url = "https://api.withmono.com" if settings.MONO_ENV == "live" else "https://api.withmono.com"
        self.headers = {
            "mono-sec-key": self.secret_key,
            "Content-Type": "application/json"
        }
        self.transaction_service = TransactionService()
    
    async def exchange_token(self, code: str, user_id: uuid.UUID) -> Dict[str, Any]:
        """Exchange authorization code for account access token and store in database"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v2/accounts/auth",
                headers=self.headers,
                json={"code": code}
            )
            
            if not response.is_success:
                error_body = response.text
                logger.error(f"Mono API error {response.status_code}: {error_body}")
                raise ValueError(f"Mono API error {response.status_code}: {error_body}")
            
            data = response.json()
            logger.info(f"Mono exchange_token response: {data}")
            
            # Mono v2 wraps the account id under data.data.id
            account_id = data.get("data", {}).get("id")
            if account_id:
                await self._store_mono_account(user_id, account_id)
                logger.info(f"Stored Mono account ID: {account_id}")
            else:
                logger.warning(f"No account ID in Mono response: {data}")
            
            return data
    
    async def get_account_info(self, account_id: str) -> Dict[str, Any]:
        """Get account information from Mono API"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v2/accounts/{account_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_account_balance(self, account_id: str) -> Dict[str, Any]:
        """Get account balance from Mono API"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v2/accounts/{account_id}/balance",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_transactions(
        self, 
        account_id: str, 
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        paginate: bool = True,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get account transactions from Mono API"""
        params = {}
        if start_date:
            params["start"] = start_date.isoformat()
        if end_date:
            params["end"] = end_date.isoformat()
        if paginate:
            params["paginate"] = "true"
        if limit:
            params["limit"] = str(limit)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v2/accounts/{account_id}/transactions",
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
    
    async def sync_transactions(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Sync transactions from Mono to our database"""
        from app.services.entitlements import (
            PlanLimitError,
            assert_can_create_transaction,
            effective_plan,
        )
        from app.services.user_service import UserService

        # Get user's Mono account ID
        account_id = await self._get_user_mono_account(user_id)
        if not account_id:
            raise ValueError("User has no connected Mono account")

        user = await UserService().get_user_by_id(user_id)
        plan = effective_plan(user) if user else None
        use_ai = bool(plan and plan.ai_categorization)
        
        # Get transactions from Mono
        mono_transactions = await self.get_transactions(account_id)
        
        # Process and store transactions
        processed_count = 0
        skipped_count = 0
        limit_reached = False
        errors = []
        
        for mono_tx in mono_transactions:
            try:
                # Check if transaction already exists
                existing = await self._check_transaction_exists(mono_tx.get("_id"))
                if existing:
                    skipped_count += 1
                    continue

                if user:
                    try:
                        await assert_can_create_transaction(user)
                    except PlanLimitError as e:
                        limit_reached = True
                        errors.append(e.detail)
                        break
                
                # Format transaction data
                formatted_tx = self.format_transaction_for_processing(mono_tx)
                
                # Create transaction using raw SQL service
                await self.transaction_service.create_transaction(
                    user_id=user_id,
                    merchant_name=formatted_tx["merchant_name"],
                    amount=formatted_tx["amount"],
                    description=formatted_tx["raw_description"],
                    transaction_date=formatted_tx["transaction_date"],
                    currency=formatted_tx["currency"],
                    plaid_transaction_id=formatted_tx["external_id"],
                    source="bank",
                    use_ai=use_ai,
                )
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing transaction {mono_tx.get('_id')}: {e}")
                errors.append(str(e))
        
        return {
            "processed": processed_count,
            "skipped": skipped_count,
            "limit_reached": limit_reached,
            "errors": errors,
            "ai_categorization": use_ai,
            "total_fetched": len(mono_transactions)
        }
    
    async def get_account_identity(self, account_id: str) -> Dict[str, Any]:
        """Get account holder identity information"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/accounts/{account_id}/identity",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_account_income(self, account_id: str) -> Dict[str, Any]:
        """Get account income analysis"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/accounts/{account_id}/income",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Mono webhook events"""
        event_type = payload.get("event")
        data = payload.get("data", {})
        
        if event_type == "mono.events.account_connected":
            # Handle new account connection
            account_id = data.get("account", {}).get("id")
            # You might want to trigger a sync here
            return {"status": "account_connected", "account_id": account_id}
        
        elif event_type == "mono.events.account_updated":
            # Handle account updates
            account_id = data.get("account", {}).get("id")
            # Trigger transaction sync
            return {"status": "account_updated", "account_id": account_id}
        
        elif event_type == "mono.events.account_reauthorization_required":
            # Handle reauth required
            account_id = data.get("account", {}).get("id")
            await self._mark_account_reauth_required(account_id)
            return {"status": "reauth_required", "account_id": account_id}
        
        return {"status": "unhandled_event", "event": event_type}
    
    def format_transaction_for_processing(self, mono_transaction: Dict[str, Any]) -> Dict[str, Any]:
        """Format Mono transaction data for our internal processing"""
        from decimal import Decimal

        from app.core.datetime_utils import as_lagos_date, parse_iso_to_utc

        amount = Decimal(str(mono_transaction.get("amount", 0))) / Decimal("100")
        balance_raw = mono_transaction.get("balance")
        balance = (
            Decimal(str(balance_raw)) / Decimal("100") if balance_raw is not None else None
        )
        raw_date = mono_transaction.get("date") or ""
        transaction_date = as_lagos_date(parse_iso_to_utc(raw_date)) if raw_date else None

        return {
            "external_id": mono_transaction.get("_id"),
            "merchant_name": mono_transaction.get("narration", "Unknown"),
            "amount": amount,  # Mono returns kobo; keep Decimal (exact)
            "currency": "NGN",
            "transaction_date": transaction_date,
            "raw_description": mono_transaction.get("narration", ""),
            "transaction_type": mono_transaction.get("type", "debit"),
            "balance": balance,
            "category": mono_transaction.get("category"),
            "meta": {
                "mono_transaction_id": mono_transaction.get("_id"),
                "mono_account_id": mono_transaction.get("account"),
                "reference": mono_transaction.get("reference")
            }
        }
    
    async def verify_webhook(
        self,
        payload: bytes,
        signature: str = "",
        header_secret: str = "",
    ) -> bool:
        """Verify Mono webhook authenticity.

        Official Mono docs send the configured webhook secret in the
        `mono-webhook-secret` header for direct comparison. Also accept an
        HMAC-SHA256 digest in `mono-webhook-signature` when present.
        """
        import hashlib
        import hmac
        import secrets as secrets_mod

        webhook_secret = settings.MONO_WEBHOOK_SECRET
        if not webhook_secret:
            logger.error("MONO_WEBHOOK_SECRET is not configured")
            return False

        if header_secret:
            return secrets_mod.compare_digest(str(header_secret), str(webhook_secret))

        if not signature:
            return False

        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return secrets_mod.compare_digest(str(signature), expected_signature)
    
    # Private helper methods using raw SQL
    async def _store_mono_account(self, user_id: uuid.UUID, account_id: str) -> bool:
        """Store Mono account ID for user"""
        query = """
            UPDATE users 
            SET plaid_access_token = $1, updated_at = $2
            WHERE id = $3
        """
        
        result = await db_service.execute_command(
            query, account_id, utc_now(), user_id
        )
        
        return "UPDATE 1" in result
    
    async def _get_user_mono_account(self, user_id: uuid.UUID) -> Optional[str]:
        """Get user's Mono account ID"""
        query = """
            SELECT plaid_access_token 
            FROM users 
            WHERE id = $1
        """
        
        result = await db_service.execute_one(query, user_id)
        return result['plaid_access_token'] if result else None
    
    async def _check_transaction_exists(self, external_id: str) -> bool:
        """Check if transaction with external ID already exists"""
        query = """
            SELECT id 
            FROM transactions 
            WHERE plaid_transaction_id = $1
            LIMIT 1
        """
        
        result = await db_service.execute_one(query, external_id)
        return result is not None
    
    async def _mark_account_reauth_required(self, account_id: str) -> bool:
        """Mark account as requiring reauthorization"""
        query = """
            UPDATE users 
            SET plaid_access_token = NULL, updated_at = $1
            WHERE plaid_access_token = $2
        """
        
        result = await db_service.execute_command(
            query, utc_now(), account_id
        )
        
        return "UPDATE" in result
    
    async def get_user_account_summary(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Get user's account summary with Mono data"""
        
        # Get user's Mono account
        account_id = await self._get_user_mono_account(user_id)
        if not account_id:
            return {"connected": False, "message": "No Mono account connected"}
        
        try:
            # Get account info and balance from Mono
            account_info = await self.get_account_info(account_id)
            balance_info = await self.get_account_balance(account_id)
            
            # Get transaction summary from our database
            tx_summary = await self.transaction_service.get_transaction_summary(
                user_id, currency="NGN"
            )
            
            return {
                "connected": True,
                "account": {
                    "name": account_info.get("name"),
                    "number": account_info.get("accountNumber"),
                    "bank": account_info.get("institution", {}).get("name"),
                    "type": account_info.get("type"),
                    "balance": float(Decimal(str(balance_info.get("balance", 0))) / Decimal("100")),
                    "currency": "NGN"
                },
                "transactions": tx_summary
            }
            
        except Exception as e:
            logger.error(f"Error getting account summary: {e}")
            return {
                "connected": True,
                "error": str(e),
                "message": "Connected but unable to fetch current data"
            }

# Nigerian Business Categories for CAC Compliance
NIGERIAN_BUSINESS_CATEGORIES = {
    # Revenue/Income Categories
    "sales_revenue": "Sales Revenue",
    "service_revenue": "Service Revenue", 
    "rental_income": "Rental Income",
    "interest_income": "Interest Income",
    "dividend_income": "Dividend Income",
    "other_income": "Other Income",
    
    # Cost of Goods Sold
    "cost_of_goods_sold": "Cost of Goods Sold",
    "raw_materials": "Raw Materials",
    "direct_labor": "Direct Labor",
    "manufacturing_overhead": "Manufacturing Overhead",
    
    # Operating Expenses
    "salaries_wages": "Salaries and Wages",
    "rent_expense": "Rent Expense",
    "utilities": "Utilities",
    "office_supplies": "Office Supplies",
    "marketing_advertising": "Marketing and Advertising",
    "professional_fees": "Professional Fees",
    "insurance": "Insurance",
    "depreciation": "Depreciation",
    "bank_charges": "Bank Charges",
    "transport_logistics": "Transport and Logistics",
    "communication": "Communication",
    "repairs_maintenance": "Repairs and Maintenance",
    "training_development": "Training and Development",
    "entertainment": "Entertainment",
    "travel_expenses": "Travel Expenses",
    
    # Tax-related
    "vat_payable": "VAT Payable",
    "withholding_tax": "Withholding Tax",
    "company_income_tax": "Company Income Tax",
    "personal_income_tax": "Personal Income Tax",
    
    # Assets
    "cash_bank": "Cash and Bank",
    "accounts_receivable": "Accounts Receivable",
    "inventory": "Inventory",
    "fixed_assets": "Fixed Assets",
    "investments": "Investments",
    
    # Liabilities
    "accounts_payable": "Accounts Payable",
    "loans_payable": "Loans Payable",
    "accrued_expenses": "Accrued Expenses",
    
    # Personal/Non-business
    "personal": "Personal (Non-business)"
}
