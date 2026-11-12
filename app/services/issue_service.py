import sqlite3
import time
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from app.database import get_db
from app.services.inventory_service import auto_mark_expired_units

def generate_issue_id(db=None) -> str:
    """Generate sequential unique issue transaction ID: ISS-YYYY-NNNN (BBMS-F-015)."""
    year = datetime.utcnow().year
    if db is not None:
        rows = db.execute(
            "SELECT issue_id FROM issue_transactions WHERE issue_id LIKE ? ORDER BY issue_id DESC",
            (f"ISS-{year}-%",)
        ).fetchall()
        max_num = 0
        for r in rows:
            try:
                num = int(r["issue_id"].split("-")[-1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                pass
        if max_num == 0:
            count = db.execute(
                "SELECT COUNT(*) as c FROM issue_transactions WHERE issue_id LIKE ?",
                (f"ISS-{year}-%",)
            ).fetchone()["c"]
            max_num = count
        return f"ISS-{year}-{max_num + 1:04d}"

    with get_db() as db_conn:
        return generate_issue_id(db=db_conn)

def issue_blood_units_for_request(
    request_id: str,
    verification_notes: str = "Standard pre-transfusion identity & cross-match verified.",
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1",
    max_retries: int = 5
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Issue blood units for an approved request (BBMS-F-013, BBMS-F-014, BBMS-F-015).
    Strictly prevents issue of expired, quarantined, or unavailable units.
    Wraps inventory changes in ACID transactions with immediate locking and atomic status checks.
    """
    auto_mark_expired_units()
    today_str = date.today().isoformat()

    for attempt in range(max_retries):
        try:
            with get_db(immediate=True) as db:
                req = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (request_id,)).fetchone()
                if not req:
                    return False, f"Request {request_id} not found.", []

                if req["status"] not in ("Approved", "Pending"):
                    return False, f"Cannot issue for request with status '{req['status']}'. Must be Approved.", []

                # Find allocated units for this request
                alloc_rows = db.execute(
                    "SELECT a.allocation_id, a.unit_id FROM allocations a WHERE a.request_id = ? AND a.status = 'Allocated'",
                    (request_id,)
                ).fetchall()

                if not alloc_rows:
                    return False, f"No units are currently allocated to request {request_id}. Please allocate units before issuing.", []

                # Verify each unit before issuing (BBMS-F-013)
                units_to_issue = []
                for a in alloc_rows:
                    uid = a["unit_id"]
                    u = db.execute("SELECT * FROM blood_units WHERE unit_id = ?", (uid,)).fetchone()
                    if not u:
                        return False, f"Allocated unit {uid} does not exist in inventory.", []

                    if u["status"] == "Expired" or u["expiry_date"] < today_str:
                        return False, f"BLOCKED: Unit {uid} is EXPIRED (expired on {u['expiry_date']}). Issue is prohibited by safety policy.", []

                    if u["status"] == "Quarantined":
                        return False, f"BLOCKED: Unit {uid} is QUARANTINED. Issue is prohibited.", []

                    if u["status"] == "Discarded":
                        return False, f"BLOCKED: Unit {uid} is marked as DISCARDED. Issue is prohibited.", []

                    if u["status"] == "Issued":
                        return False, f"BLOCKED: Unit {uid} has ALREADY BEEN ISSUED.", []

                    if u["status"] != "Reserved":
                        return False, f"BLOCKED: Unit {uid} is not in 'Reserved' status (current status: {u['status']}).", []

                    units_to_issue.append((a["allocation_id"], u))

                # Perform atomic issue transactions
                issued_records = []
                now_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                for alloc_id, u in units_to_issue:
                    uid = u["unit_id"]
                    issue_id = generate_issue_id(db=db)

                    # Insert issue transaction
                    db.execute(
                        """
                        INSERT INTO issue_transactions (
                            issue_id, request_id, unit_id, hospital_name, patient_name,
                            issuing_staff, issue_timestamp, verification_notes
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (issue_id, request_id, uid, req["hospital_name"], req["patient_name"],
                         actor_username, now_ts, verification_notes)
                    )

                    # Concurrency-safe atomic unit status update (Reserved -> Issued)
                    cur_unit = db.execute(
                        "UPDATE blood_units SET status = 'Issued', updated_at = CURRENT_TIMESTAMP WHERE unit_id = ? AND status = 'Reserved'",
                        (uid,)
                    )
                    if cur_unit.rowcount == 0:
                        raise ValueError(f"Unit {uid} was concurrently issued or status changed by another user.")

                    # Concurrency-safe atomic allocation status update (Allocated -> Issued)
                    cur_alloc = db.execute(
                        "UPDATE allocations SET status = 'Issued' WHERE allocation_id = ? AND status = 'Allocated'",
                        (alloc_id,)
                    )
                    if cur_alloc.rowcount == 0:
                        raise ValueError(f"Allocation {alloc_id} was concurrently modified or issued.")

                    # Update unit status log
                    db.execute(
                        """
                        INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
                        VALUES (?, 'Reserved', 'Issued', ?, ?)
                        """,
                        (uid, f"Issued for request {request_id} to {req['hospital_name']}", actor_username)
                    )

                    issued_records.append({
                        "issue_id": issue_id,
                        "request_id": request_id,
                        "unit_id": uid,
                        "blood_group": u["blood_group"],
                        "component_type": u["component_type"],
                        "hospital_name": req["hospital_name"],
                        "patient_name": req["patient_name"],
                        "issuing_staff": actor_username,
                        "issue_timestamp": now_ts
                    })

                # Update request status to Fulfilled if issued units >= requested quantity
                total_issued_for_req = db.execute(
                    "SELECT COUNT(*) as c FROM issue_transactions WHERE request_id = ?",
                    (request_id,)
                ).fetchone()["c"]

                if total_issued_for_req >= req["quantity"]:
                    db.execute(
                        "UPDATE blood_requests SET status = 'Fulfilled' WHERE request_id = ?",
                        (request_id,)
                    )

                # Audit log
                db.execute(
                    """
                    INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
                    VALUES (?, 'staff', 'ISSUE_BLOOD_UNITS', 'ISSUE_TRANSACTION', ?, ?, ?)
                    """,
                    (actor_username, request_id, f"Issued {len(issued_records)} blood unit(s) for request {request_id} to {req['hospital_name']}", ip_address)
                )

            return True, None, issued_records

        except ValueError as e:
            # Controlled concurrency or status mismatch - rolled back cleanly by context manager
            return False, str(e), []

        except sqlite3.IntegrityError as e:
            err_msg = str(e).lower()
            if "issue_id" in err_msg or "primary key" in err_msg:
                if attempt < max_retries - 1:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                return False, f"Failed to allocate unique issue ID after {max_retries} attempts: {e}", []
            return False, f"Database integrity error: {e}", []

        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                if attempt < max_retries - 1:
                    time.sleep(0.02 * (attempt + 1))
                    continue
                return False, "Database busy during blood unit issue. Please retry.", []
            raise

    return False, "Failed to issue blood units due to repeated concurrency collisions.", []

def get_issue_certificate(issue_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full dispatch certificate details for printing / verification."""
    with get_db() as db:
        row = db.execute(
            """
            SELECT i.*, u.blood_group, u.component_type, u.volume_ml, u.collection_date, u.expiry_date,
                   r.urgency, r.requester_name, r.patient_blood_group
            FROM issue_transactions i
            JOIN blood_units u ON i.unit_id = u.unit_id
            JOIN blood_requests r ON i.request_id = r.request_id
            WHERE i.issue_id = ?
            """,
            (issue_id,)
        ).fetchone()

        if not row:
            return None
        return dict(row)

def list_issue_transactions(query: Optional[str] = None, hospital: Optional[str] = None) -> List[Dict[str, Any]]:
    """Searchable issue transaction records (BBMS-F-014, BBMS-F-016)."""
    with get_db() as db:
        sql = """
        SELECT i.*, u.blood_group, u.component_type
        FROM issue_transactions i
        JOIN blood_units u ON i.unit_id = u.unit_id
        WHERE 1=1
        """
        params = []
        if hospital:
            sql += " AND i.hospital_name LIKE ?"
            params.append(f"%{hospital}%")
        if query:
            sql += " AND (i.issue_id LIKE ? OR i.request_id LIKE ? OR i.unit_id LIKE ? OR i.patient_name LIKE ?)"
            q_like = f"%{query}%"
            params.extend([q_like, q_like, q_like, q_like])

        sql += " ORDER BY i.issue_timestamp DESC"
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
