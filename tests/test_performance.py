"""
BBMS Stage 3: Automated Performance Testing Suite.
Verifies compliance with Non-Functional Requirement BBMS-NF-001:
'The system shall return normal search, form submission, and dashboard requests within 3 seconds for at least 95% of requests under normal expected load.'
Covers:
- Preserved TC-Perf-01 baseline test
- Repeated sequential request latency distributions (min, mean, p50, p95, p99, max)
- Concurrent read workloads (concurrency 5, 10)
- Concurrent write workloads (ACID transaction lock integrity)
- Authentication workload (PBKDF2 key derivation vs. O(1) in-memory session token lookup)
- Live HTTP server over real TCP loopback vs. In-process ASGI TestClient
- HTTP response time middleware header ('X-Process-Time-Sec') verification
- Unrelated UNIQUE constraint classification and immediate non-retry verification
"""

import os
import sys
import uuid
import pytest
from datetime import date

# Ensure app is discoverable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import get_db, init_db
from app.seed_data import seed_database
from fastapi.testclient import TestClient

from tests.perf_runner import (
    obtain_auth_tokens,
    run_sequential_benchmark,
    run_concurrent_read_benchmark,
    run_concurrent_write_benchmark,
    run_auth_performance_benchmark,
    run_live_http_benchmarks,
    compute_metrics,
    get_system_environment_info,
    escape_sql_like
)


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown_perf_db():
    """Ensure clean seeded database before and after performance testing module."""
    init_db()
    seed_database(force=True)
    yield
    # Reseed cleanly on teardown
    init_db()
    seed_database(force=True)


@pytest.fixture
def client():
    return TestClient(app)


# ==================== 1. PRESERVED BASELINE PERFORMANCE TEST ====================

def test_tc_perf_01_response_time_preserved(client):
    """
    TC-Perf-01 (BBMS-NF-001): Preserved original response time test.
    Normal search and dashboard return within 3 seconds.
    """
    import time
    login_res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    start = time.perf_counter()
    res = client.get("/api/inventory/summary", headers={"Authorization": f"Bearer {token}"})
    duration = time.perf_counter() - start
    assert res.status_code == 200
    assert duration < 3.0, f"Response took {duration}s, exceeding 3.0s SLA"


# ==================== 2. REPEATED SEQUENTIAL REQUEST BENCHMARKS ====================

def test_perf_sequential_baseline_endpoints(client):
    """
    Benchmark repeated sequential requests (N=30 each) across key business endpoints.
    Calculates min, mean, p50, p95, p99, and verifies p95 <= 3.0s with 0% error rate.
    """
    tokens = obtain_auth_tokens(client)
    staff_headers = {"Authorization": f"Bearer {tokens['staff']}"}

    test_targets = [
        ("GET", "/api/auth/me", staff_headers, None, 200, "GET /api/auth/me"),
        ("GET", "/api/inventory/summary", staff_headers, None, 200, "GET /api/inventory/summary"),
        ("GET", "/api/inventory/units?status=Available&blood_group=O+", staff_headers, None, 200, "GET /api/inventory/units"),
        ("GET", "/api/donors?search=Rahul&blood_group=O+", staff_headers, None, 200, "GET /api/donors"),
        ("GET", "/api/donors/DON-2026-0001/history", staff_headers, None, 200, "GET /api/donors/{id}/history"),
        ("GET", "/api/requests?urgency=Emergency&status=Pending", staff_headers, None, 200, "GET /api/requests"),
        ("GET", "/api/reports/inventory", staff_headers, None, 200, "GET /api/reports/inventory"),
        ("GET", "/api/reports/export-csv?report_type=inventory", staff_headers, None, 200, "GET /api/reports/export-csv"),
    ]

    for method, path, hdrs, jdata, exp_st, name in test_targets:
        metrics = run_sequential_benchmark(
            client=client,
            method=method,
            path=path,
            headers=hdrs,
            json_data=jdata,
            iterations=30,
            expected_status=exp_st,
            name=name
        )

        assert metrics["errors"] == 0, f"{name} encountered {metrics['errors']} errors: {metrics['error_details']}"
        assert metrics["p95_sec"] <= 3.0, f"{name} p95 latency {metrics['p95_sec']:.4f}s exceeded 3.0s SLA"
        assert metrics["max_sec"] <= 3.0, f"{name} max latency {metrics['max_sec']:.4f}s exceeded 3.0s SLA"
        assert metrics["max_sec"] >= metrics["p99_sec"] >= metrics["p95_sec"], (
            f"{name} latency ordering violation: max={metrics['max_sec']}, p99={metrics['p99_sec']}, p95={metrics['p95_sec']}"
        )
        assert metrics["compliance_pct"] == 100.0, f"{name} compliance {metrics['compliance_pct']}% != 100%"
        assert all(lat <= 3.0 for lat in metrics["latencies"]), f"{name} individual request exceeded 3.0s SLA"
        assert metrics["sla_passed"] is True
        assert metrics["rps"] > 0.0


