from datetime import datetime
from typing import List, Dict, Any, Optional
from app.database import get_db

def log_audit_event(
    actor_username: str,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details: Optional[str] = None,
    ip_address: str = "127.0.0.1"
) -> int:
    """Record an audit trail event for security and traceability (BBMS-F-020, BBMS-SR-005)."""
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
        )
        return cur.lastrowid

def list_audit_logs(
    actor: Optional[str] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query audit logs with multi-field filtering (BBMS-F-020)."""
    with get_db() as db:
        sql = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        if actor:
            sql += " AND actor_username LIKE ?"
            params.append(f"%{actor}%")
        if action:
            sql += " AND action = ?"
            params.append(action)
        if entity_type:
            sql += " AND entity_type = ?"
            params.append(entity_type)

        sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limit)

        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
