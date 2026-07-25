from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.api_v1.api import api_router
from app.core.database import db_service, startup_db, shutdown_db
from app.core.errors import unhandled_exception_handler
from app.core.logging_utils import CorrelationIdMiddleware, configure_logging

configure_logging()


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
    lifespan=lifespan,
)

app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_middleware(CorrelationIdMiddleware)

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
            "CAC-compliant business categories",
        ],
    }


@app.get("/health")
async def health_check():
    try:
        row = await db_service.execute_one("SELECT 1 AS ok")
        if not row or row.get("ok") != 1:
            return {"status": "unhealthy", "database": "unexpected_response"}
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return {"status": "unhealthy", "database": "disconnected"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