# ==================== 3. CONCURRENT READ WORKLOADS ====================

def test_perf_concurrent_read_workloads(client):
    """
    Execute concurrent read workloads across a thread pool (Concurrency C=10, 40 requests each).
    Verifies that SQLite WAL mode permits concurrent readers without degradation or locking errors.
    """
    tokens = obtain_auth_tokens(client)
    staff_headers = {"Authorization": f"Bearer {tokens['staff']}"}

    endpoints = [
        ("/api/inventory/summary", "GET /api/inventory/summary"),
        ("/api/donors?search=Rahul", "GET /api/donors (Search)"),
        ("/api/requests?urgency=Emergency", "GET /api/requests (Filter)"),
        ("/api/reports/inventory", "GET /api/reports/inventory"),
    ]

    for path, name in endpoints:
        metrics = run_concurrent_read_benchmark(
            client=client,
            method="GET",
            path=path,
            headers=staff_headers,
            total_requests=40,
            concurrency=10,
            name=name
        )

        assert metrics["errors"] == 0, f"{name} concurrent read errors: {metrics['error_details']}"
        assert metrics["p95_sec"] <= 3.0, f"{name} concurrent read p95 {metrics['p95_sec']:.4f}s exceeded 3.0s SLA"
        assert metrics["max_sec"] <= 3.0, f"{name} concurrent read max {metrics['max_sec']:.4f}s exceeded 3.0s SLA"
        assert metrics["max_sec"] >= metrics["p99_sec"] >= metrics["p95_sec"], (
            f"{name} latency ordering violation: max={metrics['max_sec']}, p99={metrics['p99_sec']}, p95={metrics['p95_sec']}"
        )
        assert metrics["compliance_pct"] == 100.0, f"{name} compliance {metrics['compliance_pct']}% != 100%"
        assert all(lat <= 3.0 for lat in metrics["latencies"]), f"{name} individual request exceeded 3.0s SLA"
        assert metrics["sla_passed"] is True
        assert metrics["rps"] >= 20.0, f"Expected throughput >= 20 RPS, got {metrics['rps']:.1f}"


# ==================== 4. CONCURRENT WRITE WORKLOADS ====================

