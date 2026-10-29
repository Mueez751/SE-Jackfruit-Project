from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from app.database import get_db
from app.config import COMPONENT_SHELF_LIFE_DAYS, LOW_STOCK_THRESHOLD
from app.services.donor_service import is_donor_currently_eligible

def generate_collection_id() -> str:
    year = datetime.utcnow().year
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) as c FROM blood_collections WHERE collection_id LIKE ?", (f"COL-{year}-%",)).fetchone()["c"]
        return f"COL-{year}-{count + 1:04d}"

def generate_unit_id() -> str:
    year = datetime.utcnow().year
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE unit_id LIKE ?", (f"UNIT-{year}-%",)).fetchone()["c"]
        return f"UNIT-{year}-{count + 1:05d}"

def record_collection_and_create_unit(
    donor_id: str,
    blood_group: str,
    volume_ml: float = 450.0,
    component_type: str = "Whole Blood",
    collection_dt: Optional[date] = None,
    storage_location: str = "Main Cold Storage Bay-1",
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Atomic creation of blood collection and unique blood unit (BBMS-F-004, BBMS-F-005, BBMS-F-015).
    Enforces eligibility verification before acceptance (BBMS-F-002).
    """
    # 1. Enforce donor eligibility check
    is_eligible, reason = is_donor_currently_eligible(donor_id)
    if not is_eligible:
        return False, f"Collection rejected: {reason}", None

    if collection_dt is None:
        collection_dt = date.today()

    shelf_days = COMPONENT_SHELF_LIFE_DAYS.get(component_type, 35)
    expiry_dt = collection_dt + timedelta(days=shelf_days)

    collection_id = generate_collection_id()
    unit_id = generate_unit_id()

    with get_db() as db:
        # Insert collection record
        db.execute(
            """
            INSERT INTO blood_collections (collection_id, donor_id, blood_group, volume_ml, collection_date, status, collected_by)
            VALUES (?, ?, ?, ?, ?, 'Completed', ?)
            """,
            (collection_id, donor_id, blood_group, volume_ml, collection_dt.isoformat(), actor_username)
        )

        # Insert blood unit record
        db.execute(
            """
            INSERT INTO blood_units (
                unit_id, collection_id, donor_id, blood_group, component_type,
                volume_ml, collection_date, expiry_date, status, storage_location
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Available', ?)
            """,
            (unit_id, collection_id, donor_id, blood_group, component_type, volume_ml,
             collection_dt.isoformat(), expiry_dt.isoformat(), storage_location)
        )

        # Insert unit status log
        db.execute(
            """
            INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
            VALUES (?, 'None', 'Available', 'Initial collection and processing', ?)
            """,
            (unit_id, actor_username)
        )

        # Audit log
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'CREATE_BLOOD_UNIT', 'BLOOD_UNIT', ?, ?, ?)
            """,
            (actor_username, unit_id, f"Created unit {unit_id} ({blood_group} {component_type}), expires {expiry_dt}", ip_address)
        )

    return True, None, {
        "collection_id": collection_id,
        "unit_id": unit_id,
        "blood_group": blood_group,
        "component_type": component_type,
        "collection_date": collection_dt.isoformat(),
        "expiry_date": expiry_dt.isoformat(),
        "status": "Available"
    }

def update_unit_status(
    unit_id: str,
    new_status: str,
    reason: str,
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, Optional[str]]:
    """
    Quarantine, release, or discard a blood unit with recorded reason & audit (BBMS-F-008).
    """
    valid_statuses = ["Available", "Quarantined", "Discarded"]
    if new_status not in valid_statuses:
        return False, f"Invalid target status: {new_status}. Allowed: {valid_statuses}"

    with get_db() as db:
        unit = db.execute("SELECT * FROM blood_units WHERE unit_id = ?", (unit_id,)).fetchone()
        if not unit:
            return False, f"Unit {unit_id} not found."

        prev_status = unit["status"]
        if prev_status == "Issued":
            return False, "Cannot modify status of an issued blood unit."

        db.execute(
            "UPDATE blood_units SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE unit_id = ?",
            (new_status, unit_id)
        )

        db.execute(
            """
            INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (unit_id, prev_status, new_status, reason, actor_username)
        )

        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'UPDATE_UNIT_STATUS', 'BLOOD_UNIT', ?, ?, ?)
            """,
            (actor_username, unit_id, f"Changed status from {prev_status} to {new_status}. Reason: {reason}", ip_address)
        )

    return True, None

def auto_mark_expired_units() -> int:
    """
    Automatically mark blood units as expired when expiry date is reached (BBMS-F-007).
    Prevents their issue and triggers notification.
    """
    today_str = date.today().isoformat()
    expired_count = 0

    with get_db() as db:
        # Find units that are past expiry date and still Available or Reserved or Quarantined
        units = db.execute(
            """
            SELECT unit_id, blood_group, component_type, status, expiry_date
            FROM blood_units
            WHERE expiry_date < ? AND status NOT IN ('Expired', 'Discarded', 'Issued')
            """,
            (today_str,)
        ).fetchall()

        for u in units:
            unit_id = u["unit_id"]
            prev_status = u["status"]
            db.execute(
                "UPDATE blood_units SET status = 'Expired', updated_at = CURRENT_TIMESTAMP WHERE unit_id = ?",
                (unit_id,)
            )
            db.execute(
                """
                INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
                VALUES (?, ?, 'Expired', 'Automatic system expiry date elapsed', 'SYSTEM')
                """,
                (unit_id, prev_status)
            )
            db.execute(
                """
                INSERT INTO inventory_alerts (alert_type, severity, message)
                VALUES ('Expired_Unit', 'Warning', ?)
                """,
                (f"Blood Unit {unit_id} ({u['blood_group']} {u['component_type']}) expired on {u['expiry_date']} and has been decommissioned.",)
            )
            expired_count += 1

    return expired_count

def get_inventory_summary() -> Dict[str, Any]:
    """Maintain current inventory counts by blood group, component, and availability status (BBMS-F-006)."""
    # Auto-expire first to ensure accurate real-time data
    auto_mark_expired_units()

    with get_db() as db:
        total_units = db.execute("SELECT COUNT(*) as c FROM blood_units").fetchone()["c"]
        available_units = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE status = 'Available'").fetchone()["c"]
        quarantined_units = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE status = 'Quarantined'").fetchone()["c"]
        reserved_units = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE status = 'Reserved'").fetchone()["c"]
        issued_units = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE status = 'Issued'").fetchone()["c"]
        expired_units = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE status = 'Expired'").fetchone()["c"]
        discarded_units = db.execute("SELECT COUNT(*) as c FROM blood_units WHERE status = 'Discarded'").fetchone()["c"]

        # Matrix: Blood Group x Component for Available units
        matrix_rows = db.execute(
            """
            SELECT blood_group, component_type, COUNT(*) as count
            FROM blood_units
            WHERE status = 'Available'
            GROUP BY blood_group, component_type
            """
        ).fetchall()

        stock_matrix: Dict[str, Dict[str, int]] = {}
        for r in matrix_rows:
            bg = r["blood_group"]
            comp = r["component_type"]
            cnt = r["count"]
            if bg not in stock_matrix:
                stock_matrix[bg] = {}
            stock_matrix[bg][comp] = cnt

        # Group totals for Available
        group_totals = db.execute(
            """
            SELECT blood_group, COUNT(*) as count
            FROM blood_units
            WHERE status = 'Available'
            GROUP BY blood_group
            """
        ).fetchall()

        return {
            "total_units": total_units,
            "available_units": available_units,
            "quarantined_units": quarantined_units,
            "reserved_units": reserved_units,
            "issued_units": issued_units,
            "expired_units": expired_units,
            "discarded_units": discarded_units,
            "stock_matrix": stock_matrix,
            "group_totals": {r["blood_group"]: r["count"] for r in group_totals}
        }

def list_blood_units(
    blood_group: Optional[str] = None,
    component_type: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Searchable & filterable blood unit records (BBMS-F-016)."""
    auto_mark_expired_units()
    today = date.today()

    with get_db() as db:
        sql = "SELECT * FROM blood_units WHERE 1=1"
        params = []
        if blood_group:
            sql += " AND blood_group = ?"
            params.append(blood_group)
        if component_type:
            sql += " AND component_type = ?"
            params.append(component_type)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if query:
            sql += " AND (unit_id LIKE ? OR donor_id LIKE ? OR storage_location LIKE ?)"
            q_like = f"%{query}%"
            params.extend([q_like, q_like, q_like])

        sql += " ORDER BY expiry_date ASC, created_at DESC"
        rows = db.execute(sql, params).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            exp_d = datetime.strptime(d["expiry_date"], "%Y-%m-%d").date()
            diff_days = (exp_d - today).days
            d["days_until_expiry"] = diff_days
            d["is_expired"] = diff_days < 0
            results.append(d)
        return results
