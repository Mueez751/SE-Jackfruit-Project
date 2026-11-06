from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from app.database import get_db
from app.config import BLOOD_GROUPS, COMPONENT_TYPES

def generate_request_id() -> str:
    year = datetime.utcnow().year
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) as c FROM blood_requests WHERE request_id LIKE ?", (f"REQ-{year}-%",)).fetchone()["c"]
        return f"REQ-{year}-{count + 1:04d}"

def create_blood_request(
    hospital_name: str,
    requester_name: str,
    patient_name: str,
    patient_blood_group: str,
    component_type: str,
    quantity: int,
    urgency: str = "Normal",
    required_date: Optional[date] = None,
    actor_username: str = "hospital",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate and create a hospital blood request (BBMS-F-009, BBMS-F-010).
    Enforces field validation and rejects invalid requests.
    """
    if patient_blood_group not in BLOOD_GROUPS:
        return False, f"Invalid blood group: {patient_blood_group}", None

    if component_type not in COMPONENT_TYPES:
        return False, f"Invalid component type: {component_type}", None

    if quantity <= 0 or quantity > 20:
        return False, f"Requested quantity {quantity} is invalid (must be 1-20 units).", None

    if required_date is None:
        required_date = date.today()

    request_id = generate_request_id()

    with get_db() as db:
        db.execute(
            """
            INSERT INTO blood_requests (
                request_id, hospital_name, requester_name, patient_name,
                patient_blood_group, component_type, quantity, urgency,
                required_date, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
            """,
            (request_id, hospital_name, requester_name, patient_name,
             patient_blood_group, component_type, quantity, urgency, required_date.isoformat())
        )

        # Trigger high-priority alert if urgent or emergency
        if urgency in ("Urgent", "Emergency"):
            severity = "Critical" if urgency == "Emergency" else "Warning"
            db.execute(
                """
                INSERT INTO inventory_alerts (alert_type, severity, message)
                VALUES ('Urgent_Request', ?, ?)
                """,
                (severity, f"{urgency.upper()} BLOOD REQUEST: {request_id} for {quantity} unit(s) of {patient_blood_group} {component_type} from {hospital_name} (Patient: {patient_name}).")
            )

        # Audit log
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'hospital', 'CREATE_BLOOD_REQUEST', 'BLOOD_REQUEST', ?, ?, ?)
            """,
            (actor_username, request_id, f"Created {urgency} request {request_id} for {quantity} unit(s) of {patient_blood_group} {component_type}", ip_address)
        )

    return True, None, request_id

def record_request_decision(
    request_id: str,
    decision: str,
    reason: str,
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, Optional[str]]:
    """
    Approve, reject, or place on hold a blood request with decision notes (BBMS-F-011).
    """
    valid_decisions = ["Approved", "Rejected", "On_Hold"]
    if decision not in valid_decisions:
        return False, f"Invalid decision: {decision}. Must be one of {valid_decisions}"

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as db:
        req = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not req:
            return False, f"Request {request_id} not found."

        if req["status"] in ("Fulfilled", "Cancelled"):
            return False, f"Cannot change decision for request with terminal status: {req['status']}."

        db.execute(
            """
            UPDATE blood_requests
            SET status = ?, decision_reason = ?, decision_by = ?, decision_at = ?
            WHERE request_id = ?
            """,
            (decision, reason, actor_username, now_str, request_id)
        )

        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'DECIDE_BLOOD_REQUEST', 'BLOOD_REQUEST', ?, ?, ?)
            """,
            (actor_username, request_id, f"Set request status to {decision}. Reason: {reason}", ip_address)
        )

    return True, None

def get_blood_request(request_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as db:
        req = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not req:
            return None
        res = dict(req)
        # Fetch allocated units
        allocs = db.execute(
            "SELECT unit_id FROM allocations WHERE request_id = ? AND status = 'Allocated'",
            (request_id,)
        ).fetchall()
        res["allocated_units"] = [a["unit_id"] for a in allocs]
        return res

def list_blood_requests(
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    hospital: Optional[str] = None,
    query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Searchable & filterable blood request records (BBMS-F-016)."""
    with get_db() as db:
        sql = "SELECT * FROM blood_requests WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if urgency:
            sql += " AND urgency = ?"
            params.append(urgency)
        if hospital:
            sql += " AND hospital_name LIKE ?"
            params.append(f"%{hospital}%")
        if query:
            sql += " AND (request_id LIKE ? OR patient_name LIKE ? OR hospital_name LIKE ?)"
            q_like = f"%{query}%"
            params.extend([q_like, q_like, q_like])

        # Order by priority: Emergency > Urgent > Normal, then created_at DESC
        sql += """
        ORDER BY 
            CASE urgency 
                WHEN 'Emergency' THEN 1 
                WHEN 'Urgent' THEN 2 
                ELSE 3 
            END ASC,
            created_at DESC
        """
        rows = db.execute(sql, params).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            allocs = db.execute(
                "SELECT unit_id FROM allocations WHERE request_id = ? AND status = 'Allocated'",
                (d["request_id"],)
            ).fetchall()
            d["allocated_units"] = [a["unit_id"] for a in allocs]
            results.append(d)
        return results
