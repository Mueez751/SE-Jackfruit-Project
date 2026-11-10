from fastapi import APIRouter, HTTPException, Request, status
from app.models import CollectionCreate
from app.services.inventory_service import record_collection_and_create_unit

router = APIRouter(prefix="/api/collections", tags=["Blood Collections"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionCreate, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error, data = record_collection_and_create_unit(
        donor_id=payload.donor_id,
        blood_group=payload.blood_group,
        volume_ml=payload.volume_ml,
        component_type=payload.component_type,
        collection_dt=payload.collection_date,
        actor_username="staff",
        ip_address=client_ip
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {
        "message": "Blood collection recorded and blood unit created successfully.",
        "data": data
    }
