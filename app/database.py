import sqlite3
import os
from contextlib import contextmanager
from app.config import DB_PATH

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    cursor = conn.cursor()

    # 1. Users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'staff', 'hospital', 'donor')),
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Donors
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS donors (
        donor_id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        age INTEGER NOT NULL CHECK(age > 0),
        gender TEXT NOT NULL CHECK(gender IN ('Male', 'Female', 'Other')),
        blood_group TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT,
        address TEXT,
        medical_remarks TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Eligibility Records
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS eligibility_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id TEXT NOT NULL,
        weight_kg REAL NOT NULL,
        hemoglobin_g_dl REAL NOT NULL,
        systolic_bp INTEGER NOT NULL,
        diastolic_bp INTEGER NOT NULL,
        pulse INTEGER NOT NULL,
        days_since_last_donation INTEGER,
        is_eligible INTEGER NOT NULL CHECK(is_eligible IN (0, 1)),
        rejection_reason TEXT,
        checked_by TEXT NOT NULL,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (donor_id) REFERENCES donors(donor_id) ON DELETE CASCADE
    );
    """)

    # 4. Blood Collections
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blood_collections (
        collection_id TEXT PRIMARY KEY,
        donor_id TEXT NOT NULL,
        blood_group TEXT NOT NULL,
        volume_ml REAL NOT NULL DEFAULT 450.0,
        collection_date DATE NOT NULL,
        status TEXT NOT NULL DEFAULT 'Completed',
        collected_by TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (donor_id) REFERENCES donors(donor_id) ON DELETE RESTRICT
    );
    """)

    # 5. Blood Units
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blood_units (
        unit_id TEXT PRIMARY KEY,
        collection_id TEXT,
        donor_id TEXT NOT NULL,
        blood_group TEXT NOT NULL,
        component_type TEXT NOT NULL,
        volume_ml REAL NOT NULL,
        collection_date DATE NOT NULL,
        expiry_date DATE NOT NULL,
        status TEXT NOT NULL DEFAULT 'Available' CHECK(status IN ('Available', 'Quarantined', 'Reserved', 'Issued', 'Expired', 'Discarded')),
        storage_location TEXT DEFAULT 'Main Cold Storage Bay-1',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (collection_id) REFERENCES blood_collections(collection_id) ON DELETE SET NULL,
        FOREIGN KEY (donor_id) REFERENCES donors(donor_id) ON DELETE RESTRICT
    );
    """)

    # 6. Unit Status Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS unit_status_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id TEXT NOT NULL,
        previous_status TEXT NOT NULL,
        new_status TEXT NOT NULL,
        reason TEXT NOT NULL,
        changed_by TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (unit_id) REFERENCES blood_units(unit_id) ON DELETE CASCADE
    );
    """)

    # 7. Blood Requests
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blood_requests (
        request_id TEXT PRIMARY KEY,
        hospital_name TEXT NOT NULL,
        requester_name TEXT NOT NULL,
        patient_name TEXT NOT NULL,
        patient_blood_group TEXT NOT NULL,
        component_type TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        urgency TEXT NOT NULL DEFAULT 'Normal' CHECK(urgency IN ('Normal', 'Urgent', 'Emergency')),
        required_date DATE NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending', 'Approved', 'Rejected', 'On_Hold', 'Fulfilled', 'Cancelled')),
        decision_reason TEXT,
        decision_by TEXT,
        decision_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 8. Allocations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS allocations (
        allocation_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        unit_id TEXT NOT NULL,
        allocated_by TEXT NOT NULL,
        allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL DEFAULT 'Allocated' CHECK(status IN ('Allocated', 'Issued', 'Released')),
        FOREIGN KEY (request_id) REFERENCES blood_requests(request_id) ON DELETE CASCADE,
        FOREIGN KEY (unit_id) REFERENCES blood_units(unit_id) ON DELETE CASCADE
    );
    """)

    # 9. Issue Transactions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS issue_transactions (
        issue_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        unit_id TEXT NOT NULL,
        hospital_name TEXT NOT NULL,
        patient_name TEXT NOT NULL,
        issuing_staff TEXT NOT NULL,
        issue_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verification_notes TEXT,
        FOREIGN KEY (request_id) REFERENCES blood_requests(request_id) ON DELETE RESTRICT,
        FOREIGN KEY (unit_id) REFERENCES blood_units(unit_id) ON DELETE RESTRICT
    );
    """)

    # 10. Inventory Alerts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('Info', 'Warning', 'Critical')),
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 11. Audit Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_username TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        details TEXT,
        ip_address TEXT DEFAULT '127.0.0.1',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Create Indexes for fast searches and response time (<3s NF-001)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_units_status_group ON blood_units(status, blood_group, component_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_units_expiry ON blood_units(expiry_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON blood_requests(status, urgency);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_donors_group ON donors(blood_group);")

    conn.commit()
    conn.close()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
