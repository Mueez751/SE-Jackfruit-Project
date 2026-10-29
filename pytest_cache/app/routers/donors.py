from fastapi import APIRouter, HTTPException, Query, Request, status
from typing import Optional, List
from app.models import DonorCreate, EligibilityCheckRequest
from app.services.donor_service import (
    register_donor, evaluate_and_record_eligibility,
    get_donor, list_donors, get_donor_donation_history
)

router = APIRouter(prefix="/api/donors", tags=["Donors"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_donor(payload: DonorCreate, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        donor_id = register_donor(
            full_name=payload.full_name,
            age=payload.age,
            gender=payload.gender,
            blood_group=payload.blood_group,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
            medical_remarks=payload.medical_remarks,
            actor_username="staff",
            ip_address=client_ip
        )
        return {"donor_id": donor_id, "message": "Donor registered successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("")
def get_donors(
    search: Optional[str] = Query(None, description="Search by name, ID, or phone"),
    blood_group: Optional[str] = Query(None, description="Filter by blood group")
):
    return list_donors(query=search, blood_group=blood_group)

@router.get("/{donor_id}")
def get_single_donor(donor_id: str):
    donor = get_donor(donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Donor {donor_id} not found.")
    return donor

@router.post("/{donor_id}/eligibility")
def check_donor_eligibility(donor_id: str, payload: EligibilityCheckRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    is_eligible, reasons = evaluate_and_record_eligibility(
        donor_id=donor_id,
        weight_kg=payload.weight_kg,
        hemoglobin_g_dl=payload.hemoglobin_g_dl,
        systolic_bp=payload.systolic_bp,
        diastolic_bp=payload.diastolic_bp,
        pulse=payload.pulse,
        days_since_last_donation=payload.days_since_last_donation,
        medical_flags=payload.medical_flags,
        actor_username="staff",
        ip_address=client_ip
    )
    return {
        "donor_id": donor_id,
        "is_eligible": is_eligible,
        "rejection_reasons": reasons,
        "message": "Donor is eligible for donation." if is_eligible else "Donor is currently ineligible for blood donation."
    }

@router.get("/{donor_id}/history")
def get_donor_history(donor_id: str):
    donor = get_donor(donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Donor {donor_id} not found.")
    history = get_donor_donation_history(donor_id)
    return {
        "donor_id": donor_id,
        "full_name": donor["full_name"],
        "blood_group": donor["blood_group"],
        "total_donations": len(history),
        "history": history
    }
