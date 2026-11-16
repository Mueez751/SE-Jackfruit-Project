# BBMS-F-016: Blood Request Search & Filtering - Assigned to Nandan Kumar K R
# BBMS-F-011: Request Approval Workflow with Rationale - Assigned to Nandan Kumar K R
# BBMS-F-010: Request Validation - Assigned to Mueez Ahmed
import sqlite3
import time
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from app.database import get_db
from app.config import BLOOD_GROUPS, COMPONENT_TYPES

def generate_request_id(db=None) -> str:
    """Generate sequential unique blood request ID: REQ-YYYY-NNNN (BBMS-F-009, BBMS-NF-001)."""
    year = datetime.utcnow().year
    if db is not None:
        rows = db.execute(
            "SELECT request_id FROM blood_requests WHERE request_id LIKE ? ORDER BY request_id DESC",
            (f"REQ-{year}-%",)
        ).fetchall()
        max_num = 0
        for r in rows:
            try:
                num = int(r["request_id"].split("-")[-1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                pass
        if max_num == 0:
            count = db.execute(
                "SELECT COUNT(*) as c FROM blood_requests WHERE request_id LIKE ?",
                (f"REQ-{year}-%",)
            ).fetchone()["c"]
            max_num = count
        return f"REQ-{year}-{max_num + 1:04d}"

    with get_db() as db_conn:
        return generate_request_id(db=db_conn)

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
    ip_address: str = "127.0.0.1",
    max_retries: int = 15,
    max_timeout: float = 1.5
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate and create a hospital blood request (BBMS-F-009, BBMS-F-010).
    Enforces field validation and rejects invalid requests.
    Thread-safe with collision retries and atomic locking for concurrent write performance (BBMS-NF-001).
    Database lock and retry waiting is bounded by max_timeout (default 1.5s), ensuring SQLite contention
    does not block indefinitely. Note: this bounds database lock/retry waiting specifically;
    it does not claim to guarantee every possible end-to-end HTTP request completes under arbitrary external load.
    """
    if patient_blood_group not in BLOOD_GROUPS:
        return False, f"Invalid blood group: {patient_blood_group}", None

    if component_type not in COMPONENT_TYPES:
        return False, f"Invalid component type: {component_type}", None

    if quantity <= 0 or quantity > 20:
        return False, f"Requested quantity {quantity} is invalid (must be 1-20 units).", None

    if required_date is None:
        required_date = date.today()

    start_time = time.monotonic()
    deadline = start_time + max_timeout

    for attempt in range(max_retries):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, "Database busy during request creation. Please retry.", None

        attempt_timeout = min(remaining, 0.2)
        try:
            with get_db(immediate=True, timeout=attempt_timeout) as db:
                request_id = generate_request_id(db=db)

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

        except sqlite3.IntegrityError as e:
            err_msg = str(e).lower()
            # Only retry if the failure is specifically a request_id primary key collision
            is_request_id_collision = (
                "blood_requests.request_id" in err_msg
                or ("request_id" in err_msg and ("unique" in err_msg or "primary key" in err_msg))
            )
            if is_request_id_collision:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, "Database busy during request creation. Please retry.", None
                if attempt < max_retries - 1:
                    sleep_time = min(0.01 * (attempt + 1), remaining)
                    time.sleep(sleep_time)
                    if deadline - time.monotonic() <= 0:
                        return False, "Database busy during request creation. Please retry.", None
                    continue
                return False, f"Failed to allocate unique request ID after {max_retries} attempts: {e}", None
            return False, f"Database integrity error: {e}", None

        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, "Database busy during request creation. Please retry.", None
                if attempt < max_retries - 1:
                    sleep_time = min(0.02 * (attempt + 1), remaining)
                    time.sleep(sleep_time)
                    if deadline - time.monotonic() <= 0:
                        return False, "Database busy during request creation. Please retry.", None
                    continue
                return False, "Database busy during request creation. Please retry.", None
            raise

    return False, "Database busy during request creation. Please retry.", None

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

    if not reason or not str(reason).strip():
        return False, "Written rationale is mandatory for recording a request decision."

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
    blood_group: Optional[str] = None,
    component_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Searchable & filterable blood request records across status, priority, group, and dates (BBMS-F-016)."""
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
        if blood_group:
            sql += " AND patient_blood_group = ?"
            params.append(blood_group)
        if component_type:
            sql += " AND component_type = ?"
            params.append(component_type)
        if from_date:
            sql += " AND required_date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND required_date <= ?"
            params.append(to_date)
        if query:
            sql += " AND (request_id LIKE ? OR patient_name LIKE ? OR hospital_name LIKE ? OR requester_name LIKE ?)"
            q_like = f"%{query}%"
            params.extend([q_like, q_like, q_like, q_like])

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
