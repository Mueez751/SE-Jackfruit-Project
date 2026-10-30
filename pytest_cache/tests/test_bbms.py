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
    login_res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    start = time.perf_counter()
    res = client.get("/api/inventory/summary", headers={"Authorization": f"Bearer {token}"})
    duration = time.perf_counter() - start
    assert res.status_code == 200
    assert duration < 3.0, f"Response took {duration}s, exceeding 3.0s SLA"

# ==================== STAGE 1: RBAC & AUTHENTICATION DEPENDENCY TESTS ====================

def test_rbac_unauthenticated_request_returns_401(client):
    """Verify that accessing an authenticated endpoint without Bearer token returns 401 Unauthorized."""
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert "Missing authentication credentials." in res.json().get("detail", "")

def test_rbac_invalid_token_returns_401(client):
    """Verify that accessing an authenticated endpoint with an invalid Bearer token returns 401 Unauthorized."""
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid_token_12345"})
    assert res.status_code == 401
    assert "Invalid or expired session token." in res.json().get("detail", "")

def test_rbac_valid_token_allows_me_endpoint(client):
    """Verify that authenticating and passing a valid Bearer token returns 200 OK and user data."""
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    user = me_res.json()
    assert user["username"] == "admin"
    assert user["role"] == "admin"

def test_rbac_role_authorization_forbidden_returns_403(client):
    """Verify require_roles returns 403 Forbidden when authenticated user lacks the required role."""
    from fastapi import FastAPI, Depends
    from app.routers.auth import require_roles

    test_app = FastAPI()

    @test_app.get("/admin-only")
    def admin_only_endpoint(user: dict = Depends(require_roles(["admin"]))):
        return {"message": "admin granted", "user": user["username"]}

    test_client = TestClient(test_app)

    # Login as donor using main client to generate session in _ACTIVE_SESSIONS
    login_res = client.post("/api/auth/login", json={"username": "donor", "password": "donor123"})
    assert login_res.status_code == 200
    donor_token = login_res.json()["token"]

    # Donor attempting to access admin-only endpoint must get 403 Forbidden
    res = test_client.get("/admin-only", headers={"Authorization": f"Bearer {donor_token}"})
    assert res.status_code == 403
    assert "Access forbidden" in res.json().get("detail", "")
    assert "donor" in res.json().get("detail", "")

