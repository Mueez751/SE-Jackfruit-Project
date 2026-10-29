from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from app.database import get_db
from app.config import (
    MIN_DONOR_AGE, MAX_DONOR_AGE, MIN_DONOR_WEIGHT_KG,
    MIN_HEMOGLOBIN_G_DL, MIN_DONATION_INTERVAL_DAYS,
    BP_SYSTOLIC_MIN, BP_SYSTOLIC_MAX, BP_DIASTOLIC_MIN, BP_DIASTOLIC_MAX,
    PULSE_MIN, PULSE_MAX
)

def generate_donor_id() -> str:
    year = datetime.utcnow().year
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) as c FROM donors WHERE donor_id LIKE ?", (f"DON-{year}-%",)).fetchone()["c"]
        return f"DON-{year}-{count + 1:04d}"

def register_donor(
    full_name: str,
    age: int,
    gender: str,
    blood_group: str,
    phone: str,
    email: Optional[str] = None,
    address: Optional[str] = None,
    medical_remarks: Optional[str] = None,
    actor_username: str = "system",
    ip_address: str = "127.0.0.1"
) -> str:
    """Register donor with unique ID and contact info (BBMS-F-001)."""
    donor_id = generate_donor_id()
    with get_db() as db:
        db.execute(
            """
            INSERT INTO donors (donor_id, full_name, age, gender, blood_group, phone, email, address, medical_remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (donor_id, full_name, age, gender, blood_group, phone, email, address, medical_remarks)
        )
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'REGISTER_DONOR', 'DONOR', ?, ?, ?)
            """,
            (actor_username, donor_id, f"Registered donor {full_name} ({blood_group})", ip_address)
        )
    return donor_id

def evaluate_and_record_eligibility(
    donor_id: str,
    weight_kg: float,
    hemoglobin_g_dl: float,
    systolic_bp: int,
    diastolic_bp: int,
    pulse: int,
    days_since_last_donation: Optional[int] = 999,
    medical_flags: Optional[str] = None,
    actor_username: str = "staff",
    ip_address: str = "127.0.0.1"
) -> Tuple[bool, List[str]]:
    """
    Evaluate donor medical eligibility according to clinical thresholds (BBMS-F-002).
    Prevents donation collection registration if rules are not satisfied.
    """
    reasons = []

    # Fetch donor basic info
    with get_db() as db:
        donor = db.execute("SELECT * FROM donors WHERE donor_id = ?", (donor_id,)).fetchone()
        if not donor:
            return False, ["Donor ID not found in system."]

        if donor["age"] < MIN_DONOR_AGE or donor["age"] > MAX_DONOR_AGE:
            reasons.append(f"Age {donor['age']} is outside acceptable range ({MIN_DONOR_AGE}-{MAX_DONOR_AGE} years).")

        # Check last donation date in database
        last_collection = db.execute(
            "SELECT collection_date FROM blood_collections WHERE donor_id = ? ORDER BY collection_date DESC LIMIT 1",
            (donor_id,)
        ).fetchone()

        if last_collection:
            try:
                last_dt = datetime.strptime(last_collection["collection_date"], "%Y-%m-%d").date()
                diff_days = (date.today() - last_dt).days
                if diff_days < MIN_DONATION_INTERVAL_DAYS:
                    reasons.append(f"Minimum donation interval not met: {diff_days} days since last donation (requires >= {MIN_DONATION_INTERVAL_DAYS} days).")
            except Exception:
                pass
        elif days_since_last_donation is not None and days_since_last_donation < MIN_DONATION_INTERVAL_DAYS:
            reasons.append(f"Days since last donation ({days_since_last_donation}) is less than required {MIN_DONATION_INTERVAL_DAYS} days.")

    # Clinical vitals check
    if weight_kg < MIN_DONOR_WEIGHT_KG:
        reasons.append(f"Weight {weight_kg} kg is below minimum requirement ({MIN_DONOR_WEIGHT_KG} kg).")

    if hemoglobin_g_dl < MIN_HEMOGLOBIN_G_DL:
        reasons.append(f"Hemoglobin {hemoglobin_g_dl} g/dL is below minimum requirement ({MIN_HEMOGLOBIN_G_DL} g/dL).")

    if systolic_bp < BP_SYSTOLIC_MIN or systolic_bp > BP_SYSTOLIC_MAX:
        reasons.append(f"Systolic BP {systolic_bp} mmHg is outside safe range ({BP_SYSTOLIC_MIN}-{BP_SYSTOLIC_MAX} mmHg).")

    if diastolic_bp < BP_DIASTOLIC_MIN or diastolic_bp > BP_DIASTOLIC_MAX:
        reasons.append(f"Diastolic BP {diastolic_bp} mmHg is outside safe range ({BP_DIASTOLIC_MIN}-{BP_DIASTOLIC_MAX} mmHg).")

    if pulse < PULSE_MIN or pulse > PULSE_MAX:
        reasons.append(f"Pulse rate {pulse} bpm is outside normal resting range ({PULSE_MIN}-{PULSE_MAX} bpm).")

    if medical_flags and medical_flags.strip():
        reasons.append(f"Medical remarks contraindication: {medical_flags.strip()}")

    is_eligible = len(reasons) == 0
    rejection_text = "; ".join(reasons) if not is_eligible else None

    # Save to eligibility records
    with get_db() as db:
        db.execute(
            """
            INSERT INTO eligibility_records (
                donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse,
                days_since_last_donation, is_eligible, rejection_reason, checked_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse,
             days_since_last_donation, 1 if is_eligible else 0, rejection_text, actor_username)
        )
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'staff', 'CHECK_ELIGIBILITY', 'DONOR', ?, ?, ?)
            """,
            (actor_username, donor_id, f"Eligibility result: {'PASS' if is_eligible else 'REJECTED - ' + rejection_text}", ip_address)
        )

    return is_eligible, reasons

