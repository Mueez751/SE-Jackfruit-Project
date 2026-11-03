from fastapi import APIRouter, Depends, HTTPException, status
from app.services.auth_service import authenticate_user
from app.seed_data import seed_database
from app.routers.auth import require_roles
from app.config import is_demo_mode_enabled

router = APIRouter(prefix="/api/demo", tags=["Demo Utilities"])

DEMO_CREDENTIALS = {
    "admin": ("admin", "admin123"),
    "staff": ("staff", "staff123"),
    "hospital": ("hospital", "hospital123"),
    "donor": ("donor", "donor123"),
}

@router.post("/switch-role")
def switch_demo_role(role: str):
    """Convenience utility for evaluators to obtain demo sessions for UI evaluation."""
    if not is_demo_mode_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo role switching is disabled. Set environment variable BBMS_ENABLE_DEMO=true to enable."
        )
    if role not in DEMO_CREDENTIALS:
        raise HTTPException(status_code=400, detail=f"Unknown demo role: {role}")
    u, pw = DEMO_CREDENTIALS[role]
    session = authenticate_user(u, pw)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication failed for demo role.")
    return {
        "message": f"Switched to {role.upper()} session.",
        "session": session
    }

@router.post("/reset")
def reset_demo_database(current_user: dict = Depends(require_roles(["admin"]))):
    """Reset database to initial pristine seed state. Restricted to Administrator role."""
    seed_database(force=True)
    return {"message": "Database reset to initial seed data successfully."}
