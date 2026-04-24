from typing import Optional, Dict, Any
from app.core.database import db_service
from app.core.security import get_password_hash, verify_password
import uuid
from datetime import datetime

class UserService:
    """User service using raw SQL queries"""
    
    async def create_user(
        self,
        email: str,
        full_name: str,
        password: str,
        phone_number: Optional[str] = None,
        business_name: Optional[str] = None,
        cac_number: Optional[str] = None,
        tin_number: Optional[str] = None,
        business_type: Optional[str] = None,
        country: str = "NG",
        currency: str = "NGN"
    ) -> Dict[str, Any]:
        """Create a new user"""
        
        # Check if user already exists
        existing_user = await self.get_user_by_email(email)
        if existing_user:
            raise ValueError("Email already registered")
        
        user_id = uuid.uuid4()
        hashed_password = get_password_hash(password)
        
        query = """
            INSERT INTO users (
                id, email, full_name, hashed_password, phone_number,
                business_name, cac_number, tin_number, business_type,
                country, currency, is_active, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
            ) RETURNING id, email, full_name, phone_number, business_name,
                       cac_number, tin_number, business_type, country, 
                       currency, is_active, created_at
        """
        
        now = datetime.utcnow()
        result = await db_service.execute_one(
            query,
            user_id, email, full_name, hashed_password, phone_number,
            business_name, cac_number, tin_number, business_type,
            country, currency, True, now, now
        )
        
        return result
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        query = """
            SELECT id, email, full_name, hashed_password, phone_number,
                   business_name, cac_number, tin_number, business_type,
                   country, currency, is_active, plaid_access_token,
                   created_at, updated_at
            FROM users 
            WHERE email = $1
        """
        
        return await db_service.execute_one(query, email)
    
    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        query = """
            SELECT id, email, full_name, phone_number, business_name,
                   cac_number, tin_number, business_type, country, 
                   currency, is_active, plaid_access_token,
                   created_at, updated_at
            FROM users 
            WHERE id = $1
        """
        
        return await db_service.execute_one(query, user_id)
    
    async def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user with email and password"""
        user = await self.get_user_by_email(email)
        
        if not user or not verify_password(password, user['hashed_password']):
            return None
        
        # Remove password from returned data
        user_data = {k: v for k, v in user.items() if k != 'hashed_password'}
        return user_data
    
    async def update_user(
        self,
        user_id: uuid.UUID,
        full_name: Optional[str] = None,
        phone_number: Optional[str] = None,
        business_name: Optional[str] = None,
        cac_number: Optional[str] = None,
        tin_number: Optional[str] = None,
        business_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Update user information"""
        
        # Build dynamic update query
        updates = []
        params = []
        param_count = 1
        
        if full_name is not None:
            updates.append(f"full_name = ${param_count}")
            params.append(full_name)
            param_count += 1
        
        if phone_number is not None:
            updates.append(f"phone_number = ${param_count}")
            params.append(phone_number)
            param_count += 1
        
        if business_name is not None:
            updates.append(f"business_name = ${param_count}")
            params.append(business_name)
            param_count += 1
        
        if cac_number is not None:
            updates.append(f"cac_number = ${param_count}")
            params.append(cac_number)
            param_count += 1
        
        if tin_number is not None:
            updates.append(f"tin_number = ${param_count}")
            params.append(tin_number)
            param_count += 1
        
        if business_type is not None:
            updates.append(f"business_type = ${param_count}")
            params.append(business_type)
            param_count += 1
        
        if not updates:
            return await self.get_user_by_id(user_id)
        
        updates.append(f"updated_at = ${param_count}")
        params.append(datetime.utcnow())
        param_count += 1
        
        params.append(user_id)
        
        query = f"""
            UPDATE users 
            SET {', '.join(updates)}
            WHERE id = ${param_count}
            RETURNING id, email, full_name, phone_number, business_name,
                     cac_number, tin_number, business_type, country, 
                     currency, is_active, created_at, updated_at
        """
        
        return await db_service.execute_one(query, *params)
    
    async def update_plaid_token(self, user_id: uuid.UUID, access_token: str) -> bool:
        """Update user's Plaid/Mono access token"""
        query = """
            UPDATE users 
            SET plaid_access_token = $1, updated_at = $2
            WHERE id = $3
        """
        
        result = await db_service.execute_command(
            query, access_token, datetime.utcnow(), user_id
        )
        
        return "UPDATE 1" in result
    
    async def deactivate_user(self, user_id: uuid.UUID) -> bool:
        """Deactivate user account"""
        query = """
            UPDATE users 
            SET is_active = false, updated_at = $1
            WHERE id = $2
        """
        
        result = await db_service.execute_command(
            query, datetime.utcnow(), user_id
        )
        
        return "UPDATE 1" in result
