import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict
from app.database import get_db

# Active token store: token -> {user_id, username, role, full_name, expires_at}
_ACTIVE_SESSIONS: Dict[str, dict] = {}

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with unique 16-byte salt (BBMS-SR-003)."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${key.hex()}"

def verify_password(password: str, hashed_value: str) -> bool:
    """Verify password against salted PBKDF2 hash."""
    try:
        salt, expected_hex = hashed_value.split("$", 1)
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return secrets.compare_digest(key.hex(), expected_hex)
    except Exception:
        return False

def authenticate_user(username: str, password: str, ip_address: str = "127.0.0.1") -> Optional[dict]:
    """Authenticate credentials, enforce active status, return session token (BBMS-SR-002)."""
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user:
            # Audit failed login attempt (BBMS-SR-005)
            db.execute(
                "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, "anonymous", "LOGIN_FAILED", "USER", "none", "User does not exist", ip_address)
            )
            return None

        if user["status"] != "active":
            db.execute(
                "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, user["role"], "LOGIN_FAILED", "USER", str(user["id"]), "Account is deactivated", ip_address)
            )
            return None

        if not verify_password(password, user["password_hash"]):
            db.execute(
                "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, user["role"], "LOGIN_FAILED", "USER", str(user["id"]), "Incorrect password", ip_address)
            )
            return None

        # Create session token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=24)
        session_data = {
            "token": token,
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "full_name": user["full_name"],
            "email": user["email"],
            "expires_at": expires_at
        }
        _ACTIVE_SESSIONS[token] = session_data

        # Audit successful login
        db.execute(
            "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["username"], user["role"], "LOGIN_SUCCESS", "USER", str(user["id"]), "Successful authentication", ip_address)
        )
        return session_data

def get_current_user_from_token(token: Optional[str]) -> Optional[dict]:
    if not token or token not in _ACTIVE_SESSIONS:
        return None
    session = _ACTIVE_SESSIONS[token]
    if datetime.utcnow() > session["expires_at"]:
        del _ACTIVE_SESSIONS[token]
        return None
    return session

def logout_user(token: str, ip_address: str = "127.0.0.1"):
    if token in _ACTIVE_SESSIONS:
        session = _ACTIVE_SESSIONS.pop(token)
        with get_db() as db:
            db.execute(
                "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session["username"], session["role"], "LOGOUT", "USER", str(session["user_id"]), "Session terminated", ip_address)
            )

def create_user(username: str, password: str, full_name: str, email: str, role: str, actor_username: str, ip_address: str = "127.0.0.1") -> int:
    """Create new system user with RBAC (BBMS-F-019)."""
    pw_hash = hash_password(password)
    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, full_name, email, role, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (username, pw_hash, full_name, email, role)
        )
        user_id = cursor.lastrowid
        db.execute(
            "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor_username, "admin", "CREATE_USER", "USER", str(user_id), f"Created {role} user '{username}'", ip_address)
        )
        return user_id

def set_user_status(user_id: int, status: str, actor_username: str, ip_address: str = "127.0.0.1"):
    """Activate or deactivate user account (BBMS-F-019)."""
    with get_db() as db:
        db.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        db.execute(
            "INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor_username, "admin", "UPDATE_USER_STATUS", "USER", str(user_id), f"Changed status to '{status}'", ip_address)
        )

def list_users() -> list:
    with get_db() as db:
        rows = db.execute("SELECT id, username, full_name, email, role, status, created_at FROM users ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
