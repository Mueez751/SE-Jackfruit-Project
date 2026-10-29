from fastapi import APIRouter, HTTPException, Header, Request, status
from typing import Optional
from app.models import UserLogin
from app.services.auth_service import authenticate_user, get_current_user_from_token, logout_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

def get_session_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    return get_current_user_from_token(token)

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
def logout(request: Request, authorization: Optional[str] = Header(None)):
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        client_ip = request.client.host if request.client else "127.0.0.1"
        logout_user(token, ip_address=client_ip)
    return {"message": "Logged out successfully."}

@router.get("/me")
def me(authorization: Optional[str] = Header(None)):
    user = get_session_user(authorization)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return {
        "id": user["user_id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"]
    }
