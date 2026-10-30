from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from typing import Optional
from app.models import UnitStatusUpdate
from app.services.inventory_service import (
    get_inventory_summary, list_blood_units, update_unit_status, auto_mark_expired_units
)
from app.routers.auth import get_current_active_user, require_roles

router = APIRouter(prefix="/api/inventory", tags=["Inventory"])

@router.get("/summary")
def get_summary(current_user: dict = Depends(get_current_active_user)):
    """Maintain current inventory counts by blood group, component and status (BBMS-F-006). All authenticated users."""
    return get_inventory_summary()

@router.get("/units")
def get_units(
    blood_group: Optional[str] = Query(None),
    component_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(require_roles(["staff", "admin"]))
):
    """Searchable & filterable inventory units (BBMS-F-016). Staff and Admin only."""
    return list_blood_units(
        blood_group=blood_group,
        component_type=component_type,
        status=status,
        query=search
    )

@router.patch("/units/{unit_id}/status")
def change_unit_status(
    unit_id: str,
    payload: UnitStatusUpdate,
    request: Request,
    current_user: dict = Depends(require_roles(["staff", "admin"]))
):
    """Quarantine, release, or discard a blood unit with reason & audit (BBMS-F-008). Staff and Admin only."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error = update_unit_status(
        unit_id=unit_id,
        new_status=payload.status,
        reason=payload.reason,
        actor_username=current_user["username"],
        ip_address=client_ip
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"message": f"Blood unit {unit_id} status updated to {payload.status}."}

@router.post("/check-expiry")
def trigger_expiry_scan(current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Trigger automated scan to decommission expired units (BBMS-F-007). Staff and Admin only."""
    expired_count = auto_mark_expired_units()
    return {
        "message": f"Expiry check complete. {expired_count} unit(s) newly marked as Expired.",
        "expired_count": expired_count
    }
