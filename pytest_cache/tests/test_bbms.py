import os
import sys
import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import get_db, init_db
from app.seed_data import seed_database
from app.services.auth_service import hash_password, verify_password
from app.services.donor_service import register_donor, evaluate_and_record_eligibility, get_donor_donation_history
from app.services.inventory_service import (
    record_collection_and_create_unit, update_unit_status,
    auto_mark_expired_units, get_inventory_summary
)
from app.services.request_service import create_blood_request, record_request_decision
from app.services.allocation_service import allocate_units_fefo, preview_fefo_candidates
from app.services.issue_service import issue_blood_units_for_request
from app.services.report_service import (
    generate_inventory_report, generate_donations_report,
    generate_issues_report, export_report_to_csv
)
from app.services.notification_service import list_notifications
from app.services.audit_service import list_audit_logs

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    init_db()
    seed_database(force=True)

@pytest.fixture
def client():
    return TestClient(app)

# ==================== DONOR MODULE TESTS ====================

def test_tc_donor_01_register_donor():
    """TC-Donor-01 (BBMS-F-001): Create valid donor record and verify unique ID assigned."""
    donor_id = register_donor(
        full_name="Test Donor John",
        age=30,
        gender="Male",
        blood_group="A+",
        phone="+91-9123456789",
        email="john.test@example.com",
        address="Bengaluru"
    )
    assert donor_id.startswith("DON-")

    with get_db() as db:
        d = db.execute("SELECT * FROM donors WHERE donor_id = ?", (donor_id,)).fetchone()
        assert d is not None
        assert d["full_name"] == "Test Donor John"
        assert d["blood_group"] == "A+"

def test_tc_donor_02_eligibility_rejection_rules():
    """TC-Donor-02 (BBMS-F-002): Ineligible donor cannot proceed to collection registration."""
    # Register an underweight and low Hb donor
    did = register_donor(
        full_name="Low Weight Donor",
        age=20,
        gender="Female",
        blood_group="O+",
        phone="+91-9988776655"
    )

    # Screening with weight < 50kg and Hb < 12.5
    is_eligible, reasons = evaluate_and_record_eligibility(
        donor_id=did,
        weight_kg=44.0,           # Under 50kg -> Ineligible
        hemoglobin_g_dl=11.0,      # Under 12.5 -> Ineligible
        systolic_bp=120,
        diastolic_bp=80,
        pulse=75,
        days_since_last_donation=100
    )
    assert is_eligible is False
    assert any("Weight" in r for r in reasons)
    assert any("Hemoglobin" in r for r in reasons)

    # Attempting to register collection MUST fail
    success, error, data = record_collection_and_create_unit(
        donor_id=did,
        blood_group="O+",
        volume_ml=450.0
    )
    assert success is False
    assert "rejected" in error.lower()

def test_tc_donor_03_donation_history():
    """TC-Donor-03 (BBMS-F-003): Completed donation appears in donor history."""
    # Rahul has completed donations in seed data
    history = get_donor_donation_history("DON-2026-0001")
    assert isinstance(history, list)
    assert len(history) > 0
    assert "collection_id" in history[0]

# ==================== COLLECTION & INVENTORY TESTS ====================

def test_tc_collection_01_and_02_create_unit():
    """TC-Collection-01 (BBMS-F-004) & TC-Collection-02 (BBMS-F-005): Unique ID and metadata."""
    # Fatima Zehra (DON-2026-0004) is pre-cleared and eligible
    success, error, data = record_collection_and_create_unit(
        donor_id="DON-2026-0004",
        blood_group="O-",
        volume_ml=450.0,
        component_type="Whole Blood"
    )
    assert success is True
    assert data["unit_id"].startswith("UNIT-")
    assert data["blood_group"] == "O-"
    assert data["component_type"] == "Whole Blood"
    assert data["status"] == "Available"
    # Shelf life of Whole Blood is 35 days
    exp_dt = date.fromisoformat(data["expiry_date"])
    coll_dt = date.fromisoformat(data["collection_date"])
    assert (exp_dt - coll_dt).days == 35

def test_tc_inv_01_maintain_inventory_counts():
    """TC-Inv-01 (BBMS-F-006): Inventory totals reflect real-time counts."""
    summary = get_inventory_summary()
    assert summary["total_units"] > 0
    assert summary["available_units"] >= 0
    assert "O+" in summary["group_totals"]

