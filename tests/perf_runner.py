"""
BBMS Stage 3: Reusable Performance Testing and Benchmarking Suite.
Measures latency percentiles (min, mean, p50, p95, p99, max), throughput (RPS),
and error rates across sequential, concurrent read, concurrent write, and live HTTP workloads.
Validates BBMS-NF-001 (response time SLA <= 3.0s for >= 95% of requests).
"""

import os
import sys
import time
import socket
import threading
import platform
import uuid
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import psutil

# Ensure app is discoverable
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from app.main import app
from app.database import get_db, init_db
from app.seed_data import seed_database
from app.config import DB_PATH
from fastapi.testclient import TestClient

try:
    import uvicorn
    import httpx
    HAS_LIVE_SERVER = True
except ImportError:
    HAS_LIVE_SERVER = False


def get_system_environment_info() -> Dict[str, Any]:
    """Capture runtime system and environment metadata for performance reporting."""
    wal_enabled = False
    db_size_bytes = 0
    try:
        if os.path.exists(DB_PATH):
            db_size_bytes = os.path.getsize(DB_PATH)
        with get_db() as db:
            row = db.execute("PRAGMA journal_mode;").fetchone()
            if row:
                wal_enabled = (row[0].upper() == "WAL")
    except Exception:
        pass

    mem = psutil.virtual_memory()
    return {
        "os_platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True),
        "ram_total_gb": round(mem.total / (1024 ** 3), 2),
        "ram_available_gb": round(mem.available / (1024 ** 3), 2),
        "database_engine": "SQLite 3",
        "database_path": DB_PATH,
        "database_size_kb": round(db_size_bytes / 1024, 2),
        "sqlite_wal_mode": wal_enabled,
    }


def compute_metrics(
    name: str,
    harness: str,
    category: str,
    concurrency: int,
    latencies: List[float],
    total_time_sec: float,
    errors: int = 0,
    error_details: Optional[List[str]] = None,
    sla_target_sec: float = 3.0
) -> Dict[str, Any]:
    """Calculate comprehensive statistical metrics from a latency sample."""
    n = len(latencies)
    total_attempts = n + errors
    if total_attempts == 0:
        return {
            "name": name,
            "harness": harness,
            "category": category,
            "concurrency": concurrency,
            "completed": 0,
            "errors": errors,
            "error_rate_pct": 0.0,
            "min_sec": 0.0,
            "mean_sec": 0.0,
            "p50_sec": 0.0,
            "p90_sec": 0.0,
            "p95_sec": 0.0,
            "p99_sec": 0.0,
            "max_sec": 0.0,
            "total_time_sec": total_time_sec,
            "rps": 0.0,
            "sla_target_sec": sla_target_sec,
            "sla_passed": False,
            "error_details": error_details or [],
        }

    arr = np.array(latencies) if n > 0 else np.array([0.0])
    p95 = float(np.percentile(arr, 95)) if n > 0 else 0.0
    p99 = float(np.percentile(arr, 99)) if n > 0 else 0.0
    max_val = float(np.max(arr)) if n > 0 else 0.0
    error_rate = (errors / total_attempts) * 100.0 if total_attempts > 0 else 0.0
    within_target = sum(1 for dt in latencies if dt <= sla_target_sec)
    compliance_pct = (within_target / n * 100.0) if n > 0 else 0.0
    sla_passed = (
        (p95 <= sla_target_sec)
        and (max_val <= sla_target_sec)
        and (error_rate == 0.0)
        and (compliance_pct == 100.0)
        and (max_val >= p99 >= p95)
    )

    return {
        "name": name,
        "harness": harness,
        "category": category,
        "concurrency": concurrency,
        "completed": n,
        "errors": errors,
        "error_rate_pct": error_rate,
        "compliance_pct": compliance_pct,
        "min_sec": float(np.min(arr)) if n > 0 else 0.0,
        "mean_sec": float(np.mean(arr)) if n > 0 else 0.0,
        "p50_sec": float(np.percentile(arr, 50)) if n > 0 else 0.0,
        "p90_sec": float(np.percentile(arr, 90)) if n > 0 else 0.0,
        "p95_sec": p95,
        "p99_sec": p99,
        "max_sec": max_val,
        "total_time_sec": total_time_sec,
        "rps": (n / total_time_sec) if total_time_sec > 0 else 0.0,
        "sla_target_sec": sla_target_sec,
        "sla_passed": sla_passed,
        "error_details": error_details or [],
        "latencies": list(latencies),
    }


