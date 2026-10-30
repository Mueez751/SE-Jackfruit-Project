from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Optional
from app.services.report_service import (
    generate_inventory_report, generate_donations_report,
    generate_issues_report, generate_discards_and_expiries_report,
    export_report_to_csv
)
from app.routers.auth import require_roles

router = APIRouter(prefix="/api/reports", tags=["Reports"])

@router.get("/inventory")
def report_inventory(current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Generate aggregate inventory report. Staff and Admin only."""
    return generate_inventory_report()

@router.get("/donations")
def report_donations(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    current_user: dict = Depends(require_roles(["staff", "admin"]))
):
    """Generate donations audit report. Staff and Admin only."""
    return generate_donations_report(from_date=from_date, to_date=to_date)

@router.get("/issues")
def report_issues(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    current_user: dict = Depends(require_roles(["staff", "admin"]))
):
    """Generate blood issues report. Staff and Admin only."""
    return generate_issues_report(from_date=from_date, to_date=to_date)

@router.get("/discards-expiries")
def report_discards_expiries(current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Generate discard and expiry report. Staff and Admin only."""
    return generate_discards_and_expiries_report()

@router.get("/export-csv")
def export_csv(
    report_type: str = Query(..., description="inventory, donations, issues, or discards_expiries"),
    current_user: dict = Depends(require_roles(["staff", "admin"]))
):
    """Export report to CSV format. Staff and Admin only."""
    csv_data = export_report_to_csv(report_type)
    filename = f"bbms_report_{report_type}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