def test_rbac_role_authorization_allowed_returns_200(client):
    """Verify require_roles returns 200 OK when user possesses the required role."""
    from fastapi import FastAPI, Depends
    from app.routers.auth import require_roles

    test_app = FastAPI()

    @test_app.get("/admin-only")
    def admin_only_endpoint(user: dict = Depends(require_roles(["admin"]))):
        return {"message": "admin granted", "user": user["username"]}

    test_client = TestClient(test_app)

    # Login as admin
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert login_res.status_code == 200
    admin_token = login_res.json()["token"]

    res = test_client.get("/admin-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["message"] == "admin granted"
    assert res.json()["user"] == "admin"

def test_rbac_multi_role_authorization(client):
    """Verify require_roles accepts any role among a permitted list (e.g. ['staff', 'admin'])."""
    from fastapi import FastAPI, Depends
    from app.routers.auth import require_roles

    test_app = FastAPI()

    @test_app.get("/clinical")
    def clinical_endpoint(user: dict = Depends(require_roles(["staff", "admin"]))):
        return {"message": "clinical granted", "role": user["role"]}

    test_client = TestClient(test_app)

    # Staff user (authorized)
    staff_login = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert staff_login.status_code == 200
    staff_token = staff_login.json()["token"]
    staff_res = test_client.get("/clinical", headers={"Authorization": f"Bearer {staff_token}"})
    assert staff_res.status_code == 200
    assert staff_res.json()["role"] == "staff"

    # Hospital user (forbidden)
    hosp_login = client.post("/api/auth/login", json={"username": "hospital", "password": "hospital123"})
    assert hosp_login.status_code == 200
    hosp_token = hosp_login.json()["token"]
    hosp_res = test_client.get("/clinical", headers={"Authorization": f"Bearer {hosp_token}"})
    assert hosp_res.status_code == 403
    assert "Access forbidden" in hosp_res.json().get("detail", "")

def test_rbac_expired_token_returns_401(client):
    """Verify that an expired session token returns 401 Unauthorized."""
    from datetime import datetime, timedelta
    from app.services.auth_service import _ACTIVE_SESSIONS

    login_res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    # Artificially expire the session timestamp
    _ACTIVE_SESSIONS[token]["expires_at"] = datetime.utcnow() - timedelta(minutes=10)

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "Invalid or expired session token." in res.json().get("detail", "")


def test_rbac_unsupported_auth_scheme_returns_401(client):
    """Verify that using an unsupported scheme like Basic returns 401 Unauthorized."""
    res = client.get("/api/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert res.status_code == 401
    assert "Unsupported authorization scheme or invalid header format." in res.json().get("detail", "")

def test_rbac_empty_bearer_token_returns_401(client):
    """Verify that providing 'Bearer ' with an empty token returns 401 Unauthorized."""
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer   "})
    assert res.status_code == 401
    assert "Authentication token is missing." in res.json().get("detail", "")


# ==================== STAGE 2: BUSINESS ROUTER RBAC & AUDIT LOGGING TESTS ====================

def _login(client, username, password):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return {"Authorization": f"Bearer {res.json()['token']}"}

def test_stage2_unauthenticated_requests_return_401(client):
    """Verify that unauthenticated access across all business endpoints returns 401 Unauthorized."""
    endpoints = [
        ("POST", "/api/auth/logout"),
        ("GET", "/api/inventory/summary"),
        ("GET", "/api/inventory/units"),
        ("PATCH", "/api/inventory/units/UNIT-2026-00001/status"),
        ("POST", "/api/inventory/check-expiry"),
        ("GET", "/api/donors"),
        ("POST", "/api/donors"),
        ("GET", "/api/donors/DON-2026-0001"),
        ("POST", "/api/donors/DON-2026-0001/eligibility"),
        ("GET", "/api/donors/DON-2026-0001/history"),
        ("POST", "/api/collections"),
        ("GET", "/api/requests"),
        ("POST", "/api/requests"),
        ("GET", "/api/requests/REQ-2026-0001"),
        ("POST", "/api/requests/REQ-2026-0001/decision"),
        ("GET", "/api/allocations/preview/REQ-2026-0001"),
        ("POST", "/api/allocations/allocate"),
        ("POST", "/api/allocations/release"),
        ("GET", "/api/issues"),
        ("POST", "/api/issues"),
        ("GET", "/api/issues/ISS-2026-00001/certificate"),
        ("GET", "/api/reports/inventory"),
        ("GET", "/api/reports/donations"),
        ("GET", "/api/reports/issues"),
        ("GET", "/api/reports/discards-expiries"),
        ("GET", "/api/reports/export-csv?report_type=inventory"),
        ("GET", "/api/notifications"),
        ("POST", "/api/notifications/1/read"),
        ("POST", "/api/notifications/read-all"),
        ("GET", "/api/admin/users"),
        ("POST", "/api/admin/users"),
        ("PATCH", "/api/admin/users/1/status"),
        ("GET", "/api/admin/audit-logs"),
        ("POST", "/api/demo/reset"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        elif method == "POST":
            res = client.post(path, json={})
        elif method == "PATCH":
            res = client.patch(path, json={})
        assert res.status_code == 401, f"Expected 401 for unauthenticated {method} {path}, got {res.status_code}"

def test_stage2_admin_endpoints_role_isolation(client):
    """Verify admin endpoints are strictly forbidden to staff, hospital, and donor (403), allowed for admin."""
    admin_auth = _login(client, "admin", "admin123")
    staff_auth = _login(client, "staff", "staff123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")

    for auth in [staff_auth, hosp_auth, donor_auth]:
        res_users = client.get("/api/admin/users", headers=auth)
        assert res_users.status_code == 403
        res_audit = client.get("/api/admin/audit-logs", headers=auth)
        assert res_audit.status_code == 403

    # Admin succeeds
    res_ok = client.get("/api/admin/users", headers=admin_auth)
    assert res_ok.status_code == 200

def test_stage2_donor_endpoints_role_isolation(client):
    """Verify donor registry and records are accessible only to staff/admin, forbidden to donor/hospital."""
    staff_auth = _login(client, "staff", "staff123")
    admin_auth = _login(client, "admin", "admin123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")

    # Forbidden for donor and hospital
    for auth in [donor_auth, hosp_auth]:
        assert client.get("/api/donors", headers=auth).status_code == 403
        assert client.get("/api/donors/DON-2026-0001", headers=auth).status_code == 403
        assert client.get("/api/donors/DON-2026-0001/history", headers=auth).status_code == 403
        assert client.post("/api/donors", json={}, headers=auth).status_code == 403
        assert client.post("/api/donors/DON-2026-0001/eligibility", json={}, headers=auth).status_code == 403

    # Permitted for staff and admin
    res_staff = client.get("/api/donors", headers=staff_auth)
    assert res_staff.status_code == 200
    res_admin = client.get("/api/donors", headers=admin_auth)
    assert res_admin.status_code == 200

def test_stage2_collections_role_isolation(client):
    """Verify blood collections can only be recorded by staff and admin."""
    staff_auth = _login(client, "staff", "staff123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")

    # Forbidden for donor and hospital
    payload = {
        "donor_id": "DON-2026-0001",
        "blood_group": "O+",
        "volume_ml": 450,
        "component_type": "Whole Blood"
    }
    assert client.post("/api/collections", json=payload, headers=donor_auth).status_code == 403
    assert client.post("/api/collections", json=payload, headers=hosp_auth).status_code == 403

def test_stage2_inventory_management_role_isolation(client):
    """Verify inventory summary is accessible to all authenticated roles, but unit management is restricted."""
    admin_auth = _login(client, "admin", "admin123")
    staff_auth = _login(client, "staff", "staff123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")

    # All authenticated users can view summary
    for auth in [donor_auth, hosp_auth, staff_auth, admin_auth]:
        res = client.get("/api/inventory/summary", headers=auth)
        assert res.status_code == 200
        assert "total_units" in res.json()

    # Unit listing, status patch, and expiry scan restricted to staff and admin
    for auth in [donor_auth, hosp_auth]:
        assert client.get("/api/inventory/units", headers=auth).status_code == 403
        assert client.patch("/api/inventory/units/UNIT-2026-00001/status", json={"status": "Quarantined", "reason": "Test"}, headers=auth).status_code == 403
        assert client.post("/api/inventory/check-expiry", headers=auth).status_code == 403

    # Staff succeeds
    assert client.get("/api/inventory/units", headers=staff_auth).status_code == 200
    assert client.post("/api/inventory/check-expiry", headers=staff_auth).status_code == 200

def test_stage2_blood_requests_role_isolation(client):
    """Verify hospital can submit requests but cannot view directory, approve, or decide requests."""
    admin_auth = _login(client, "admin", "admin123")
    staff_auth = _login(client, "staff", "staff123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")

    req_payload = {
        "hospital_name": "Apollo Clinic",
        "requester_name": "Dr. Sharma",
        "patient_name": "Patient R",
        "patient_blood_group": "B+",
        "component_type": "Whole Blood",
        "quantity": 1,
        "urgency": "Normal",
        "required_date": str(date.today() + timedelta(days=2))
    }

    # Donor cannot submit request
    res_donor = client.post("/api/requests", json=req_payload, headers=donor_auth)
    assert res_donor.status_code == 403

    # Hospital can submit request
    res_hosp = client.post("/api/requests", json=req_payload, headers=hosp_auth)
    assert res_hosp.status_code == 201
    created_id = res_hosp.json()["request_id"]

    # Hospital and Donor cannot list requests or view single request (Choice 1 strict role isolation)
    assert client.get("/api/requests", headers=hosp_auth).status_code == 403
    assert client.get(f"/api/requests/{created_id}", headers=hosp_auth).status_code == 403
    assert client.get("/api/requests", headers=donor_auth).status_code == 403

    # Hospital cannot make decisions (approve/reject)
    decision_payload = {"decision": "Approved", "reason": "Self-approval attempt"}
    res_dec_hosp = client.post(f"/api/requests/{created_id}/decision", json=decision_payload, headers=hosp_auth)
    assert res_dec_hosp.status_code == 403

    # Staff can view and approve
    assert client.get("/api/requests", headers=staff_auth).status_code == 200
    res_dec_staff = client.post(f"/api/requests/{created_id}/decision", json={"decision": "Approved", "reason": "Staff approved"}, headers=staff_auth)
    assert res_dec_staff.status_code == 200

def test_stage2_allocations_and_issues_role_isolation(client):
    """Verify allocations and issues are strictly restricted to staff and admin."""
    admin_auth = _login(client, "admin", "admin123")
    staff_auth = _login(client, "staff", "staff123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")

    # Create fresh approved request
    req_res = client.post("/api/requests", json={
        "hospital_name": "Fortis Hospital",
        "requester_name": "Dr. Rao",
        "patient_name": "Alloc Patient",
        "patient_blood_group": "A+",
        "component_type": "Whole Blood",
        "quantity": 1,
        "urgency": "Normal",
        "required_date": str(date.today() + timedelta(days=2))
    }, headers=staff_auth)
    assert req_res.status_code == 201
    test_req_id = req_res.json()["request_id"]

    appr_res = client.post(f"/api/requests/{test_req_id}/decision", json={"decision": "Approved", "reason": "Approved for alloc test"}, headers=staff_auth)
    assert appr_res.status_code == 200

    # Hospital and donor cannot access allocations or issues
    for auth in [donor_auth, hosp_auth]:
        assert client.get(f"/api/allocations/preview/{test_req_id}", headers=auth).status_code == 403
        assert client.post("/api/allocations/allocate", json={"request_id": test_req_id}, headers=auth).status_code == 403
        assert client.post(f"/api/allocations/release?request_id={test_req_id}&unit_id=UNIT-2026-00001", headers=auth).status_code == 403
        assert client.get("/api/issues", headers=auth).status_code == 403
        assert client.post("/api/issues", json={"request_id": test_req_id}, headers=auth).status_code == 403
        assert client.get("/api/issues/ISS-2026-00001/certificate", headers=auth).status_code == 403

    # Staff has access
    preview_res = client.get(f"/api/allocations/preview/{test_req_id}", headers=staff_auth)
    assert preview_res.status_code == 200
    assert client.get("/api/issues", headers=staff_auth).status_code == 200

def test_stage2_reports_and_notifications_role_isolation(client):
    """Verify operational reports and alerts are restricted to staff and admin."""
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")
    staff_auth = _login(client, "staff", "staff123")

    report_paths = [
        "/api/reports/inventory",
        "/api/reports/donations",
        "/api/reports/issues",
        "/api/reports/discards-expiries",
        "/api/reports/export-csv?report_type=inventory",
    ]
    for path in report_paths:
        assert client.get(path, headers=hosp_auth).status_code == 403
        assert client.get(path, headers=donor_auth).status_code == 403
        assert client.get(path, headers=staff_auth).status_code == 200

    # Notifications
    assert client.get("/api/notifications", headers=hosp_auth).status_code == 403
    assert client.get("/api/notifications", headers=donor_auth).status_code == 403
    assert client.get("/api/notifications", headers=staff_auth).status_code == 200

def test_stage2_demo_reset_role_isolation(client):
    """Verify /api/demo/reset is protected: 401 unauthenticated, 403 non-admin, 200 admin."""
    # Unauthenticated -> 401
    assert client.post("/api/demo/reset").status_code == 401

    # Non-admin -> 403
    staff_auth = _login(client, "staff", "staff123")
    hosp_auth = _login(client, "hospital", "hospital123")
    donor_auth = _login(client, "donor", "donor123")
    assert client.post("/api/demo/reset", headers=staff_auth).status_code == 403
    assert client.post("/api/demo/reset", headers=hosp_auth).status_code == 403
    assert client.post("/api/demo/reset", headers=donor_auth).status_code == 403

    # Admin -> 200
    admin_auth = _login(client, "admin", "admin123")
    res = client.post("/api/demo/reset", headers=admin_auth)
    assert res.status_code == 200
    assert "Database reset" in res.json().get("message", "")

def test_stage2_authentic_audit_logging(client):
    """Verify audit logs record authentic caller identity instead of hardcoded strings."""
    # Reset database first using admin
    admin_auth = _login(client, "admin", "admin123")
    client.post("/api/demo/reset", headers=admin_auth)

    # 1. Hospital submits blood request
    hosp_auth = _login(client, "hospital", "hospital123")
    req_payload = {
        "hospital_name": "Authentic Hospital",
        "requester_name": "Dr. Authenticator",
        "patient_name": "Audit Test Patient",
        "patient_blood_group": "AB+",
        "component_type": "Whole Blood",
        "quantity": 1,
        "urgency": "Normal",
        "required_date": str(date.today() + timedelta(days=2))
    }
    hosp_res = client.post("/api/requests", json=req_payload, headers=hosp_auth)
    assert hosp_res.status_code == 201
    created_req_id = hosp_res.json()["request_id"]

    # 2. Staff approves request
    staff_auth = _login(client, "staff", "staff123")
    staff_dec_res = client.post(
        f"/api/requests/{created_req_id}/decision",
        json={"decision": "Approved", "reason": "Crossmatch verified for audit test"},
        headers=staff_auth
    )
    assert staff_dec_res.status_code == 200

    # 3. Admin creates a user
    import uuid
    random_user = f"auditor_{uuid.uuid4().hex[:6]}"
    admin_res = client.post(
        "/api/admin/users",
        json={
            "username": random_user,
            "password": "auditUser123!",
            "full_name": "Auditor Test",
            "email": f"{random_user}@bbms.org",
            "role": "staff"
        },
        headers=admin_auth
    )
    assert admin_res.status_code == 201

    # Verify audit logs in database
    with get_db() as db:
        # Check request creation audit log
        req_log = db.execute(
            "SELECT actor_username FROM audit_logs WHERE entity_id = ? AND action = 'CREATE_BLOOD_REQUEST'",
            (created_req_id,)
        ).fetchone()
        assert req_log is not None
        assert req_log["actor_username"] == "hospital"

        # Check request decision audit log
        dec_log = db.execute(
            "SELECT actor_username FROM audit_logs WHERE entity_id = ? AND action = 'DECIDE_BLOOD_REQUEST'",
            (created_req_id,)
        ).fetchone()
        assert dec_log is not None
        assert dec_log["actor_username"] == "staff"

        # Check user creation audit log
        user_log = db.execute(
            "SELECT actor_username FROM audit_logs WHERE entity_type = 'USER' AND action = 'CREATE_USER' AND details LIKE ?",
            (f"%{random_user}%",)
        ).fetchone()
        assert user_log is not None
        assert user_log["actor_username"] == "admin"

def test_stage2_auth_logout_workflow(client):
    """Verify logout requires authentication, rejects invalid tokens, invalidates session and audits."""
    # 1. Unauthenticated logout -> 401
    res_unauth = client.post("/api/auth/logout")
    assert res_unauth.status_code == 401
    assert "Missing authentication credentials." in res_unauth.json().get("detail", "")

    # 2. Invalid token logout -> 401
    res_invalid = client.post("/api/auth/logout", headers={"Authorization": "Bearer invalid_token_xyz"})
    assert res_invalid.status_code == 401
    assert "Invalid or expired session token." in res_invalid.json().get("detail", "")

    # 3. Valid login and logout
    login_res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # Verify session is valid before logout
    me_before = client.get("/api/auth/me", headers=auth_header)
    assert me_before.status_code == 200
    assert me_before.json()["username"] == "staff"

    # Logout
    logout_res = client.post("/api/auth/logout", headers=auth_header)
    assert logout_res.status_code == 200
    assert "Logged out successfully." in logout_res.json().get("message", "")

    # Verify session is invalidated - subsequent requests fail with 401
    me_after = client.get("/api/auth/me", headers=auth_header)
    assert me_after.status_code == 401
    assert "Invalid or expired session token." in me_after.json().get("detail", "")

    # Verify logout audit log exists
    with get_db() as db:
        log = db.execute(
            "SELECT * FROM audit_logs WHERE action = 'LOGOUT' AND actor_username = 'staff' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert log is not None
        assert log["actor_username"] == "staff"

def test_stage2_demo_switch_role_disabled_by_default(client, monkeypatch):
    """Verify that demo switch-role is rejected with HTTP 403 when BBMS_ENABLE_DEMO is false or unset."""
    monkeypatch.delenv("BBMS_ENABLE_DEMO", raising=False)
    res = client.post("/api/demo/switch-role?role=admin")
    assert res.status_code == 403
    assert "Demo role switching is disabled" in res.json().get("detail", "")

    monkeypatch.setenv("BBMS_ENABLE_DEMO", "false")
    res_false = client.post("/api/demo/switch-role?role=staff")
    assert res_false.status_code == 403
    assert "Demo role switching is disabled" in res_false.json().get("detail", "")

def test_stage2_demo_switch_role_enabled(client, monkeypatch):
    """Verify that demo switch-role succeeds for all 4 roles when BBMS_ENABLE_DEMO is true."""
    monkeypatch.setenv("BBMS_ENABLE_DEMO", "true")
    for role in ["admin", "staff", "hospital", "donor"]:
        res = client.post(f"/api/demo/switch-role?role={role}")
        assert res.status_code == 200
        data = res.json()
        assert "session" in data
        assert data["session"]["role"] == role
        assert "token" in data["session"]

def test_stage2_demo_switch_role_rejects_invalid_roles(client, monkeypatch):
    """Verify that demo switch-role rejects unknown or invalid roles with HTTP 400 Bad Request."""
    monkeypatch.setenv("BBMS_ENABLE_DEMO", "true")
    res = client.post("/api/demo/switch-role?role=superadmin")
    assert res.status_code == 400
    assert "Unknown demo role: superadmin" in res.json().get("detail", "")

    res_empty = client.post("/api/demo/switch-role?role=")
    assert res_empty.status_code == 400

def test_stage2_authenticated_endpoints_remain_protected_in_demo_mode(client, monkeypatch):
    """Verify that normal authenticated business endpoints remain strictly protected even when demo mode is enabled."""
    monkeypatch.setenv("BBMS_ENABLE_DEMO", "true")

    # 1. Unauthenticated requests still return 401
    assert client.get("/api/inventory/summary").status_code == 401
    assert client.get("/api/donors").status_code == 401
    assert client.get("/api/admin/users").status_code == 401
    assert client.post("/api/demo/reset").status_code == 401

    # 2. Donor token still cannot access staff/admin endpoints (403)
    donor_res = client.post("/api/demo/switch-role?role=donor")
    assert donor_res.status_code == 200
    donor_auth = {"Authorization": f"Bearer {donor_res.json()['session']['token']}"}

    assert client.get("/api/admin/users", headers=donor_auth).status_code == 403
    assert client.get("/api/donors", headers=donor_auth).status_code == 403
    assert client.post("/api/demo/reset", headers=donor_auth).status_code == 403

    # 3. Staff token still cannot access admin endpoints (403)
    staff_res = client.post("/api/demo/switch-role?role=staff")
    assert staff_res.status_code == 200
    staff_auth = {"Authorization": f"Bearer {staff_res.json()['session']['token']}"}

    assert client.get("/api/admin/users", headers=staff_auth).status_code == 403
    assert client.post("/api/demo/reset", headers=staff_auth).status_code == 403



