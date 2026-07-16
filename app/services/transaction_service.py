from typing import List, Optional, Dict, Any
from app.core.database import db_service
from app.services.ai_service import AIService
import uuid
from datetime import datetime, date
from decimal import Decimal

TX_COLUMNS = """
    id, user_id, plaid_transaction_id, merchant_name, amount,
    currency, transaction_date, raw_description, category,
    ai_confidence, status, source, vat_deductible, wht_applicable, wht_rate,
    created_at, updated_at
"""

class TransactionService:
    """Transaction service using raw SQL queries"""
    
    def __init__(self):
        self.ai_service = AIService()
    
    async def create_transaction(
        self,
        user_id: uuid.UUID,
        merchant_name: str,
        amount: float,
        description: str,
        transaction_date: date,
        currency: str = "NGN",
        plaid_transaction_id: Optional[str] = None,
        source: str = "bank",
        category: Optional[str] = None,
        vat_deductible: Optional[bool] = None,
        wht_applicable: Optional[bool] = None,
        wht_rate: Optional[float] = None,
        use_ai: bool = True,
    ) -> Dict[str, Any]:
        """Create a new transaction.

        Bank-synced entries use AI categorization when use_ai is True.
        Manual entries use the caller-provided category and land as confirmed.
        """
        is_manual = source == "manual"

        if is_manual:
            if not category:
                raise ValueError("Category is required for manual transactions")
            final_category = category
            ai_confidence = None
            status = "confirmed"
            final_vat = vat_deductible
            final_wht = wht_applicable
            final_wht_rate = Decimal(str(wht_rate)) if wht_applicable and wht_rate is not None else None
        elif use_ai:
            country = "NG" if currency == "NGN" else "US"
            ai_result = await self.ai_service.categorize_transaction(
                merchant_name=merchant_name,
                description=description,
                amount=amount,
                currency=currency,
                country=country
            )
            final_category = category or ai_result["category"]
            ai_confidence = ai_result["confidence"]
            status = "confirmed" if ai_result["confidence"] > 0.9 else "pending"
            final_vat = vat_deductible
            final_wht = wht_applicable
            final_wht_rate = Decimal(str(wht_rate)) if wht_rate is not None else None
        else:
            final_category = category or "Uncategorized"
            ai_confidence = None
            status = "pending"
            final_vat = vat_deductible
            final_wht = wht_applicable
            final_wht_rate = Decimal(str(wht_rate)) if wht_rate is not None else None
        
        transaction_id = uuid.uuid4()
        now = datetime.utcnow()
        
        query = f"""
            INSERT INTO transactions (
                id, user_id, plaid_transaction_id, merchant_name, amount,
                currency, transaction_date, raw_description, category,
                ai_confidence, status, source, vat_deductible, wht_applicable, wht_rate,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17
            ) RETURNING {TX_COLUMNS}
        """
        
        result = await db_service.execute_one(
            query,
            transaction_id, user_id, plaid_transaction_id, merchant_name,
            Decimal(str(amount)), currency, transaction_date, description,
            final_category, ai_confidence, status, source,
            final_vat, final_wht, final_wht_rate, now, now
        )
        
        return result
    
    async def get_user_transactions(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """Get transactions for a user with filtering"""
        
        conditions = ["user_id = $1"]
        params = [user_id]
        param_count = 2
        
        if status:
            conditions.append(f"status = ${param_count}")
            params.append(status)
            param_count += 1
        
        if category:
            conditions.append(f"category = ${param_count}")
            params.append(category)
            param_count += 1
        
        if start_date:
            conditions.append(f"transaction_date >= ${param_count}")
            params.append(start_date)
            param_count += 1
        
        if end_date:
            conditions.append(f"transaction_date <= ${param_count}")
            params.append(end_date)
            param_count += 1
        
        where_clause = " AND ".join(conditions)
        
        query = f"""
            SELECT {TX_COLUMNS}
            FROM transactions 
            WHERE {where_clause}
            ORDER BY transaction_date DESC, created_at DESC
            OFFSET ${param_count} LIMIT ${param_count + 1}
        """
        
        params.extend([skip, limit])
        
        return await db_service.execute_query(query, *params)
    
    async def get_transaction_by_id(
        self, 
        transaction_id: uuid.UUID, 
        user_id: Optional[uuid.UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """Get single transaction by ID"""
        
        if user_id:
            query = f"""
                SELECT {TX_COLUMNS}
                FROM transactions 
                WHERE id = $1 AND user_id = $2
            """
            return await db_service.execute_one(query, transaction_id, user_id)
        else:
            query = f"""
                SELECT {TX_COLUMNS}
                FROM transactions 
                WHERE id = $1
            """
            return await db_service.execute_one(query, transaction_id)
    
    async def update_transaction_status(
        self,
        transaction_id: uuid.UUID,
        status: Optional[str] = None,
        category: Optional[str] = None,
        vat_deductible: Optional[bool] = None,
        wht_applicable: Optional[bool] = None,
        wht_rate: Optional[float] = None,
        user_id: Optional[uuid.UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """Update transaction status, category, and tax flags"""
        
        updates = ["updated_at = $1"]
        params: List[Any] = [datetime.utcnow()]
        param_count = 2
        
        if status is not None:
            updates.append(f"status = ${param_count}")
            params.append(status)
            param_count += 1
        
        if category is not None:
            updates.append(f"category = ${param_count}")
            params.append(category)
            param_count += 1

        if vat_deductible is not None:
            updates.append(f"vat_deductible = ${param_count}")
            params.append(vat_deductible)
            param_count += 1

        if wht_applicable is not None:
            updates.append(f"wht_applicable = ${param_count}")
            params.append(wht_applicable)
            param_count += 1

        if wht_rate is not None or wht_applicable is False:
            updates.append(f"wht_rate = ${param_count}")
            if wht_applicable is False:
                params.append(None)
            elif wht_rate is not None:
                params.append(Decimal(str(wht_rate)))
            else:
                params.append(None)
            param_count += 1
        
        params.append(transaction_id)
        where_clause = f"id = ${param_count}"
        
        if user_id:
            param_count += 1
            params.append(user_id)
            where_clause += f" AND user_id = ${param_count}"
        
        query = f"""
            UPDATE transactions 
            SET {', '.join(updates)}
            WHERE {where_clause}
            RETURNING {TX_COLUMNS}
        """
        
        return await db_service.execute_one(query, *params)
    
    async def delete_transaction(
        self, 
        transaction_id: uuid.UUID, 
        user_id: uuid.UUID
    ) -> bool:
        """Delete a transaction"""
        query = """
            DELETE FROM transactions 
            WHERE id = $1 AND user_id = $2
        """
        
        result = await db_service.execute_command(query, transaction_id, user_id)
        return "DELETE 1" in result
    
    async def get_transaction_summary(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Get comprehensive transaction summary for dashboard"""
        
        # Main summary query
        summary_query = """
            SELECT 
                COUNT(*) as total_transactions,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_count,
                COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as confirmed_count,
                COUNT(CASE WHEN status = 'flagged' THEN 1 END) as flagged_count,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_income,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as total_expenses,
                SUM(amount) as net_amount,
                AVG(ai_confidence) as avg_confidence
            FROM transactions 
            WHERE user_id = $1
        """
        
        summary = await db_service.execute_one(summary_query, user_id)
        
        # Category breakdown
        category_query = """
            SELECT 
                category,
                COUNT(*) as transaction_count,
                SUM(amount) as total_amount,
                AVG(amount) as avg_amount,
                AVG(ai_confidence) as avg_confidence
            FROM transactions 
            WHERE user_id = $1 AND category IS NOT NULL
            GROUP BY category
            ORDER BY ABS(SUM(amount)) DESC
        """
        
        categories = await db_service.execute_query(category_query, user_id)
        
        # Monthly trends (last 12 months)
        monthly_query = """
            SELECT 
                DATE_TRUNC('month', transaction_date) as month,
                COUNT(*) as transaction_count,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as expenses,
                SUM(amount) as net
            FROM transactions 
            WHERE user_id = $1 
                AND transaction_date >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', transaction_date)
            ORDER BY month DESC
        """
        
        monthly_trends = await db_service.execute_query(monthly_query, user_id)
        
        # Recent transactions
        recent_query = """
            SELECT id, merchant_name, amount, currency, transaction_date,
                   category, status, source, ai_confidence
            FROM transactions 
            WHERE user_id = $1
            ORDER BY transaction_date DESC, created_at DESC
            LIMIT 10
        """
        
        recent_transactions = await db_service.execute_query(recent_query, user_id)
        
        return {
            "summary": summary,
            "categories": categories,
            "monthly_trends": monthly_trends,
            "recent_transactions": recent_transactions
        }
    
    async def bulk_update_categories(
        self, 
        user_id: uuid.UUID, 
        updates: List[Dict[str, Any]]
    ) -> int:
        """Bulk update transaction categories"""
        
        if not updates:
            return 0
        
        # Prepare bulk update using VALUES clause
        values_list = []
        params = []
        param_count = 1
        
        for update in updates:
            values_list.append(f"(${param_count}::uuid, ${param_count + 1}, ${param_count + 2})")
            params.extend([
                uuid.UUID(update['transaction_id']),
                update['category'],
                datetime.utcnow()
            ])
            param_count += 3
        
        values_clause = ", ".join(values_list)
        
        query = f"""
            UPDATE transactions 
            SET category = data.category,
                updated_at = data.updated_at
            FROM (VALUES {values_clause}) AS data(id, category, updated_at)
            WHERE transactions.id = data.id 
                AND transactions.user_id = ${param_count}
        """
        
        params.append(user_id)
        
        result = await db_service.execute_command(query, *params)
        
        # Extract number of updated rows
        if "UPDATE" in result:
            return int(result.split()[1])
        return 0
    
    async def get_spending_analytics(
        self,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Get detailed spending analytics for a date range"""
        
        query = """
            WITH daily_spending AS (
                SELECT 
                    transaction_date,
                    category,
                    SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as expenses,
                    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income,
                    COUNT(*) as transaction_count
                FROM transactions 
                WHERE user_id = $1 
                    AND transaction_date BETWEEN $2 AND $3
                GROUP BY transaction_date, category
            ),
            category_totals AS (
                SELECT 
                    category,
                    SUM(expenses) as total_expenses,
                    SUM(income) as total_income,
                    SUM(transaction_count) as total_transactions,
                    AVG(expenses) as avg_daily_expenses
                FROM daily_spending
                GROUP BY category
            ),
            daily_totals AS (
                SELECT 
                    transaction_date,
                    SUM(expenses) as daily_expenses,
                    SUM(income) as daily_income,
                    SUM(transaction_count) as daily_transactions
                FROM daily_spending
                GROUP BY transaction_date
                ORDER BY transaction_date
            )
            SELECT 
                'category_breakdown' as type,
                json_agg(
                    json_build_object(
                        'category', category,
                        'total_expenses', total_expenses,
                        'total_income', total_income,
                        'total_transactions', total_transactions,
                        'avg_daily_expenses', avg_daily_expenses
                    )
                ) as data
            FROM category_totals
            
            UNION ALL
            
            SELECT 
                'daily_trends' as type,
                json_agg(
                    json_build_object(
                        'date', transaction_date,
                        'expenses', daily_expenses,
                        'income', daily_income,
                        'transactions', daily_transactions
                    ) ORDER BY transaction_date
                ) as data
            FROM daily_totals
        """
        
        results = await db_service.execute_query(query, user_id, start_date, end_date)
        
        # Process results into structured format
        analytics = {}
        for result in results:
            analytics[result['type']] = result['data']
        
        return analytics
