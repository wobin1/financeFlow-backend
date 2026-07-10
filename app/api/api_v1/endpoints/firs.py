from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from datetime import datetime
from typing import Optional

from app.api.api_v1.endpoints.auth import get_current_user
from app.core.utils import ensure_uuid
from app.services.firs_service import FirsService

router = APIRouter()


@router.get("/prep")
async def get_firs_filing_prep(
    current_user: dict = Depends(get_current_user),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
):
    """Generate VAT, WHT, and CIT prep worksheets for a filing period."""
    now = datetime.utcnow()
    filing_year = year or now.year
    filing_month = month or now.month

    service = FirsService()
    try:
        return await service.get_filing_prep(
            user_id=ensure_uuid(current_user["id"]),
            year=filing_year,
            month=filing_month,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate FIRS prep data: {str(e)}",
        )


@router.get("/export")
async def export_firs_prep_csv(
    current_user: dict = Depends(get_current_user),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
):
    """Download FIRS prep worksheet as CSV."""
    now = datetime.utcnow()
    filing_year = year or now.year
    filing_month = month or now.month

    service = FirsService()
    try:
        csv_content = await service.export_csv(
            user_id=ensure_uuid(current_user["id"]),
            year=filing_year,
            month=filing_month,
        )
        filename = f"firs-prep-{filing_year}-{filing_month:02d}.csv"
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export FIRS prep data: {str(e)}",
        )
