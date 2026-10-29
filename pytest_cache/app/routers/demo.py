from fastapi import APIRouter
from app.services.auth_service import authenticate_user
from app.seed_data import seed_database

router = APIRouter(prefix="/api/demo", tags=["Demo Utilities"])

DEMO_CREDENTIALS = {
    "admin": ("admin", "admin123"),
    "staff": ("staff", "staff123"),
    "hospital": ("hospital", "hospital123"),
    "donor": ("donor", "donor123"),
}

@router.post("/switch-role")
def switch_demo_role(role: str):
    """Convenience utility for evaluators to switch roles with a single click."""
    if role not in DEMO_CREDENTIALS:
        return {"error": f"Unknown demo role: {role}"}
    u, pw = DEMO_CREDENTIALS[role]
    session = authenticate_user(u, pw)
    return {
        "message": f"Switched to {role.upper()} session.",
        "session": session
    }

@router.post("/reset")
def reset_demo_database():
    """Reset database to initial pristine seed state."""
    seed_database(force=True)
    return {"message": "Database reset to initial seed data successfully."}
