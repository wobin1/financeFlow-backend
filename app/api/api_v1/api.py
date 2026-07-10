from fastapi import APIRouter

from app.api.api_v1.endpoints import auth, users, transactions, mono, firs

api_router = APIRouter()

# Include all raw SQL endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_router.include_router(mono.router, prefix="/mono", tags=["mono-banking"])
api_router.include_router(firs.router, prefix="/firs", tags=["firs-filing"])
