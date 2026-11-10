from fastapi import APIRouter, HTTPException, Request, status
from typing import Optional, List
from app.models import AllocateRequest
from app.services.allocation_service import (
    preview_fefo_candidates, allocate_units_fefo, release_allocation
)

router = APIRouter(prefix="/api/allocations", tags=["Allocations"])

@router.get("/preview/{request_id}")
def preview_fefo(request_id: str):
    """Preview candidate blood units matching request via FEFO ordering (BBMS-F-012)."""
    success, error, candidates = preview_fefo_candidates(request_id)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {
        "request_id": request_id,
        "candidate_count": len(candidates),
        "candidates": candidates
    }

@router.post("/allocate", status_code=status.HTTP_200_OK)
def allocate_units(payload: AllocateRequest, request: Request):
    """
    Allocate available eligible blood units to approved request using FEFO (BBMS-F-012).
    Updates inventory atomically (BBMS-F-015).
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error, allocated_ids = allocate_units_fefo(
        request_id=payload.request_id,
        selected_unit_ids=payload.selected_unit_ids,
        actor_username="staff",
        ip_address=client_ip
    )
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {
        "message": f"Successfully allocated {len(allocated_ids)} unit(s) via FEFO strategy.",
        "request_id": payload.request_id,
        "allocated_unit_ids": allocated_ids
    }

@router.post("/release")
def release_unit(request_id: str, unit_id: str, request: Request):
    """Release an allocated unit back to Available inventory."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    success, error = release_allocation(request_id, unit_id, actor_username="staff", ip_address=client_ip)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"message": f"Unit {unit_id} released from request {request_id}."}
