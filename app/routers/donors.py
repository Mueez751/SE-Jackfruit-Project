# BBMS-F-016: Searchable and Filterable Donor Registry - Assigned to Nandan Kumar K R
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from typing import Optional, List
from app.models import DonorCreate, EligibilityCheckRequest
from app.services.donor_service import (
    register_donor, evaluate_and_record_eligibility,
    get_donor, list_donors, get_donor_donation_history,
    get_donor_by_email, get_donor_screening_history,
    get_donor_donation_interval_status, get_full_donor_history,
    AmbiguousDonorEmailError
)
from app.routers.auth import require_roles, get_current_active_user

router = APIRouter(prefix="/api/donors", tags=["Donors"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_donor(payload: DonorCreate, request: Request, current_user: dict = Depends(require_roles(["staff", "admin"]))):
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
            actor_username=current_user["username"],
            ip_address=client_ip
        )
        return {"donor_id": donor_id, "message": "Donor registered successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("")
def get_donors(
    search: Optional[str] = Query(None, description="Search by name, ID, phone, or email"),
    blood_group: Optional[str] = Query(None, description="Filter by blood group"),
    gender: Optional[str] = Query(None, description="Filter by gender (Male, Female, Other)"),
    current_user: dict = Depends(require_roles(["staff", "admin"]))
):
    """Searchable & filterable donor directory (BBMS-F-016). Staff and Admin only."""
    return list_donors(query=search, blood_group=blood_group, gender=gender)

@router.get("/me/history")
def get_my_donor_history(current_user: dict = Depends(get_current_active_user)):
    """Allows authenticated donors to view their own donation history, screening outcomes, and interval status (BBMS-F-003)."""
    email = current_user.get("email")
    if not email or not isinstance(email, str) or not email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user account has no associated email address."
        )

    try:
        donor = get_donor_by_email(email)
    except AmbiguousDonorEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Multiple donor profiles are linked to this email address. Please contact blood bank staff to resolve account ambiguity."
        )

    if not donor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No donor profile linked to current user account."
        )

    history = get_full_donor_history(donor["donor_id"])
    return history

@router.get("/{donor_id}")
def get_single_donor(donor_id: str, current_user: dict = Depends(require_roles(["staff", "admin"]))):
    donor = get_donor(donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Donor {donor_id} not found.")
    return donor

@router.post("/{donor_id}/eligibility")
def check_donor_eligibility(donor_id: str, payload: EligibilityCheckRequest, request: Request, current_user: dict = Depends(require_roles(["staff", "admin"]))):
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
        actor_username=current_user["username"],
        ip_address=client_ip
    )
    return {
        "donor_id": donor_id,
        "is_eligible": is_eligible,
        "rejection_reasons": reasons,
        "message": "Donor is eligible for donation." if is_eligible else "Donor is currently ineligible for blood donation."
    }

@router.get("/{donor_id}/history")
def get_donor_history(donor_id: str, current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Enables staff/admin to view comprehensive donor history, screening outcomes, and donation intervals (BBMS-F-003)."""
    donor = get_donor(donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Donor {donor_id} not found.")
    return get_full_donor_history(donor_id)

@router.get("/{donor_id}/screening")
def get_donor_screening(donor_id: str, current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Allows staff/admin to view past screening outcomes and clinical vitals (BBMS-F-003)."""
    donor = get_donor(donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Donor {donor_id} not found.")
    return {
        "donor_id": donor_id,
        "full_name": donor["full_name"],
        "screening_outcomes": get_donor_screening_history(donor_id)
    }

@router.get("/{donor_id}/intervals")
def get_donor_intervals(donor_id: str, current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Allows staff/admin to check donation intervals and next eligible donation date (BBMS-F-003)."""
    donor = get_donor(donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Donor {donor_id} not found.")
    return {
        "donor_id": donor_id,
        "full_name": donor["full_name"],
        "interval_status": get_donor_donation_interval_status(donor_id)
    }