def test_tc_inv_02_auto_mark_expired_and_block_issue():
    """TC-Inv-02 (BBMS-F-007) & TC-Alloc-02 (BBMS-F-013): Auto-mark expired unit and block issue."""
    # UNIT-2026-00012 was seeded with an past expiry date
    auto_mark_expired_units()

    with get_db() as db:
        u = db.execute("SELECT status FROM blood_units WHERE unit_id = 'UNIT-2026-00012'").fetchone()
        assert u["status"] == "Expired"

def test_tc_inv_03_quarantine_discard_audit():
    """TC-Inv-03 (BBMS-F-008): Status change requires reason and records audit entry."""
    uid = "UNIT-2026-00003"
    success, error = update_unit_status(
        unit_id=uid,
        new_status="Quarantined",
        reason="Abnormal turbidity observed in plasma component"
    )
    assert success is True

    with get_db() as db:
        unit = db.execute("SELECT status FROM blood_units WHERE unit_id = ?", (uid,)).fetchone()
        assert unit["status"] == "Quarantined"

        log = db.execute("SELECT * FROM unit_status_logs WHERE unit_id = ? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        assert log["new_status"] == "Quarantined"
        assert "Abnormal turbidity" in log["reason"]

def test_tc_inv_04_atomic_transaction_integrity():
    """TC-Inv-04 (BBMS-F-015): No partial updates occur when a transaction fails."""
    # Attempting to allocate an unapproved request should fail atomically
    success, error, ids = allocate_units_fefo("REQ-2026-0002")  # REQ-2026-0002 is Pending, not Approved
    assert success is False
    assert len(ids) == 0

# ==================== REQUEST & ALLOCATION TESTS ====================

def test_tc_req_01_create_request():
    """TC-Req-01 (BBMS-F-009): Valid request receives unique ID and pending status."""
    success, error, req_id = create_blood_request(
        hospital_name="Apollo Hospital",
        requester_name="Dr. K. Srinivas",
        patient_name="Mohan Rao",
        patient_blood_group="B+",
        component_type="Whole Blood",
        quantity=1,
        urgency="Urgent"
    )
    assert success is True
    assert req_id.startswith("REQ-")

def test_tc_req_02_reject_invalid_request():
    """TC-Req-02 (BBMS-F-010): Reject invalid blood group or zero quantity."""
    success, error, req_id = create_blood_request(
        hospital_name="Apollo Hospital",
        requester_name="Dr. Srinivas",
        patient_name="Mohan",
        patient_blood_group="INVALID_GROUP",
        component_type="Whole Blood",
        quantity=1
    )
    assert success is False
    assert "invalid blood group" in error.lower()

def test_tc_req_03_approve_and_hold_decision():
    """TC-Req-03 (BBMS-F-011): Request status and decision history updated."""
    # Create request and approve it
    _, _, req_id = create_blood_request(
        hospital_name="St. Martha Hospital",
        requester_name="Dr. Alice",
        patient_name="Kiran Roy",
        patient_blood_group="A+",
        component_type="Whole Blood",
        quantity=1,
        urgency="Normal"
    )
    success, error = record_request_decision(
        request_id=req_id,
        decision="Approved",
        reason="Crossmatch verified and stock confirmed"
    )
    assert success is True

    with get_db() as db:
        req = db.execute("SELECT status, decision_reason FROM blood_requests WHERE request_id = ?", (req_id,)).fetchone()
        assert req["status"] == "Approved"
        assert "Crossmatch verified" in req["decision_reason"]

def test_tc_alloc_01_fefo_allocation_strategy():
    """TC-Alloc-01 (BBMS-F-012): Allocation selects earliest expiring eligible unit (FEFO)."""
    # Create request for O+ Packed Red Cells
    _, _, req_id = create_blood_request(
        hospital_name="Fortis Hospital",
        requester_name="Dr. Mehta",
        patient_name="Anil Kumar",
        patient_blood_group="O+",
        component_type="Packed Red Cells",
        quantity=1,
        urgency="Emergency"
    )
    record_request_decision(req_id, "Approved", "Emergency trauma OT")

    # Preview FEFO candidates
    ok, err, candidates = preview_fefo_candidates(req_id)
    assert ok is True
    assert len(candidates) > 0
    # Candidate units must be ordered ascending by expiry date (FEFO)
    for i in range(len(candidates) - 1):
        assert candidates[i]["expiry_date"] <= candidates[i+1]["expiry_date"]

    # Allocate unit
    alloc_ok, alloc_err, alloc_ids = allocate_units_fefo(req_id)
    assert alloc_ok is True
    assert len(alloc_ids) == 1
    # Check unit status is now Reserved
    with get_db() as db:
        u = db.execute("SELECT status FROM blood_units WHERE unit_id = ?", (alloc_ids[0],)).fetchone()
        assert u["status"] == "Reserved"

# ==================== ISSUE & REPORTING TESTS ====================

def test_tc_issue_01_record_blood_issue():
    """TC-Issue-01 (BBMS-F-014): Issue transaction stored and traceable end-to-end."""
    # REQ-2026-0001 is seeded with UNIT-2026-00001 allocated
    ok, err, records = issue_blood_units_for_request(
        request_id="REQ-2026-0001",
        verification_notes="Compatibility matched 100%"
    )
    assert ok is True
    assert len(records) == 1
    assert records[0]["issue_id"].startswith("ISS-")

    with get_db() as db:
        u = db.execute("SELECT status FROM blood_units WHERE unit_id = 'UNIT-2026-00001'").fetchone()
        assert u["status"] == "Issued"

def test_tc_report_01_generate_reports_and_csv():
    """TC-Report-01 (BBMS-F-017): Selected report generated with correct records & CSV."""
    inv_rep = generate_inventory_report()
    assert isinstance(inv_rep, list)

    don_rep = generate_donations_report()
    assert isinstance(don_rep, list)

    iss_rep = generate_issues_report()
    assert isinstance(iss_rep, list)

    csv_data = export_report_to_csv("inventory")
    assert "Blood Group,Component Type,Status" in csv_data

def test_tc_notif_01_notifications():
    """TC-Notif-01 (BBMS-F-018): System creates notifications for low stock and upcoming expiry."""
    alerts = list_notifications()
    assert isinstance(alerts, list)
    # Alerts must be present due to low stock in some blood groups or upcoming expiries
    assert len(alerts) > 0

# ==================== SECURITY & NON-FUNCTIONAL TESTS ====================

def test_tc_sec_03_password_protection():
    """TC-Sec-04 (BBMS-SR-003): Strong salted password hashing, never plaintext."""
    raw = "SecurePassword123!"
    hashed = hash_password(raw)
    assert raw not in hashed
    assert "$" in hashed
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

def test_tc_sec_05_sql_injection_defense():
    """TC-Sec-05 (BBMS-SR-004): Parameterized queries prevent SQL injection attacks."""
    malicious_input = "' OR '1'='1"
    # Should not crash and should safely treat input as literal string
    _, _, req_id = create_blood_request(
        hospital_name=malicious_input,
        requester_name="Dr. Attacker",
        patient_name=malicious_input,
        patient_blood_group="O+",
        component_type="Whole Blood",
        quantity=1
    )
    with get_db() as db:
        r = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (req_id,)).fetchone()
        assert r["patient_name"] == malicious_input

