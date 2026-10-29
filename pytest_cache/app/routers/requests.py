from fastapi import APIRouter, HTTPException, Query, Request, status
from typing import Optional
from app.models import BloodRequestCreate, BloodRequestDecision
from app.services.request_service import (
    create_blood_request, record_request_decision,
    get_blood_request, list_blood_requests
)

router = APIRouter(prefix="/api/requests", tags=["Blood Requests"])

@router.post("", status_code=status.HTTP_201_CREATED)
def submit_blood_request(payload: BloodRequestCreate, request: Request):
    """Create blood request with validation and priority (BBMS-F-009, BBMS-F-010)."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error, req_id = create_blood_request(
        hospital_name=payload.hospital_name,
        requester_name=payload.requester_name,
        patient_name=payload.patient_name,
        patient_blood_group=payload.patient_blood_group,
        component_type=payload.component_type,
        quantity=payload.quantity,
        urgency=payload.urgency,
        required_date=payload.required_date,
        actor_username="hospital",
        ip_address=client_ip
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {
        "message": "Blood request submitted successfully.",
        "request_id": req_id
    }

@router.get("")
def get_requests(
    status: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    hospital: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Searchable & filterable requests ordered by urgency (BBMS-F-016)."""
    return list_blood_requests(
        status=status,
        urgency=urgency,
        hospital=hospital,
        query=search
    )

@router.get("/{request_id}")
def get_single_request(request_id: str):
    req = get_blood_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found.")
    return req

@router.post("/{request_id}/decision")
def make_request_decision(request_id: str, payload: BloodRequestDecision, request: Request):
    """Approve, reject, or place on hold a blood request (BBMS-F-011)."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error = record_request_decision(
        request_id=request_id,
        decision=payload.decision,
        reason=payload.reason,
        actor_username="staff",
        ip_address=client_ip
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"message": f"Request {request_id} decision recorded as {payload.decision}."}
