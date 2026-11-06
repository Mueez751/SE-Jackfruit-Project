from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from typing import Optional, List
from app.models import UserLogin
from app.services.auth_service import authenticate_user, get_current_user_from_token, logout_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

def get_session_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Retrieve session user from Authorization header if present, or None."""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    return get_current_user_from_token(token)

def get_current_active_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    FastAPI dependency to extract and validate Bearer token.
    Accepts only properly formatted 'Authorization: Bearer <token>' headers.
    Returns authenticated user session dictionary or raises HTTP 401 Unauthorized.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported authorization scheme or invalid header format. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_current_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def require_roles(allowed_roles: List[str]):
    """
    FastAPI dependency factory enforcing Role-Based Access Control (RBAC).
    Returns a dependency callable that checks if the authenticated user has one of allowed_roles.
    Raises HTTP 403 Forbidden if the user's role is not authorized.
    """
    def role_dependency(current_user: dict = Depends(get_current_active_user)) -> dict:
        user_role = current_user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: role '{user_role}' is not authorized for this resource."
            )
        return current_user
    return role_dependency

@router.post("/login")
def login(payload: UserLogin, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    session = authenticate_user(payload.username, payload.password, ip_address=client_ip)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username, incorrect password, or account deactivated."
        )
    return {
        "token": session["token"],
        "user": {
            "id": session["user_id"],
            "username": session["username"],
            "full_name": session["full_name"],
            "email": session["email"],
            "role": session["role"]
        }
    }

@router.post("/logout")
def logout(request: Request, current_user: dict = Depends(get_current_active_user)):
    client_ip = request.client.host if request.client else "127.0.0.1"
    logout_user(current_user["token"], ip_address=client_ip)
    return {"message": "Logged out successfully."}

@router.get("/me")
def me(current_user: dict = Depends(get_current_active_user)):
    return {
        "id": current_user["user_id"],
        "username": current_user["username"],
        "full_name": current_user["full_name"],
        "email": current_user["email"],
        "role": current_user["role"]
    }
