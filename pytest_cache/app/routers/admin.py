from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from typing import Optional
from app.models import UserCreate, UserStatusUpdate
from app.services.auth_service import list_users, create_user, set_user_status
from app.services.audit_service import list_audit_logs
from app.routers.auth import require_roles

router = APIRouter(prefix="/api/admin", tags=["Administration & Audit"])

@router.get("/users")
def get_all_users(current_user: dict = Depends(require_roles(["admin"]))):
    """List system users and their assigned roles (BBMS-F-019). Administrator only."""
    return list_users()

@router.post("/users", status_code=status.HTTP_201_CREATED)
def add_user(payload: UserCreate, request: Request, current_user: dict = Depends(require_roles(["admin"]))):
    """Administrator creates system user and assigns role (BBMS-F-019)."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        user_id = create_user(
            username=payload.username,
            password=payload.password,
            full_name=payload.full_name,
            email=payload.email,
            role=payload.role,
            actor_username=current_user["username"],
            ip_address=client_ip
        )
        return {"user_id": user_id, "message": f"User '{payload.username}' created successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/users/{user_id}/status")
def toggle_user_status(user_id: int, payload: UserStatusUpdate, request: Request, current_user: dict = Depends(require_roles(["admin"]))):
    """Administrator modifies user activation status (BBMS-F-019)."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        set_user_status(user_id, payload.status, actor_username=current_user["username"], ip_address=client_ip)
        return {"message": f"User {user_id} status updated to {payload.status}."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/audit-logs")
def get_audit_trail(
    actor: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(require_roles(["admin"]))
):
    """Query tamper-evident audit logs with multi-parameter filtering (BBMS-F-020). Administrator only."""
    return list_audit_logs(actor=actor, action=action, entity_type=entity_type, limit=limit)
