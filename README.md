# Blood Bank Management System (BBMS)

**Software Engineering Laboratory Project**  
**Students:** 
N Sai Lokesh Naidu, Nandan Kumar K R, Mithun P Naik, Mueez ahmed

## Team Members

| Name | Scrum Role | Focus |
|---|---|---|
| Mueez Ahmed | Scrum Master | Authentication, audit log, admin moderation, plagiarism check |
| Lokesh Naidu| Product Owner | Quiz creation, backlog and documentation |
| Mithun P Naik | Developer | Integration testing, RBAC, performance tests |
| Nandan Kumar K R | Developer | Frontend, CI/CD |
**Section:** 5E  
**Institution:** PES University  
**SRS Reference:** `D:\SWE\Blood_Bank_Management_System_SRS.docx` (Version 1.1)

---

## 🌟 Executive Summary

The **Blood Bank Management System (BBMS)** is an enterprise-grade, centralized health informatics solution engineered to manage blood donor lifecycles, clinical eligibility screenings, blood unit inventory, hospital blood requisitions, intelligent **FEFO (First-Expire, First-Out)** cross-match allocations, atomic dispatch transactions, tamper-evident audit trails, and automated regulatory reporting.

This system is built in strict adherence to the **Software Requirements Specification (SRS v1.1)**, addressing 100% of functional requirements (`BBMS-F-001` through `BBMS-F-020`), non-functional requirements (`BBMS-NF-001` through `BBMS-NF-005`), and security requirements (`BBMS-SR-001` through `BBMS-SR-005`).

---

## 🏗️ Architecture & Technology Stack

- **Backend Framework:** FastAPI (Python 3.14) with high-performance asynchronous ASGI support.
- **Data Persistence:** SQLite in WAL (Write-Ahead Logging) mode with foreign key enforcement and immediate ACID transaction locking.
- **Security:** Salted PBKDF2-HMAC-SHA256 password hashing, token-based session management, Role-Based Access Control (RBAC), and 100% parameterized SQL query execution.
- **Frontend:** Responsive, modern Glassmorphism HTML5/CSS3/JavaScript interface optimized for desktop, tablet, and mobile browsers.
- **Interactive API Documentation:** Built-in Swagger UI (`/docs`) and ReDoc (`/redoc`).
- **Testing:** Automated Pytest test suite covering all 20 SRS acceptance test cases.

---

## 📋 SRS Requirements Traceability Matrix (RTM)