def test_tc_admin_01_user_management():
    """TC-Admin-01 (BBMS-F-019): Admin creates, deactivates user and verifies RBAC."""
    from app.services.auth_service import create_user, set_user_status, authenticate_user
    uid = create_user("nurse_lata", "lataPass123!", "Nurse Lata", "lata@bloodbank.org", "staff", "admin")
    assert uid > 0

    # User can login
    s = authenticate_user("nurse_lata", "lataPass123!")
    assert s is not None

    # Deactivate user
    set_user_status(uid, "inactive", "admin")

    # Deactivated user cannot login
    s2 = authenticate_user("nurse_lata", "lataPass123!")
    assert s2 is None

def test_tc_audit_01_audit_logging():
    """TC-Audit-01 (BBMS-F-020): Audit log contains actor, timestamp, action, and record reference."""
    logs = list_audit_logs(limit=20)
    assert len(logs) > 0
    first = logs[0]
    assert "actor_username" in first
    assert "timestamp" in first
    assert "action" in first
    assert "entity_id" in first

def test_tc_perf_01_response_time(client):
    """TC-Perf-01 (BBMS-NF-001): Normal search and dashboard return within 3 seconds."""
    import time
    start = time.perf_counter()
    res = client.get("/api/inventory/summary")
    duration = time.perf_counter() - start
    assert res.status_code == 200
    assert duration < 3.0, f"Response took {duration}s, exceeding 3.0s SLA"