def test_perf_concurrent_write_workloads(client):
    """
    Execute concurrent write operations (POST /api/requests) under thread pool contention (C=5, 20 requests).
    Verifies SQLite ACID locking safety, absence of unhandled lock timeouts, and thread-safe ID allocation.
    Also verifies non-destructive cleanup: benchmark records are removed, while pre-existing audit logs are preserved.
    """
    import uuid
    tokens = obtain_auth_tokens(client)
    hospital_headers = {"Authorization": f"Bearer {tokens['hospital']}"}

    # 1. Pre-seed an unrelated hospital audit record to prove non-destructive cleanup
    unrelated_marker = f"HOSPITAL_AUDIT_PRESERVE_{uuid.uuid4().hex[:6]}"
    with get_db() as db:
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details)
            VALUES ('hospital', 'hospital', 'CREATE_BLOOD_REQUEST', 'BLOOD_REQUEST', 'REQ-PRE-EXISTING', ?)
            """,
            (unrelated_marker,)
        )

    # 2. Pre-seed a benchmark request record and an associated audit log WITHOUT run_tag in details
    custom_run_tag = f"PERF_WRITE_TAG_{uuid.uuid4().hex[:6]}"
    custom_req_id = f"REQ-CUSTOM-{uuid.uuid4().hex[:6]}"
    with get_db() as db:
        db.execute(
            """
            INSERT INTO blood_requests (
                request_id, hospital_name, requester_name, patient_name,
                patient_blood_group, component_type, quantity, urgency,
                required_date, status
            )
            VALUES (?, 'City Care Hospital', 'Dr. Benchmark', ?, 'A+', 'Whole Blood', 1, 'Normal', '2026-11-20', 'Pending')
            """,
            (custom_req_id, f"{custom_run_tag}_preseed")
        )
        # Note: details does NOT contain custom_run_tag; it is associated strictly by entity_id
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details)
            VALUES ('hospital', 'hospital', 'DISPATCH_VERIFICATION', 'BLOOD_REQUEST', ?, 'Standard dispatch verification with NO run tag text')
            """,
            (custom_req_id,)
        )

    # 3. Pre-seed an unrelated patient whose name has wildcard character similarity (replacing underscore with 'X')
    wildcard_trick_id = f"REQ-WILDCARD-{uuid.uuid4().hex[:6]}"
    wildcard_patient = custom_run_tag.replace("_", "X", 1) + "_patient"
    with get_db() as db:
        db.execute(
            """
            INSERT INTO blood_requests (
                request_id, hospital_name, requester_name, patient_name,
                patient_blood_group, component_type, quantity, urgency,
                required_date, status
            )
            VALUES (?, 'St. Jude Hospital', 'Dr. External', ?, 'B+', 'Whole Blood', 1, 'Normal', '2026-11-20', 'Pending')
            """,
            (wildcard_trick_id, wildcard_patient)
        )

    try:
        metrics = run_concurrent_write_benchmark(
            client=client,
            headers=hospital_headers,
            total_requests=20,
            concurrency=5,
            name="POST /api/requests (Concurrent Writes)",
            run_tag=custom_run_tag
        )

        assert metrics["errors"] == 0, f"Concurrent writes failed with errors: {metrics['error_details']}"
        assert metrics["p95_sec"] <= 3.0, f"Concurrent write p95 {metrics['p95_sec']:.4f}s exceeded 3.0s SLA"
        assert metrics["max_sec"] <= 3.0, f"Concurrent write max {metrics['max_sec']:.4f}s exceeded 3.0s SLA"
        assert metrics["max_sec"] >= metrics["p99_sec"] >= metrics["p95_sec"], (
            f"Concurrent write latency ordering violation: max={metrics['max_sec']}, p99={metrics['p99_sec']}, p95={metrics['p95_sec']}"
        )
        assert metrics["compliance_pct"] == 100.0, f"Concurrent write compliance {metrics['compliance_pct']}% != 100%"
        assert all(lat <= 3.0 for lat in metrics["latencies"]), "Concurrent write individual request exceeded 3.0s SLA"
        assert metrics["sla_passed"] is True
        assert metrics["completed"] == 20

        # 4. Verify that the audit record associated with custom_req_id (without run tag in details) was cleanly removed by entity_id cleanup
        with get_db() as db:
            row_custom_audit = db.execute("SELECT * FROM audit_logs WHERE entity_id = ?", (custom_req_id,)).fetchone()
            assert row_custom_audit is None, "Audit record associated with benchmark request ID was NOT removed by entity_id cleanup"

            row_custom_req = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (custom_req_id,)).fetchone()
            assert row_custom_req is None, "Benchmark blood request was NOT removed by cleanup"

            # 5. Verify unrelated pre-existing hospital audit log remains completely untouched
            row = db.execute("SELECT * FROM audit_logs WHERE details = ?", (unrelated_marker,)).fetchone()
            assert row is not None, "Unrelated pre-existing hospital audit log was incorrectly removed by cleanup"

            # 6. Verify unrelated blood request with wildcard similarity survived without accidental matching
            row_wildcard = db.execute("SELECT * FROM blood_requests WHERE request_id = ?", (wildcard_trick_id,)).fetchone()
            assert row_wildcard is not None, "Unrelated blood request was incorrectly removed due to SQL LIKE wildcard matching"

        # 7. Verify that cleanup failure reporting prevents an entirely successful run
        fail_metric = compute_metrics(
            name="test_cleanup_fail",
            harness="TestClient",
            category="Concurrent Write",
            concurrency=1,
            latencies=[0.05],
            total_time_sec=0.1,
            errors=1,
            error_details=["Cleanup failure: Simulated lock error"]
        )
        assert fail_metric["errors"] == 1
        assert fail_metric["sla_passed"] is False
        assert "Cleanup failure" in fail_metric["error_details"][0]

    finally:
        with get_db() as db:
            db.execute("DELETE FROM audit_logs WHERE details = ?", (unrelated_marker,))
            db.execute("DELETE FROM audit_logs WHERE entity_id = ?", (custom_req_id,))
            db.execute("DELETE FROM blood_requests WHERE request_id = ?", (custom_req_id,))
            db.execute("DELETE FROM blood_requests WHERE request_id = ?", (wildcard_trick_id,))


