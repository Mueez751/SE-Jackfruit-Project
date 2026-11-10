from fastapi import APIRouter, HTTPException, Query, Request, status
from typing import Optional
from app.models import IssueRequest
from app.services.issue_service import (
    issue_blood_units_for_request, get_issue_certificate, list_issue_transactions
)

router = APIRouter(prefix="/api/issues", tags=["Issues & Dispatch"])

@router.post("", status_code=status.HTTP_201_CREATED)
def issue_units(payload: IssueRequest, request: Request):
    """
    Issue blood units for an approved request (BBMS-F-013, BBMS-F-014, BBMS-F-015).
    Blocks issue of expired, quarantined, or unavailable units.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error, issued_records = issue_blood_units_for_request(
        request_id=payload.request_id,
        verification_notes=payload.verification_notes or "Standard pre-transfusion crossmatch verified.",
        actor_username="staff",
        ip_address=client_ip
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {
        "message": f"Successfully issued {len(issued_records)} blood unit(s).",
        "request_id": payload.request_id,
        "issued_records": issued_records
    }

@router.get("")
def get_issues(
    hospital: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Searchable & filterable issue transactions (BBMS-F-014, BBMS-F-016)."""
    return list_issue_transactions(query=search, hospital=hospital)

@router.get("/{issue_id}/certificate")
def get_certificate(issue_id: str):
    """Retrieve printable issue certificate / dispatch voucher (BBMS-F-014)."""
    cert = get_issue_certificate(issue_id)
    if not cert:
        raise HTTPException(status_code=404, detail=f"Issue certificate {issue_id} not found.")
    return cert
