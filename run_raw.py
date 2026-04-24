#!/usr/bin/env python3
"""
Run FinanceFlow with Raw SQL implementation
"""

import uvicorn
from app.main import app

if __name__ == "__main__":
    print("🚀 Starting FinanceFlow API with Raw SQL...")
    print("📊 Features:")
    print("  - Raw SQL queries for better performance")
    print("  - Async database operations with connection pooling")
    print("  - AI-powered transaction categorization")
    print("  - Mono banking integration for Nigerian banks")
    print("  - CAC-compliant business categories")
    print()
    print("🌐 API will be available at: http://localhost:8000")
    print("📚 API docs will be available at: http://localhost:8000/docs")
    print()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