def test_perf_concurrent_write_cleanup_exception_handling(client, monkeypatch):
    """
    BBMS-NF-001 / Issue #25: Genuine cleanup exception handling test.
    Triggers a controlled database exception during the cleanup phase of
    run_concurrent_write_benchmark() using monkeypatch.
    Verifies that:
    1. The exception is caught by the real cleanup exception handler.
    2. errors increases.
    3. error_details contains the descriptive cleanup failure.
    4. sla_passed evaluates to False.
    5. All patched behavior is restored and test records are cleaned up cleanly.
    """
    import unittest.mock
    import contextlib
    import sqlite3
    import tests.perf_runner

    tokens = obtain_auth_tokens(client)
    hospital_headers = {"Authorization": f"Bearer {tokens['hospital']}"}
    fail_run_tag = f"CLEANUP_EXC_{uuid.uuid4().hex[:6]}"

    real_get_db = tests.perf_runner.get_db

    @contextlib.contextmanager
    def faulty_cleanup_get_db(*args, **kwargs):
        with real_get_db(*args, **kwargs) as real_db:
            mock_db = unittest.mock.MagicMock(wraps=real_db)
            def faulty_execute(sql, *exec_args, **exec_kwargs):
                if "blood_requests" in sql or "audit_logs" in sql:
                    raise sqlite3.OperationalError("Simulated database lock during cleanup execution")
                return real_db.execute(sql, *exec_args, **exec_kwargs)
            mock_db.execute.side_effect = faulty_execute
            yield mock_db

    monkeypatch.setattr("tests.perf_runner.get_db", faulty_cleanup_get_db)

    try:
        # Run concurrent write benchmark through the real cleanup exception handler
        metrics = run_concurrent_write_benchmark(
            client=client,
            headers=hospital_headers,
            total_requests=4,
            concurrency=2,
            name="POST /api/requests (Cleanup Exception Test)",
            run_tag=fail_run_tag
        )

        # 1. Verify errors increased due to the cleanup failure
        assert metrics["errors"] >= 1, f"Expected cleanup failure to increment errors, got {metrics['errors']}"

        # 2. Verify error_details contains the cleanup failure message
        assert any("Cleanup failure: Simulated database lock during cleanup execution" in err for err in metrics["error_details"]), (
            f"Expected cleanup failure in error_details, got {metrics['error_details']}"
        )

        # 3. Verify that sla_passed is False
        assert metrics["sla_passed"] is False, "Expected sla_passed to be False when cleanup fails"
        assert metrics["error_rate_pct"] > 0.0

    finally:
        # Restore patched get_db
        monkeypatch.undo()

        # Clean up all created test records using the restored real database connection
        with real_get_db() as db:
            escaped_tag = escape_sql_like(fail_run_tag)
            rows = db.execute(
                "SELECT request_id FROM blood_requests WHERE patient_name LIKE ? ESCAPE '\\'",
                (f"{escaped_tag}%",)
            ).fetchall()
            req_ids = [r["request_id"] for r in rows]
            if req_ids:
                placeholders = ",".join("?" for _ in req_ids)
                db.execute(f"DELETE FROM blood_requests WHERE request_id IN ({placeholders})", req_ids)
                db.execute(f"DELETE FROM audit_logs WHERE entity_id IN ({placeholders})", req_ids)
            db.execute("DELETE FROM audit_logs WHERE details LIKE ? ESCAPE '\\'", (f"%{escaped_tag}%",))

        # Assert database is left completely clean
        with real_get_db() as db:
            rem = db.execute(
                "SELECT COUNT(*) as c FROM blood_requests WHERE patient_name LIKE ? ESCAPE '\\'",
                (f"{escaped_tag}%",)
            ).fetchone()["c"]
            assert rem == 0, f"Dangling blood requests remained after cleanup: {rem}"


# ==================== 5. AUTHENTICATION PERFORMANCE WORKLOAD ====================