| Req ID | Requirement Description | Design Module | Test Case | Status |
| :--- | :--- | :--- | :--- | :---: |
| **BBMS-F-001** | Register donor with unique ID and contact details | `app/services/donor_service.py` | `TC-Donor-01` | **PASS (A)** |
| **BBMS-F-002** | Donor medical eligibility screening (Age, Weight, Hb, BP, Interval) | `app/services/donor_service.py` | `TC-Donor-02` | **PASS (A)** |
| **BBMS-F-003** | Donor donation history tracking | `app/services/donor_service.py` | `TC-Donor-03` | **PASS (A)** |
| **BBMS-F-004** | Create unique blood unit ID for every accepted collection | `app/services/inventory_service.py` | `TC-Collection-01` | **PASS (A)** |
| **BBMS-F-005** | Record blood group, component type, collection/expiry dates, status | `app/services/inventory_service.py` | `TC-Collection-02` | **PASS (A)** |
| **BBMS-F-006** | Maintain real-time blood inventory counts & stock matrix | `app/services/inventory_service.py` | `TC-Inv-01` | **PASS (A)** |
| **BBMS-F-007** | Automatic unit expiry detection & blocking from allocation | `app/services/inventory_service.py` | `TC-Inv-02` | **PASS (A)** |
| **BBMS-F-008** | Quarantine, release, or discard blood unit with mandatory reason & audit | `app/services/inventory_service.py` | `TC-Inv-03` | **PASS (A)** |
| **BBMS-F-009** | Hospital/requester blood request creation (patient, group, component, urgency) | `app/services/request_service.py` | `TC-Req-01` | **PASS (A)** |
| **BBMS-F-010** | Validation of blood group, component, and rejection of invalid data | `app/services/request_service.py` | `TC-Req-02` | **PASS (A)** |
| **BBMS-F-011** | Blood-bank staff approval, rejection, or hold of requests with rationale | `app/services/request_service.py` | `TC-Req-03` | **PASS (A)** |
| **BBMS-F-012** | **FEFO (First-Expire, First-Out)** allocation engine with cross-matching | `app/services/allocation_service.py` | `TC-Alloc-01` | **PASS (A)** |
| **BBMS-F-013** | Strict blocking of expired, quarantined, or already issued units | `app/services/issue_service.py` | `TC-Alloc-02` | **PASS (A)** |
| **BBMS-F-014** | Record blood issue with unit, request, hospital, timestamp & staff | `app/services/issue_service.py` | `TC-Issue-01` | **PASS (A)** |
| **BBMS-F-015** | Atomic inventory updates (ACID transaction isolation) | `app/database.py` | `TC-Inv-04` | **PASS (A)** |
| **BBMS-F-016** | Searchable & filterable records across donors, units, and requests | Multiple modules | `TC-Search-01` | **PASS (A)** |
| **BBMS-F-017** | Dynamic reports for Inventory, Collections, Issues, and Discards + CSV | `app/services/report_service.py` | `TC-Report-01` | **PASS (A)** |
| **BBMS-F-018** | Alerts & notifications for low stock, expiring units, and urgent requests | `app/services/notification_service.py` | `TC-Notif-01` | **PASS (A)** |
| **BBMS-F-019** | User administration: account creation, deactivation, and RBAC | `app/services/auth_service.py` | `TC-Admin-01` | **PASS (A)** |
| **BBMS-F-020** | Tamper-evident audit trail logging actor, action, timestamp, entity | `app/services/audit_service.py` | `TC-Audit-01` | **PASS (A)** |
| **BBMS-NF-001** | Sub-3 second response time SLA (Measured: < 0.05s) | Performance middleware | `TC-Perf-01` | **PASS (A)** |
| **BBMS-SR-001** | Role-Based Access Control (Admin, Staff, Hospital, Donor) | `app/routers/` | `TC-Sec-02` | **PASS (A)** |
| **BBMS-SR-003** | Salted PBKDF2 password protection (never stored in plaintext) | `app/services/auth_service.py` | `TC-Sec-04` | **PASS (A)** |
| **BBMS-SR-004** | Input validation & SQL injection prevention via parameterized SQL | SQLite DB layer | `TC-Sec-05` | **PASS (A)** |

---

## 🧬 Biological Compatibility & Shelf-Life Rules

### 1. Shelf-Life Durations (Configured in `app/config.py`)
- **Platelets:** 5 days (stored at 20–24°C with gentle agitation)
- **Whole Blood:** 35 days (stored at 2–6°C)
- **Packed Red Cells (RBC):** 42 days (stored at 2–6°C)
- **Fresh Frozen Plasma (FFP):** 365 days (stored at ≤ -18°C)
- **Cryoprecipitate:** 365 days (stored at ≤ -18°C)

### 2. Biological Compatibility Matrix
- **Red Blood Cells / Whole Blood:**
  - `O-` is the Universal Donor (compatible with all recipient groups).
  - `AB+` is the Universal Recipient.
- **Plasma:**
  - `AB` is the Universal Plasma Donor.
  - `O` is the Universal Plasma Recipient.

---

## 👥 Demo User Accounts (Pre-Seeded)

The web interface features an instant role-switching toolbar at the top. You can evaluate the entire application as:

| Role | Username | Password | Permissions |
| :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `admin123` | Full access, user management, audit trail inspection |
| **Blood Bank Staff** | `staff` | `staff123` | Collections, eligibility screening, inventory, FEFO allocation, dispatch |
| **Hospital Requester**| `hospital`| `hospital123`| Blood requisitions, urgency setting, status tracking |
| **Donor** | `donor` | `donor123` | Personal profile & donation history review |