def obtain_auth_tokens(client: TestClient) -> Dict[str, str]:
    """Generate session tokens for each role for benchmarking."""
    tokens = {}
    for role, user, pwd in [
        ("staff", "staff", "staff123"),
        ("admin", "admin", "admin123"),
        ("hospital", "hospital", "hospital123"),
        ("donor", "donor", "donor123"),
    ]:
        res = client.post("/api/auth/login", json={"username": user, "password": pwd})
        if res.status_code == 200:
            tokens[role] = res.json()["token"]
    return tokens


def run_sequential_benchmark(
    client: TestClient,
    method: str,
    path: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    iterations: int = 50,
    expected_status: int = 200,
    name: Optional[str] = None
) -> Dict[str, Any]:
    """Execute repeated sequential requests to measure baseline latency distribution."""
    display_name = name or f"{method.upper()} {path}"
    latencies = []
    errors = 0
    err_details = []

    t_batch_start = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            if method.upper() == "GET":
                res = client.get(path, headers=headers)
            elif method.upper() == "POST":
                res = client.post(path, headers=headers, json=json_data)
            elif method.upper() == "PATCH":
                res = client.patch(path, headers=headers, json=json_data)
            else:
                raise ValueError(f"Unsupported method: {method}")

            dt = time.perf_counter() - t0
            if res.status_code == expected_status:
                latencies.append(dt)
            else:
                errors += 1
                if len(err_details) < 5:
                    err_details.append(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            errors += 1
            if len(err_details) < 5:
                err_details.append(str(e))

    total_time = time.perf_counter() - t_batch_start
    return compute_metrics(
        name=display_name,
        harness="In-Process TestClient (ASGI)",
        category="Sequential Baseline",
        concurrency=1,
        latencies=latencies,
        total_time_sec=total_time,
        errors=errors,
        error_details=err_details
    )


def run_concurrent_read_benchmark(
    client: TestClient,
    method: str,
    path: str,
    headers: Optional[Dict[str, str]] = None,
    total_requests: int = 50,
    concurrency: int = 10,
    expected_status: int = 200,
    name: Optional[str] = None
) -> Dict[str, Any]:
    """Execute concurrent read requests across a thread pool."""
    display_name = name or f"{method.upper()} {path}"
    latencies = []
    errors = 0
    err_details = []
    lock = threading.Lock()

    def worker_task(_):
        nonlocal errors
        t0 = time.perf_counter()
        try:
            res = client.get(path, headers=headers)
            dt = time.perf_counter() - t0
            with lock:
                if res.status_code == expected_status:
                    latencies.append(dt)
                else:
                    errors += 1
                    if len(err_details) < 5:
                        err_details.append(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            with lock:
                errors += 1
                if len(err_details) < 5:
                    err_details.append(str(e))

    t_batch_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(worker_task, range(total_requests)))
    total_time = time.perf_counter() - t_batch_start

    return compute_metrics(
        name=display_name,
        harness="In-Process TestClient (ASGI)",
        category="Concurrent Read",
        concurrency=concurrency,
        latencies=latencies,
        total_time_sec=total_time,
        errors=errors,
        error_details=err_details
    )


def escape_sql_like(value: str, escape_char: str = "\\") -> str:
    """
    Escape SQL LIKE wildcards (%, _, and the escape character itself)
    for exact literal prefix or substring matching in SQLite.
    Prevents single-character wildcard (_) misclassifications on patient names.
    """
    return value.replace(escape_char, escape_char * 2).replace("%", f"{escape_char}%").replace("_", f"{escape_char}_")


def run_concurrent_write_benchmark(
    client: TestClient,
    headers: Optional[Dict[str, str]] = None,
    total_requests: int = 30,
    concurrency: int = 5,
    name: str = "POST /api/requests (Concurrent ACID Writes)",
    run_tag: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute concurrent write operations under SQLite WAL mode.
    Tests ACID transaction serialization and lock handling under contention.
    Cleans up created test records immediately after benchmark.
    """
    latencies = []
    errors = 0
    err_details = []
    created_request_ids = []
    lock = threading.Lock()
    active_run_tag = run_tag or f"PERF_WRITE_{uuid.uuid4().hex[:6]}"
    escaped_run_tag = escape_sql_like(active_run_tag)

    def write_worker(idx: int):
        nonlocal errors
        payload = {
            "hospital_name": "City Care Hospital",
            "requester_name": "Dr. Benchmark",
            "patient_name": f"{active_run_tag}_{idx}",
            "patient_blood_group": "A+",
            "component_type": "Whole Blood",
            "quantity": 1,
            "urgency": "Normal",
            "required_date": "2026-11-20"
        }
        t0 = time.perf_counter()
        try:
            res = client.post("/api/requests", json=payload, headers=headers)
            dt = time.perf_counter() - t0
            with lock:
                if res.status_code == 201:
                    latencies.append(dt)
                    req_id = res.json().get("request_id")
                    if req_id:
                        created_request_ids.append(req_id)
                else:
                    errors += 1
                    if len(err_details) < 5:
                        err_details.append(f"HTTP {res.status_code}: {res.text[:100]}")
        except Exception as e:
            with lock:
                errors += 1
                if len(err_details) < 5:
                    err_details.append(str(e))

    t_batch_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(write_worker, range(total_requests)))
    total_time = time.perf_counter() - t_batch_start

    # Clean up created benchmark records safely without touching unrelated records
    try:
        with get_db() as db:
            # Query all request_ids for this run_tag to ensure complete cleanup even if response collection failed
            rows = db.execute(
                "SELECT request_id FROM blood_requests WHERE patient_name LIKE ? ESCAPE '\\'",
                (f"{escaped_run_tag}%",)
            ).fetchall()
            all_run_request_ids = list(set(created_request_ids + [r["request_id"] for r in rows]))

            if all_run_request_ids:
                placeholders = ",".join("?" for _ in all_run_request_ids)
                db.execute(f"DELETE FROM blood_requests WHERE request_id IN ({placeholders})", all_run_request_ids)
                db.execute(f"DELETE FROM audit_logs WHERE entity_id IN ({placeholders})", all_run_request_ids)

            # Delete only audit logs specifically referencing this run_tag
            db.execute(
                "DELETE FROM audit_logs WHERE details LIKE ? ESCAPE '\\'",
                (f"%{escaped_run_tag}%",)
            )

            # 1. Verify remaining benchmark blood requests
            remaining_requests = db.execute(
                "SELECT COUNT(*) as c FROM blood_requests WHERE patient_name LIKE ? ESCAPE '\\'",
                (f"{escaped_run_tag}%",)
            ).fetchone()["c"]

            # 2. Verify remaining audit logs by request entity_id
            remaining_audit_by_id = 0
            if all_run_request_ids:
                placeholders = ",".join("?" for _ in all_run_request_ids)
                remaining_audit_by_id = db.execute(
                    f"SELECT COUNT(*) as c FROM audit_logs WHERE entity_id IN ({placeholders})",
                    all_run_request_ids
                ).fetchone()["c"]

            # 3. Verify remaining audit logs by run_tag
            remaining_audit_by_tag = db.execute(
                "SELECT COUNT(*) as c FROM audit_logs WHERE details LIKE ? ESCAPE '\\'",
                (f"%{escaped_run_tag}%",)
            ).fetchone()["c"]

            if remaining_requests > 0 or remaining_audit_by_id > 0 or remaining_audit_by_tag > 0:
                raise RuntimeError(
                    f"Cleanup verification failed: {remaining_requests} request(s), "
                    f"{remaining_audit_by_id} audit record(s) by entity_id, and "
                    f"{remaining_audit_by_tag} audit record(s) by run_tag remained"
                )
    except Exception as cleanup_err:
        errors += 1
        err_details.append(f"Cleanup failure: {cleanup_err}")

    return compute_metrics(
        name=name,
        harness="In-Process TestClient (ASGI)",
        category="Concurrent Write",
        concurrency=concurrency,
        latencies=latencies,
        total_time_sec=total_time,
        errors=errors,
        error_details=err_details
    )


def run_auth_performance_benchmark(
    client: TestClient,
    iterations: int = 30
) -> List[Dict[str, Any]]:
    """
    Benchmark CPU-bound PBKDF2 authentication vs. in-memory token lookup.
    Quantifies the architectural difference between credential hashing and token cache.
    """
    # 1. PBKDF2 Login benchmark
    login_latencies = []
    login_errors = 0
    t_login_start = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
        dt = time.perf_counter() - t0
        if res.status_code == 200:
            login_latencies.append(dt)
        else:
            login_errors += 1
    total_login_time = time.perf_counter() - t_login_start

    m_login = compute_metrics(
        name="POST /api/auth/login (PBKDF2 100k rounds)",
        harness="In-Process TestClient (ASGI)",
        category="Authentication",
        concurrency=1,
        latencies=login_latencies,
        total_time_sec=total_login_time,
        errors=login_errors
    )

    # 2. In-memory session lookup benchmark
    token_res = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    token = token_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_latencies = []
    me_errors = 0
    t_me_start = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = client.get("/api/auth/me", headers=headers)
        dt = time.perf_counter() - t0
        if res.status_code == 200:
            me_latencies.append(dt)
        else:
            me_errors += 1
    total_me_time = time.perf_counter() - t_me_start

    m_me = compute_metrics(
        name="GET /api/auth/me (O(1) Memory Token Lookup)",
        harness="In-Process TestClient (ASGI)",
        category="Authentication",
        concurrency=1,
        latencies=me_latencies,
        total_time_sec=total_me_time,
        errors=me_errors
    )

    return [m_login, m_me]


def find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_live_http_benchmarks(
    requests_per_endpoint: int = 30,
    concurrency: int = 5
) -> List[Dict[str, Any]]:
    """
    Run benchmarks against a live Uvicorn HTTP server over real TCP loopback.
    Clearly distinguishes network/socket performance from in-process TestClient.
    """
    if not HAS_LIVE_SERVER:
        return []

    port = find_free_port()
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config=config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(40):
        try:
            r = httpx.get(f"{base_url}/docs", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.1)

    if not ready:
        server.should_exit = True
        return []

    results = []
    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as http_client:
            # Login
            login_res = http_client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
            token = login_res.json()["token"]
            headers = {"Authorization": f"Bearer {token}"}

            endpoints_to_test = [
                ("GET /api/inventory/summary", "/api/inventory/summary"),
                ("GET /api/donors?search=Rahul", "/api/donors?search=Rahul"),
                ("GET /api/requests?urgency=Emergency", "/api/requests?urgency=Emergency"),
                ("GET /api/reports/inventory", "/api/reports/inventory"),
            ]

            for ep_name, ep_path in endpoints_to_test:
                latencies = []
                errors = 0
                err_details = []
                lock = threading.Lock()

                def http_worker(_):
                    nonlocal errors
                    t0 = time.perf_counter()
                    try:
                        res = http_client.get(ep_path, headers=headers)
                        dt = time.perf_counter() - t0
                        with lock:
                            if res.status_code == 200:
                                latencies.append(dt)
                            else:
                                errors += 1
                                if len(err_details) < 3:
                                    err_details.append(f"HTTP {res.status_code}")
                    except Exception as e:
                        with lock:
                            errors += 1
                            if len(err_details) < 3:
                                err_details.append(str(e))

                t_batch_start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    list(pool.map(http_worker, range(requests_per_endpoint)))
                total_time = time.perf_counter() - t_batch_start

                m = compute_metrics(
                    name=ep_name,
                    harness="Live HTTP Server (Uvicorn / TCP)",
                    category="Live HTTP Concurrent",
                    concurrency=concurrency,
                    latencies=latencies,
                    total_time_sec=total_time,
                    errors=errors,
                    error_details=err_details
                )
                results.append(m)
    finally:
        server.should_exit = True
        server_thread.join(timeout=3.0)

    return results


def run_full_benchmark_suite() -> Dict[str, Any]:
    """
    Execute the complete Stage 3 Performance Testing Suite across all workload profiles.
    Returns structured results and environment details.
    """
    env_info = get_system_environment_info()
    client = TestClient(app)
    tokens = obtain_auth_tokens(client)

    staff_headers = {"Authorization": f"Bearer {tokens['staff']}"}
    hospital_headers = {"Authorization": f"Bearer {tokens['hospital']}"}

    all_metrics: List[Dict[str, Any]] = []

    # 1. Profile 1: Sequential Baseline (11 endpoints identified in inspection)
    sequential_targets = [
        ("GET", "/api/auth/me", staff_headers, None, 200, "GET /api/auth/me"),
        ("GET", "/api/inventory/summary", staff_headers, None, 200, "GET /api/inventory/summary"),
        ("GET", "/api/inventory/units?status=Available&blood_group=O+", staff_headers, None, 200, "GET /api/inventory/units (Filtered)"),
        ("GET", "/api/donors?search=Rahul&blood_group=O+", staff_headers, None, 200, "GET /api/donors (Search & Filter)"),
        ("GET", "/api/donors/DON-2026-0001/history", staff_headers, None, 200, "GET /api/donors/{id}/history (Join Query)"),
        ("GET", "/api/requests?urgency=Emergency&status=Pending", staff_headers, None, 200, "GET /api/requests (Urgency Filter)"),
        ("GET", "/api/reports/inventory", staff_headers, None, 200, "GET /api/reports/inventory (Aggregate Report)"),
        ("GET", "/api/reports/export-csv?report_type=inventory", staff_headers, None, 200, "GET /api/reports/export-csv (CSV Export)"),
    ]

    for method, path, hdrs, jdata, exp_st, name in sequential_targets:
        m = run_sequential_benchmark(client, method, path, headers=hdrs, json_data=jdata, iterations=40, expected_status=exp_st, name=name)
        all_metrics.append(m)

    # 2. Profile 2: Concurrent Read Workloads
    concurrent_targets = [
        ("/api/inventory/summary", "GET /api/inventory/summary"),
        ("/api/donors?search=Rahul", "GET /api/donors (Search)"),
        ("/api/requests?urgency=Emergency", "GET /api/requests (Filtered)"),
        ("/api/reports/inventory", "GET /api/reports/inventory (Aggregate)"),
    ]

    for path, name in concurrent_targets:
        for c_level in [5, 10]:
            m = run_concurrent_read_benchmark(
                client=client,
                method="GET",
                path=path,
                headers=staff_headers,
                total_requests=50,
                concurrency=c_level,
                name=f"{name} [C={c_level}]"
            )
            all_metrics.append(m)

    # 3. Profile 3: Concurrent Write Workloads
    for c_level in [5, 10]:
        m_write = run_concurrent_write_benchmark(
            client=client,
            headers=hospital_headers,
            total_requests=30,
            concurrency=c_level,
            name=f"POST /api/requests (Concurrent ACID Writes) [C={c_level}]"
        )
        all_metrics.append(m_write)

    # 4. Profile 4: Authentication Benchmarks
    auth_metrics = run_auth_performance_benchmark(client, iterations=30)
    all_metrics.extend(auth_metrics)

    # 5. Profile 5: Live HTTP Server Comparison
    live_metrics = run_live_http_benchmarks(requests_per_endpoint=30, concurrency=5)
    all_metrics.extend(live_metrics)

    return {
        "env_info": env_info,
        "metrics": all_metrics,
    }


def format_performance_report(results: Dict[str, Any]) -> str:
    """Format structured benchmark results into a clean, human-readable ASCII report."""
    env = results["env_info"]
    metrics = results["metrics"]

    total_ops = sum(m["completed"] for m in metrics)
    total_errors = sum(m["errors"] for m in metrics)
    overall_error_rate = (total_errors / (total_ops + total_errors) * 100.0) if (total_ops + total_errors) > 0 else 0.0

    all_sla_passed = all(m["sla_passed"] for m in metrics)

    all_latencies = [lat for m in metrics for lat in m.get("latencies", [])]
    if all_latencies:
        arr_all = np.array(all_latencies)
        pooled_max = float(np.max(arr_all))
        pooled_p99 = float(np.percentile(arr_all, 99))
        pooled_p95 = float(np.percentile(arr_all, 95))
        pooled_p50 = float(np.percentile(arr_all, 50))
        pooled_mean = float(np.mean(arr_all))
        within_3s_count = sum(1 for dt in all_latencies if dt <= 3.0)
        overall_compliance_pct = (within_3s_count / len(all_latencies)) * 100.0
        assert pooled_max >= pooled_p99 >= pooled_p95 >= pooled_p50, (
            f"Latency percentile ordering violated: max={pooled_max}, p99={pooled_p99}, p95={pooled_p95}, p50={pooled_p50}"
        )
    else:
        pooled_max = max((m['max_sec'] for m in metrics), default=0.0)
        pooled_p99 = 0.0
        pooled_p95 = max((m['p95_sec'] for m in metrics), default=0.0)
        pooled_p50 = 0.0
        pooled_mean = 0.0
        within_3s_count = total_ops
        overall_compliance_pct = 100.0 if all_sla_passed else 0.0

    report_lines = [
        "=" * 115,
        "                         BBMS STAGE 3: BACKEND PERFORMANCE TESTING REPORT",
        "                Compliance Verification for Non-Functional Requirement: BBMS-NF-001",
        "=" * 115,
        "",
        "1. ENVIRONMENT & RUNTIME CONFIGURATION:",
        f"   - Operating System       : {env['os_platform']}",
        f"   - Python Runtime         : {env['python_version']}",
        f"   - CPU Architecture       : {env['cpu_count_physical']} Physical Cores / {env['cpu_count_logical']} Logical Processors",
        f"   - System RAM             : {env['ram_total_gb']} GB Total ({env['ram_available_gb']} GB Available)",
        f"   - Database Engine        : {env['database_engine']} (WAL Mode: {env['sqlite_wal_mode']}, Timeout: 20.0s)",
        f"   - Database File Size     : {env['database_size_kb']} KB",
        "",
        "2. WORKLOAD PROFILES & HARNESS DESCRIPTION:",
        "   - In-Process TestClient  : FastAPI/Starlette ASGI in-memory transport. Direct internal dispatch without socket I/O.",
        "   - Live HTTP Server (TCP) : High-performance Uvicorn ASGI server bound to 127.0.0.1. Real TCP socket networking.",
        "   - Concurrency Mechanism  : Python ThreadPoolExecutor with concurrent worker threads.",
        "   - SLA Target             : Response time <= 3.0000s for >= 95% of operations (BBMS-NF-001). Error Rate = 0.00%.",
        "",
        "3. BENCHMARK RESULTS MATRIX:",
        "-" * 115,
        f"{'Operation / Endpoint':<42} {'Harness':<16} {'Conc':<5} {'Reqs':<5} {'Min(s)':<8} {'Mean(s)':<8} {'p50(s)':<8} {'p95(s)':<8} {'p99(s)':<8} {'RPS':<7} {'SLA':<6}",
        "-" * 115,
    ]

    for m in metrics:
        harness_short = "TestClient" if "TestClient" in m["harness"] else "Live TCP"
        sla_str = "PASS" if m["sla_passed"] else "FAIL"
        report_lines.append(
            f"{m['name'][:41]:<42} "
            f"{harness_short:<16} "
            f"{m['concurrency']:<5} "
            f"{m['completed']:<5} "
            f"{m['min_sec']:<8.4f} "
            f"{m['mean_sec']:<8.4f} "
            f"{m['p50_sec']:<8.4f} "
            f"{m['p95_sec']:<8.4f} "
            f"{m['p99_sec']:<8.4f} "
            f"{m['rps']:<7.1f} "
            f"{sla_str:<6}"
        )

    report_lines.extend([
        "-" * 115,
        "",
        "4. BBMS-NF-001 COMPLIANCE VERIFICATION SUMMARY:",
        f"   - Total Benchmarked Operations : {total_ops:,} requests across {len(metrics)} workload scenarios",
        f"   - Total Unhandled Errors       : {total_errors} (Error Rate: {overall_error_rate:.2f}%)",
        f"   - Aggregate Compliance Rate    : {overall_compliance_pct:.2f}% ({within_3s_count}/{total_ops} operations <= 3.0000s)",
        f"   - Documented Requirement       : BBMS-NF-001: 95% of applicable operations <= 3.0000s (Issue #25: 100% <= 3.0000s)",
        f"   - Observed Worst-Case Max      : {pooled_max:.4f} seconds",
        f"   - Observed Worst-Case p99      : {pooled_p99:.4f} seconds",
        f"   - Observed Worst-Case p95      : {pooled_p95:.4f} seconds",
        f"   - Observed Median (p50)        : {pooled_p50:.4f} seconds",
        f"   - Observed Fastest Mean Latency: {min((m['mean_sec'] for m in metrics), default=0.0):.4f} seconds",
        f"   - Overall SLA Pass Status      : {'100% COMPLIANT (ALL SCENARIOS PASSED)' if all_sla_passed else 'NON-COMPLIANT'}",
        "=" * 115,
    ])

    return "\n".join(report_lines)


if __name__ == "__main__":
    print("Executing BBMS Stage 3 Performance Testing Suite...")
    benchmark_results = run_full_benchmark_suite()
    report = format_performance_report(benchmark_results)
    print(report)