def test_perf_auth_pbkdf2_and_token_lookup(client):
    """
    Measure and compare authentication performance:
    1. POST /api/auth/login: CPU-intensive PBKDF2 hashing (100,000 iterations per BBMS-SR-003).
       Assert p95 < 1.0s (deliberate hashing delay, but strictly sub-second).
    2. GET /api/auth/me: In-memory session token lookup (O(1)).
       Assert p95 < 0.05s (sub-50ms high-speed cached authorization).
    """
    results = run_auth_performance_benchmark(client, iterations=25)
    m_login, m_me = results[0], results[1]

    # Verify Login PBKDF2 performance
    assert m_login["errors"] == 0
    assert m_login["p95_sec"] <= 1.0, f"Login PBKDF2 p95 {m_login['p95_sec']:.4f}s exceeded 1.0s threshold"
    assert m_login["max_sec"] <= 3.0, f"Login PBKDF2 max {m_login['max_sec']:.4f}s exceeded 3.0s SLA"
    assert m_login["max_sec"] >= m_login["p99_sec"] >= m_login["p95_sec"], "Login PBKDF2 ordering violation"
    assert m_login["compliance_pct"] == 100.0
    assert all(lat <= 3.0 for lat in m_login["latencies"])
    assert m_login["sla_passed"] is True

    # Verify In-memory Token lookup performance
    assert m_me["errors"] == 0
    assert m_me["p95_sec"] <= 0.05, f"Token lookup p95 {m_me['p95_sec']:.4f}s exceeded 0.05s threshold"
    assert m_me["max_sec"] <= 3.0, f"Token lookup max {m_me['max_sec']:.4f}s exceeded 3.0s SLA"
    assert m_me["max_sec"] >= m_me["p99_sec"] >= m_me["p95_sec"], "Token lookup ordering violation"
    assert m_me["compliance_pct"] == 100.0
    assert all(lat <= 3.0 for lat in m_me["latencies"])
    assert m_me["sla_passed"] is True

    # Ratio check: In-memory token lookup should be significantly faster than cryptographic password hashing
    assert m_me["mean_sec"] < m_login["mean_sec"], "Token session lookup should be faster than PBKDF2 login"


# ==================== 6. LIVE HTTP SERVER COMPARISON ====================

def test_perf_live_http_server_comparison():
    """
    Launch a real Uvicorn server on a dynamically assigned loopback port.
    Execute concurrent HTTP requests over real TCP sockets using httpx.
    Validates that live networking and socket I/O also comfortably satisfy the 3.0s SLA.
    """
    live_results = run_live_http_benchmarks(requests_per_endpoint=20, concurrency=5)
    assert len(live_results) > 0, "Live server benchmark returned no results"

    for m in live_results:
        assert m["errors"] == 0, f"Live HTTP {m['name']} encountered errors: {m['error_details']}"
        assert m["p95_sec"] <= 3.0, f"Live HTTP {m['name']} p95 {m['p95_sec']:.4f}s exceeded 3.0s SLA"
        assert m["max_sec"] <= 3.0, f"Live HTTP {m['name']} max {m['max_sec']:.4f}s exceeded 3.0s SLA"
        assert m["max_sec"] >= m["p99_sec"] >= m["p95_sec"], (
            f"Live HTTP latency ordering violation: max={m['max_sec']}, p99={m['p99_sec']}, p95={m['p95_sec']}"
        )
        assert m["compliance_pct"] == 100.0, f"Live HTTP compliance {m['compliance_pct']}% != 100%"
        assert all(lat <= 3.0 for lat in m["latencies"]), f"Live HTTP {m['name']} request exceeded 3.0s SLA"
        assert m["sla_passed"] is True


# ==================== 7. BBMS-NF-001 OVERALL COMPLIANCE ====================

def test_perf_bbms_nf_001_overall_compliance(client):
    """
    Aggregate verification of Non-Functional Requirement BBMS-NF-001:
    Verifies that >= 95% of all operations across the standard performance suite complete within 3.0 seconds,
    and strictly enforces Issue #25 (100% of measured requests <= 3.0 seconds).
    """
    tokens = obtain_auth_tokens(client)
    staff_headers = {"Authorization": f"Bearer {tokens['staff']}"}

    sample_latencies = []
    import time
    for path in ["/api/inventory/summary", "/api/donors", "/api/requests", "/api/reports/inventory"]:
        for _ in range(15):
            t0 = time.perf_counter()
            r = client.get(path, headers=staff_headers)
            sample_latencies.append(time.perf_counter() - t0)
            assert r.status_code == 200

    import numpy as np
    arr = np.array(sample_latencies)
    p50 = float(np.percentile(arr, 50))
    p95 = float(np.percentile(arr, 95))
    p99 = float(np.percentile(arr, 99))
    max_latency = float(np.max(arr))
    within_3s_count = sum(1 for dt in sample_latencies if dt <= 3.0)
    compliance_pct = (within_3s_count / len(sample_latencies)) * 100.0

    # 1. Preserve SRS BBMS-NF-001 check (>= 95.0% and p95 <= 3.0s)
    assert compliance_pct >= 95.0, f"SRS compliance {compliance_pct:.1f}% is below 95% threshold"
    assert p95 <= 3.0, f"Overall p95 {p95:.4f}s exceeded 3.0s SLA"

    # 2. Strict Issue #25 check (100% of measured requests <= 3.0s, max <= 3.0s)
    assert compliance_pct == 100.0, f"Strict Issue #25 compliance expected 100%, got {compliance_pct:.1f}%"
    assert max_latency <= 3.0, f"Maximum observed latency {max_latency:.4f}s exceeded 3.0s SLA"
    assert all(dt <= 3.0 for dt in sample_latencies), "Individual request in overall compliance exceeded 3.0s SLA"
    assert max_latency >= p99 >= p95 >= p50, (
        f"Percentile ordering violated: max={max_latency}, p99={p99}, p95={p95}, p50={p50}"
    )
    assert p50 <= p95 <= p99 <= max_latency <= 3.0, "Percentiles must satisfy p50 <= p95 <= p99 <= max <= 3.0s"


