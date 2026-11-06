from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from app.database import get_db
from app.config import RBC_COMPATIBILITY, PLASMA_COMPATIBILITY
from app.services.inventory_service import auto_mark_expired_units

def generate_allocation_id() -> str:
    year = datetime.utcnow().year
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) as c FROM allocations WHERE allocation_id LIKE ?", (f"ALC-{year}-%",)).fetchone()["c"]
        return f"ALC-{year}-{count + 1:04d}"

def get_compatible_groups(recipient_group: str, component_type: str) -> List[str]:
    """Determine compatible donor groups based on component type and recipient ABO/Rh."""
    if component_type in ("Fresh Frozen Plasma", "Cryoprecipitate"):
        return PLASMA_COMPATIBILITY.get(recipient_group, [recipient_group])
    else:
        # Whole Blood, Packed Red Cells, Platelets
        return RBC_COMPATIBILITY.get(recipient_group, [recipient_group])

def preview_fefo_candidates(request_id: str) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Simulate and preview eligible units using FEFO (First-Expire, First-Out) (BBMS-F-012).
    """
    auto_mark_expired_units()
    today_str = date.today().isoformat()

    with get_db() as db:
        req = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not req:
            return False, f"Request {request_id} not found.", []

        if req["status"] not in ("Approved", "Pending"):
            return False, f"Request is in status '{req['status']}'. Can only allocate for Approved or Pending requests.", []

        patient_group = req["patient_blood_group"]
        component = req["component_type"]
        qty = req["quantity"]

        compatible_groups = get_compatible_groups(patient_group, component)
        placeholders = ",".join("?" for _ in compatible_groups)

        sql = f"""
        SELECT * FROM blood_units
        WHERE status = 'Available'
          AND expiry_date >= ?
          AND component_type = ?
          AND blood_group IN ({placeholders})
        ORDER BY expiry_date ASC, created_at ASC
        """
        params = [today_str, component] + compatible_groups
        rows = db.execute(sql, params).fetchall()

        candidates = []
        for r in rows:
            d = dict(r)
            exp_d = datetime.strptime(d["expiry_date"], "%Y-%m-%d").date()
            d["days_until_expiry"] = (exp_d - date.today()).days
            d["is_exact_match"] = (d["blood_group"] == patient_group)
            candidates.append(d)

        return True, None, candidates

def allocate_units_fefo(
    request_id: str,
    selected_unit_ids: Optional[List[str]] = None,
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Allocate available eligible blood units to an approved request using FEFO (BBMS-F-012).
    Updates inventory and reservation status atomically (BBMS-F-015).
    """
    auto_mark_expired_units()
    today_str = date.today().isoformat()

    with get_db() as db:
        req = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not req:
            return False, f"Request {request_id} not found.", []

        if req["status"] != "Approved":
            return False, f"Request status must be 'Approved' before allocation (currently: {req['status']}).", []

        needed_qty = req["quantity"]
        # Check already allocated count
        existing_allocs = db.execute(
            "SELECT COUNT(*) as c FROM allocations WHERE request_id = ? AND status = 'Allocated'",
            (request_id,)
        ).fetchone()["c"]

        remaining_needed = needed_qty - existing_allocs
        if remaining_needed <= 0:
            return False, "This request has already been fully allocated.", []

        patient_group = req["patient_blood_group"]
        component = req["component_type"]
        compatible_groups = get_compatible_groups(patient_group, component)

        chosen_units = []

        if selected_unit_ids and len(selected_unit_ids) > 0:
            # Operator manually specified units - validate each
            for uid in selected_unit_ids:
                u = db.execute(
                    "SELECT * FROM blood_units WHERE unit_id = ? AND status = 'Available' AND expiry_date >= ?",
                    (uid, today_str)
                ).fetchone()
                if not u:
                    return False, f"Unit {uid} is not available or has expired.", []
                if u["blood_group"] not in compatible_groups:
                    return False, f"Unit {uid} ({u['blood_group']}) is biologically incompatible with recipient ({patient_group}).", []
                if u["component_type"] != component:
                    return False, f"Unit {uid} component ({u['component_type']}) does not match requested ({component}).", []
                chosen_units.append(uid)
        else:
            # Auto-FEFO: query earliest expiring units
            placeholders = ",".join("?" for _ in compatible_groups)
            sql = f"""
            SELECT unit_id, blood_group, expiry_date FROM blood_units
            WHERE status = 'Available'
              AND expiry_date >= ?
              AND component_type = ?
              AND blood_group IN ({placeholders})
            ORDER BY expiry_date ASC, created_at ASC
            LIMIT ?
            """
            params = [today_str, component] + compatible_groups + [remaining_needed]
            available_rows = db.execute(sql, params).fetchall()

            if len(available_rows) < remaining_needed:
                return False, f"Insufficient compatible stock. Needed {remaining_needed} unit(s), but only {len(available_rows)} available.", []

            chosen_units = [r["unit_id"] for r in available_rows]

        # Atomically reserve each chosen unit
        allocated_ids = []
        for uid in chosen_units:
            alloc_id = generate_allocation_id()
            db.execute(
                """
                INSERT INTO allocations (allocation_id, request_id, unit_id, allocated_by, status)
                VALUES (?, ?, ?, ?, 'Allocated')
                """,
                (alloc_id, request_id, uid, actor_username)
            )
            db.execute(
                "UPDATE blood_units SET status = 'Reserved', updated_at = CURRENT_TIMESTAMP WHERE unit_id = ?",
                (uid,)
            )
            db.execute(
                """
                INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
                VALUES (?, 'Available', 'Reserved', ?, ?)
                """,
                (uid, f"Allocated to request {request_id} via FEFO", actor_username)
            )
            allocated_ids.append(uid)

        # Audit log
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'ALLOCATE_UNITS_FEFO', 'REQUEST_ALLOCATION', ?, ?, ?)
            """,
            (actor_username, request_id, f"Allocated {len(allocated_ids)} unit(s) ({', '.join(allocated_ids)}) to request {request_id}", ip_address)
        )

        return True, None, allocated_ids

def release_allocation(
    request_id: str,
    unit_id: str,
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, Optional[str]]:
    """Release an allocated blood unit back to available inventory."""
    with get_db() as db:
        alloc = db.execute(
            "SELECT * FROM allocations WHERE request_id = ? AND unit_id = ? AND status = 'Allocated'",
            (request_id, unit_id)
        ).fetchone()
        if not alloc:
            return False, f"Allocation for unit {unit_id} on request {request_id} not found."

        db.execute(
            "UPDATE allocations SET status = 'Released' WHERE allocation_id = ?",
            (alloc["allocation_id"],)
        )
        db.execute(
            "UPDATE blood_units SET status = 'Available', updated_at = CURRENT_TIMESTAMP WHERE unit_id = ?",
            (unit_id,)
        )
        db.execute(
            """
            INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
            VALUES (?, 'Reserved', 'Available', ?, ?)
            """,
            (unit_id, f"Released from request {request_id}", actor_username)
        )
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'RELEASE_ALLOCATION', 'REQUEST_ALLOCATION', ?, ?, ?)
            """,
            (actor_username, request_id, f"Released unit {unit_id} back to available stock", ip_address)
        )

    return True, None