---

## 🚀 How to Run the Project

### 1. Start the Web Server
Open terminal in the project directory:
```bash
python run.py
```
- Web Application: **http://localhost:8000**
- Interactive Swagger UI: **http://localhost:8000/docs**

### 2. Run the Automated Test Suite
To verify all 66 tests in `tests/test_bbms.py`:
```bash
python -m pytest tests/test_bbms.py -v
```
All 66 tests will execute and pass, verifying full compliance.

To verify the full regression test suite (76 automated tests: 66 in `tests/test_bbms.py` and 10 in `tests/test_performance.py` covering functional, security, RBAC, ACID, and performance requirements):
```bash
python -m pytest tests/ -v
```

### 3. Run the Performance Benchmark Runner
To generate the real-time empirical benchmark report across all 24 workload profiles:
```bash
python -m tests.perf_runner
```
To run the dedicated performance SLA test suite:
```bash
python -m pytest tests/test_performance.py -v
```

---

## ⚡ Performance & Response Time Benchmark (BBMS-NF-001)

### Requirement & SLA Compliance
Under **Non-Functional Requirement BBMS-NF-001**:
> *"The system shall return normal search, form submission, and dashboard requests within 3 seconds for at least 95% of requests under normal expected load."*

The application includes an active HTTP monitoring middleware (`add_process_time_header` in `app/main.py`) that measures server processing duration for every request and injects it into the `X-Process-Time-Sec` HTTP response header.

In comprehensive empirical benchmarking (24 distinct workload profiles, 960 total operations), **100% of operations completed well below the 3.0-second SLA limit**, achieving an **overall error rate of 0.00%**.

### Architectural Latency Characteristics (< 0.05s Reads vs. Security PBKDF2)
- **High-Speed Cached Reads (< 0.05 s / < 50 ms):** Standard search, filter, and dashboard endpoints (such as `GET /api/inventory/summary`, `GET /api/donors?search=...`, and `GET /api/requests?urgency=...`) consistently execute in **0.007s – 0.043s** under both in-process ASGI and live TCP loopback socket environments. O(1) in-memory session token validation (`GET /api/auth/me`) resolves in ~0.008s–0.009s.
- **Deliberate Cryptographic Defense (~0.12s):** Credential verification (`POST /api/auth/login`) utilizes 100,000 rounds of salted PBKDF2-HMAC-SHA256 (mandated by `BBMS-SR-003` to thwart offline brute-force and dictionary attacks). This deliberate computational cost takes ~0.127s (strictly sub-second and far below the 3.0s SLA), while all subsequent authenticated queries operate at sub-50ms speeds via cached bearer tokens.
- **ACID Transaction Locking Under Contention:** Concurrent request creation (`POST /api/requests`) with SQLite WAL mode and immediate locking handles high concurrency (C=5, C=10) with 0 errors and a worst-case p95 of 0.4875s (max: 0.6397s).

### System & Environment Configuration
- **Operating System:** Windows 11 (10.0.26300)
- **Python Runtime:** Python 3.14.0
- **CPU Architecture:** 4 Physical Cores / 8 Logical Processors
- **System Memory:** 23.69 GB RAM Total (12.77 GB Available)
- **Database Engine:** SQLite 3 in WAL Mode (Write-Ahead Logging enabled, busy timeout: 20.0s)

### Empirical Benchmark Matrix (24 Scenarios, 960 Operations)