def is_donor_currently_eligible(donor_id: str) -> Tuple[bool, Optional[str]]:
    """Verify if the donor has a recent valid passing eligibility check."""
    with get_db() as db:
        rec = db.execute(
            "SELECT * FROM eligibility_records WHERE donor_id = ? ORDER BY checked_at DESC LIMIT 1",
            (donor_id,)
        ).fetchone()
        if not rec:
            return False, "No eligibility screening on record for this donor."
        if rec["is_eligible"] != 1:
            return False, f"Donor failed latest screening: {rec['rejection_reason']}"
        return True, None

def get_donor(donor_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as db:
        d = db.execute("SELECT * FROM donors WHERE donor_id = ?", (donor_id,)).fetchone()
        if not d:
            return None
        res = dict(d)
        # Stats
        colls = db.execute("SELECT COUNT(*) as c, MAX(collection_date) as last_d FROM blood_collections WHERE donor_id = ?", (donor_id,)).fetchone()
        res["donation_count"] = colls["c"] if colls else 0
        res["last_donation_date"] = colls["last_d"] if colls else None
        return res

def list_donors(query: Optional[str] = None, blood_group: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db() as db:
        sql = "SELECT * FROM donors WHERE 1=1"
        params = []
        if blood_group:
            sql += " AND blood_group = ?"
            params.append(blood_group)
        if query:
            sql += " AND (full_name LIKE ? OR donor_id LIKE ? OR phone LIKE ?)"
            q_like = f"%{query}%"
            params.extend([q_like, q_like, q_like])
        sql += " ORDER BY created_at DESC"
        rows = db.execute(sql, params).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            colls = db.execute("SELECT COUNT(*) as c, MAX(collection_date) as last_d FROM blood_collections WHERE donor_id = ?", (d["donor_id"],)).fetchone()
            d["donation_count"] = colls["c"] if colls else 0
            d["last_donation_date"] = colls["last_d"] if colls else None
            result.append(d)
        return result

def get_donor_donation_history(donor_id: str) -> List[Dict[str, Any]]:
    """Maintain donor donation history (BBMS-F-003)."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT c.*, u.unit_id, u.component_type, u.expiry_date, u.status as unit_status
            FROM blood_collections c
            LEFT JOIN blood_units u ON c.collection_id = u.collection_id
            WHERE c.donor_id = ?
            ORDER BY c.collection_date DESC
            """,
            (donor_id,)
        ).fetchall()
        return [dict(r) for r in rows]
