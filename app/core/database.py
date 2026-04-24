import asyncpg
import asyncio
from typing import Dict, List, Any, Optional
from contextlib import asynccontextmanager
from app.core.config import settings
import uuid
from datetime import datetime, date
import json

class DatabaseService:
    """Raw SQL database service using asyncpg for better performance"""
    
    def __init__(self):
        self.pool = None
    
    async def init_pool(self):
        """Initialize connection pool"""
        if not self.pool:
            self.pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
    
    async def close_pool(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool"""
        if not self.pool:
            await self.init_pool()
        
        async with self.pool.acquire() as conn:
            yield conn
    
    async def execute_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute SELECT query and return results as list of dicts"""
        async with self.get_connection() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def execute_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute SELECT query and return single result"""
        async with self.get_connection() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def execute_command(self, query: str, *args) -> str:
        """Execute INSERT/UPDATE/DELETE and return status"""
        async with self.get_connection() as conn:
            return await conn.execute(query, *args)
    
    async def execute_transaction(self, queries: List[tuple]) -> bool:
        """Execute multiple queries in a transaction"""
        async with self.get_connection() as conn:
            async with conn.transaction():
                try:
                    for query, args in queries:
                        await conn.execute(query, *args)
                    return True
                except Exception as e:
                    print(f"Transaction failed: {e}")
                    return False

# Global database service instance
db_service = DatabaseService()

# Startup and shutdown events
async def startup_db():
    await db_service.init_pool()

async def shutdown_db():
    await db_service.close_pool()