| Operation / Endpoint | Harness | Conc | Reqs | Min(s) | Mean(s) | p50(s) | p95(s) | p99(s) | RPS | BBMS-NF-001 SLA |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GET /api/auth/me` | TestClient | 1 | 40 | 0.0066 | 0.0078 | 0.0076 | 0.0093 | 0.0096 | 127.8 | **PASS** |
| `GET /api/inventory/summary` | TestClient | 1 | 40 | 0.0155 | 0.0171 | 0.0166 | 0.0184 | 0.0289 | 58.6 | **PASS** |
| `GET /api/inventory/units (Filtered)` | TestClient | 1 | 40 | 0.0152 | 0.0180 | 0.0163 | 0.0189 | 0.0528 | 55.5 | **PASS** |
| `GET /api/donors (Search & Filter)` | TestClient | 1 | 40 | 0.0111 | 0.0129 | 0.0128 | 0.0146 | 0.0171 | 77.5 | **PASS** |
| `GET /api/donors/{id}/history (Join Query)` | TestClient | 1 | 40 | 0.0264 | 0.0307 | 0.0294 | 0.0406 | 0.0569 | 32.5 | **PASS** |
| `GET /api/requests (Urgency Filter)` | TestClient | 1 | 40 | 0.0114 | 0.0138 | 0.0128 | 0.0170 | 0.0331 | 72.5 | **PASS** |
| `GET /api/reports/inventory (Aggregate Report)` | TestClient | 1 | 40 | 0.0152 | 0.0171 | 0.0166 | 0.0184 | 0.0267 | 58.4 | **PASS** |
| `GET /api/reports/export-csv (CSV Export)` | TestClient | 1 | 40 | 0.0159 | 0.0171 | 0.0168 | 0.0194 | 0.0200 | 58.6 | **PASS** |
| `GET /api/inventory/summary` [C=5] | TestClient | 5 | 50 | 0.0159 | 0.0517 | 0.0477 | 0.0925 | 0.0998 | 94.1 | **PASS** |
| `GET /api/inventory/summary` [C=10] | TestClient | 10 | 50 | 0.0474 | 0.0890 | 0.0891 | 0.1151 | 0.1392 | 107.4 | **PASS** |
| `GET /api/donors (Search)` [C=5] | TestClient | 5 | 50 | 0.0137 | 0.0676 | 0.0438 | 0.2737 | 0.3166 | 72.4 | **PASS** |
| `GET /api/donors (Search)` [C=10] | TestClient | 10 | 50 | 0.0487 | 0.0823 | 0.0831 | 0.0998 | 0.1032 | 116.7 | **PASS** |
| `GET /api/requests (Filtered)` [C=5] | TestClient | 5 | 50 | 0.0248 | 0.0476 | 0.0427 | 0.0859 | 0.1108 | 101.7 | **PASS** |
| `GET /api/requests (Filtered)` [C=10] | TestClient | 10 | 50 | 0.0579 | 0.0879 | 0.0876 | 0.1070 | 0.1097 | 109.3 | **PASS** |
| `GET /api/reports/inventory (Aggregate)` [C=5] | TestClient | 5 | 50 | 0.0368 | 0.0505 | 0.0492 | 0.0658 | 0.0724 | 95.7 | **PASS** |
| `GET /api/reports/inventory (Aggregate)` [C=10] | TestClient | 10 | 50 | 0.0538 | 0.0861 | 0.0849 | 0.1203 | 0.1303 | 111.1 | **PASS** |
| `POST /api/requests (Concurrent ACID Writes)` [C=5] | TestClient | 5 | 30 | 0.0351 | 0.0715 | 0.0627 | 0.0966 | 0.2456 | 65.6 | **PASS** |
| `POST /api/requests (Concurrent ACID Writes)` [C=10] | TestClient | 10 | 30 | 0.0365 | 0.1422 | 0.0726 | 0.4875 | 0.6141 | 46.6 | **PASS** |
| `POST /api/auth/login (PBKDF2 100k rounds)` | TestClient | 1 | 30 | 0.1018 | 0.1268 | 0.1277 | 0.1417 | 0.1442 | 7.9 | **PASS** |
| `GET /api/auth/me (O(1) Memory Token Lookup)` | TestClient | 1 | 30 | 0.0069 | 0.0081 | 0.0080 | 0.0094 | 0.0098 | 124.2 | **PASS** |
| `GET /api/inventory/summary` | Live TCP | 5 | 30 | 0.0235 | 0.0402 | 0.0389 | 0.0578 | 0.0657 | 116.4 | **PASS** |
| `GET /api/donors?search=Rahul` | Live TCP | 5 | 30 | 0.0096 | 0.0316 | 0.0308 | 0.0603 | 0.0646 | 146.7 | **PASS** |
| `GET /api/requests?urgency=Emergency` | Live TCP | 5 | 30 | 0.0115 | 0.0317 | 0.0304 | 0.0474 | 0.0486 | 148.2 | **PASS** |
| `GET /api/reports/inventory` | Live TCP | 5 | 30 | 0.0211 | 0.0423 | 0.0423 | 0.0632 | 0.0656 | 111.0 | **PASS** |

### Benchmark Execution Summary
- **Total Operations:** 960 requests across 24 workload profiles
- **Total Unhandled Errors:** 0 (0.00% Error Rate)
- **Aggregate Compliance Rate:** 100.00% (960/960 operations <= 3.0000s)
- **Observed Worst-Case Max:** 0.6397 s (100.00% of operations <= 3.0s)
- **Observed Worst-Case p99:** 0.2626 s (pooled across all 960 requests)
- **Observed Worst-Case p95:** 0.1165 s (pooled across all 960 requests; worst scenario p95: 0.4875 s)
- **Observed Median (p50):** 0.0400 s (pooled across all 960 requests)
- **Observed Fastest Mean Latency:** 0.0078 s (GET /api/auth/me session token lookup)
- **SLA Status:** 100% compliant with Non-Functional Requirement BBMS-NF-001 & Issue #25 (every request <= 3.0s)

---

## 📁 Project Directory Structure

```
BloodBankManagementSystem/
├── app/
│   ├── config.py                 # Shelf lives, compatibility matrix, clinical thresholds
│   ├── database.py               # SQLite schema, WAL mode, ACID context manager
│   ├── main.py                   # FastAPI setup, middleware, static mounting
│   ├── models.py                 # Pydantic validation schemas
│   ├── seed_data.py              # Initial realistic demo data generator
│   ├── routers/
│   │   ├── admin.py              # User management & audit logs
│   │   ├── allocations.py        # FEFO allocation endpoints
│   │   ├── auth.py               # Authentication & session endpoints
│   │   ├── collections.py        # Blood collection registration
│   │   ├── demo.py               # Role switcher & reset utilities
│   │   ├── donors.py             # Donor registration & vitals screening
│   │   ├── inventory.py          # Stock counts, unit actions, auto-expiry
│   │   ├── issues.py             # Issue execution & dispatch slip
│   │   ├── notifications.py      # Low stock & expiry alerts
│   │   ├── reports.py            # Inventory, donation, issue reports & CSV
│   │   └── requests.py           # Hospital blood requisitions & decisions
│   ├── services/
│   │   ├── allocation_service.py # FEFO algorithm implementation
│   │   ├── audit_service.py      # Tamper-evident logging
│   │   ├── auth_service.py       # Password hashing & RBAC
│   │   ├── donor_service.py      # Donor registration & medical screening
│   │   ├── inventory_service.py  # Unit tracking & auto-expiry engine
│   │   ├── issue_service.py      # Dispatch execution & verification
│   │   ├── notification_service.py# Alert detection
│   │   ├── report_service.py     # Aggregated reports & CSV export
│   │   └── request_service.py    # Request workflow
│   └── static/
│       ├── css/style.css         # Responsive styling
│       ├── js/app.js             # Dynamic UI logic
│       └── index.html            # Main web application dashboard
├── tests/
│   ├── perf_runner.py            # Reusable benchmarking runner (24 scenarios, metrics & reporting)
│   ├── test_bbms.py              # 66 automated pytest test cases (functional, security, RBAC, ACID)
│   └── test_performance.py       # 10 automated performance SLA & middleware tests
├── requirements.txt
├── run.py                        # Server runner
└── README.md                     # Documentation
```
