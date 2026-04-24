import google.generativeai as genai
from typing import Optional, Dict, Any
from app.core.config import settings
import json
import re

class AIService:
    """AI service for transaction categorization using Google Gemini"""
    
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-2.0-flash')
    
    async def categorize_transaction(
        self,
        merchant_name: str,
        description: str,
        amount: float,
        country: str = "NG"
    ) -> Dict[str, Any]:
        """Categorize a transaction using AI"""
        
        # Country-specific categories
        if country == "NG":
            categories = [
                "Office Supplies",
                "Professional Services",
                "Transportation",
                "Utilities",
                "Rent/Lease",
                "Insurance",
                "Marketing",
                "Travel",
                "Equipment",
                "Meals/Entertainment",
                "Taxes",
                "Salaries",
                "Inventory",
                "Bank Charges"
            ]
        else:
            categories = [
                "Office Supplies",
                "Professional Services",
                "Transportation",
                "Utilities",
                "Rent/Lease",
                "Insurance",
                "Marketing",
                "Travel",
                "Equipment",
                "Meals/Entertainment",
                "Taxes",
                "Salaries",
                "Inventory",
                "Bank Charges"
            ]
        
        prompt = f"""Categorize this business transaction:
        
Merchant: {merchant_name}
Description: {description}
Amount: {amount}
Country: {country}

Available categories: {', '.join(categories)}

Respond ONLY with a JSON object in this exact format:
{{"category": "Category Name", "confidence": 0.95, "reasoning": "Brief explanation"}}

Rules:
1. Select the most appropriate category from the list
2. Confidence should be between 0.0 and 1.0
3. Keep reasoning under 100 characters
"""
        
        try:
            response = await self.model.generate_content_async(prompt)
            
            # Extract JSON from response
            text = response.text
            json_match = re.search(r'\{[^}]+\}', text)
            
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "category": result.get("category", "Uncategorized"),
                    "confidence": result.get("confidence", 0.5),
                    "reasoning": result.get("reasoning", ""),
                    "ai_processed": True
                }
            
            # Fallback if no JSON found
            return {
                "category": "Uncategorized",
                "confidence": 0.0,
                "reasoning": "Failed to parse AI response",
                "ai_processed": False
            }
            
        except Exception as e:
            print(f"AI categorization error: {e}")
            return {
                "category": "Uncategorized",
                "confidence": 0.0,
                "reasoning": str(e),
                "ai_processed": False
            }
    
    async def extract_receipt_data(self, receipt_text: str) -> Dict[str, Any]:
        """Extract structured data from receipt text"""
        
        prompt = f"""Extract information from this receipt:

{receipt_text}

Respond with JSON in this format:
{{
    "merchant_name": "Store Name",
    "date": "YYYY-MM-DD",
    "total_amount": 99.99,
    "items": [
        {{"name": "Item Name", "price": 10.00, "quantity": 1}}
    ],
    "category": "Category Name"
}}

Extract only what you can find. Use null for missing values."""
        
        try:
            response = await self.model.generate_content_async(prompt)
            text = response.text
            json_match = re.search(r'\{[^}]+\}', text, re.DOTALL)
            
            if json_match:
                return json.loads(json_match.group())
            
            return {"error": "Could not extract data", "raw_text": receipt_text}
            
        except Exception as e:
            print(f"Receipt extraction error: {e}")
            return {"error": str(e), "raw_text": receipt_text}

    def categorize_batch(self, transactions: list) -> list:
        """Categorize multiple transactions (synchronous for batch processing)"""
        results = []
        for tx in transactions:
            # Use synchronous version for batch processing
            result = self._categorize_sync(
                tx.get('merchant_name', ''),
                tx.get('description', ''),
                tx.get('amount', 0),
                tx.get('country', 'NG')
            )
            results.append(result)
        return results
    
    def _categorize_sync(self, merchant_name: str, description: str, amount: float, country: str = "NG") -> Dict[str, Any]:
        """Synchronous version for batch processing"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, return default
                return {
                    "category": "Uncategorized",
                    "confidence": 0.0,
                    "ai_processed": False
                }
        except RuntimeError:
            pass
        
        # Run async method synchronously
        return asyncio.run(self.categorize_transaction(merchant_name, description, amount, country))