# ==================== 8. PERFORMANCE MONITORING MIDDLEWARE HEADER ====================

def test_perf_middleware_timing_header_presence(client):
    """
    Verify that the HTTP performance middleware records request execution latency
    in the 'X-Process-Time-Sec' response header per requirement BBMS-NF-001.
    Checks header presence, format, and that measured duration is a valid positive float <= 3.0s.
    """
    # 1. Public endpoint test
    doc_res = client.get("/docs")
    assert doc_res.status_code == 200
    assert "x-process-time-sec" in doc_res.headers
    doc_time = float(doc_res.headers["x-process-time-sec"])
    assert 0.0 <= doc_time <= 3.0

    # 2. Authenticated endpoint test
    login_res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert login_res.status_code == 200
    assert "x-process-time-sec" in login_res.headers
    login_time = float(login_res.headers["x-process-time-sec"])
    assert 0.0 <= login_time <= 3.0

    token = login_res.json()["token"]
    inv_res = client.get("/api/inventory/summary", headers={"Authorization": f"Bearer {token}"})
    assert inv_res.status_code == 200
    assert "x-process-time-sec" in inv_res.headers
    inv_time = float(inv_res.headers["x-process-time-sec"])
    assert 0.0 <= inv_time <= 3.0


# ==================== 9. INTEGRITY ERROR CLASSIFICATION TEST ====================

def test_unrelated_unique_constraint_failure_not_retried():
    """
    Verify that an unrelated UNIQUE constraint violation (not on request_id)
    is NEVER misclassified as a request ID collision and is NOT retried.
    Must immediately return an explicit database integrity failure without retry delay.
    """
    import time
    from app.services.request_service import create_blood_request

    # Temporarily create an unrelated unique constraint on patient_name
    with get_db() as db:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_test_unique_patient ON blood_requests(patient_name);")

    test_patient = "Patient_Unrelated_Unique_SLA_Test"
    try:
        # First request succeeds
        ok1, err1, req1 = create_blood_request(
            hospital_name="St. Mary Hospital",
            requester_name="Dr. Smith",
            patient_name=test_patient,
            patient_blood_group="O+",
            component_type="Whole Blood",
            quantity=1
        )
        assert ok1 is True
        assert req1 is not None

        # Second request with identical patient_name causes UNIQUE constraint failure on patient_name
        t0 = time.perf_counter()
        ok2, err2, req2 = create_blood_request(
            hospital_name="St. Mary Hospital",
            requester_name="Dr. Smith",
            patient_name=test_patient,
            patient_blood_group="O+",
            component_type="Whole Blood",
            quantity=1
        )
        elapsed = time.perf_counter() - t0

        # Must fail immediately on first attempt without executing 15 retry sleep cycles (>1.0s)
        assert ok2 is False
        assert req2 is None
        assert "Database integrity error" in err2
        assert "blood_requests.patient_name" in err2
        assert "Failed to allocate unique request ID after" not in err2
        assert elapsed < 0.1, f"Expected immediate abort (<0.1s), but took {elapsed:.4f}s (unwanted retry detected)"

    finally:
        with get_db() as db:
            db.execute("DROP INDEX IF EXISTS idx_test_unique_patient;")
            db.execute("DELETE FROM blood_requests WHERE patient_name = ?;", (test_patient,))


