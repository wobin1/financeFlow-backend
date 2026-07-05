from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.api_v1.api import api_router
from app.core.database import startup_db, shutdown_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await startup_db()
    yield
    # Shutdown
    await shutdown_db()

app = FastAPI(
    title="FinanceFlow API",
    description="Intelligent bookkeeping automation for Nigerian businesses",
    version="2.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "message": "FinanceFlow API - Raw SQL Version",
        "version": "2.0.0",
        "description": "Intelligent bookkeeping automation for Nigerian businesses",
        "features": [
            "Raw SQL queries for better performance",
            "Async database operations with connection pooling",
            "AI-powered transaction categorization",
            "Mono banking integration for Nigerian banks",
            "CAC-compliant business categories"
        ]
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
