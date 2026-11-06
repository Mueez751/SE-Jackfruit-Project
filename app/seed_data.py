from datetime import date, timedelta, datetime
from app.database import get_db, init_db
from app.services.auth_service import hash_password

def seed_database(force: bool = False):
    init_db()

    with get_db() as db:
        user_count = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        if user_count > 0 and not force:
            return  # Already seeded

        # Clear existing tables if force
        if force:
            for tbl in ["audit_logs", "inventory_alerts", "issue_transactions", "allocations",
                        "blood_requests", "unit_status_logs", "blood_units", "blood_collections",
                        "eligibility_records", "donors", "users"]:
                db.execute(f"DELETE FROM {tbl};")

        # 1. Seed Users (Admin, Staff, Hospital, Donor)
        users = [
            ("admin", "admin123", "System Administrator", "admin@pesbloodbank.org", "admin"),
            ("staff", "staff123", "Senior Staff Nurse Priya", "staff@pesbloodbank.org", "staff"),
            ("hospital", "hospital123", "City Care Hospital Requester", "blooddesk@citycarehospital.org", "hospital"),
            ("donor", "donor123", "Rahul Kumar", "rahul.donor@gmail.com", "donor"),
        ]

        for u, pw, name, em, role in users:
            pw_h = hash_password(pw)
            db.execute(
                "INSERT INTO users (username, password_hash, full_name, email, role, status) VALUES (?, ?, ?, ?, ?, 'active')",
                (u, pw_h, name, em, role)
            )

        # 2. Seed Donors
        donors = [
            ("DON-2026-0001", "Rahul Kumar", 28, "Male", "O+", "+91-9876543210", "rahul.donor@gmail.com", "Indiranagar, Bengaluru", "Fit and active"),
            ("DON-2026-0002", "Ananya Sharma", 24, "Female", "A+", "+91-9876543211", "ananya.s@outlook.com", "Koramangala, Bengaluru", "No prior medical conditions"),
            ("DON-2026-0003", "Vikramaditya Roy", 35, "Male", "B+", "+91-9876543212", "v.roy@gmail.com", "Whitefield, Bengaluru", "Universal platelet donor candidate"),
            ("DON-2026-0004", "Fatima Zehra", 30, "Female", "O-", "+91-9876543213", "fatima.z@gmail.com", "Jayanagar, Bengaluru", "Universal RBC donor"),
            ("DON-2026-0005", "Karthik Iyer", 42, "Male", "AB+", "+91-9876543214", "karthik.iyer@gmail.com", "Malleshwaram, Bengaluru", "Regular donor"),
            ("DON-2026-0006", "Sneha Patil", 22, "Female", "A-", "+91-9876543215", "sneha.p@gmail.com", "Electronic City, Bengaluru", "Student donor"),
            ("DON-2026-0007", "Rohan Mehta", 19, "Male", "B-", "+91-9876543216", "rohan.m@gmail.com", "RR Nagar, Bengaluru", "First-time prospective donor"),
        ]

        for did, name, age, gen, bg, ph, em, addr, rem in donors:
            db.execute(
                """
                INSERT INTO donors (donor_id, full_name, age, gender, blood_group, phone, email, address, medical_remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (did, name, age, gen, bg, ph, em, addr, rem)
            )

        # 3. Seed Eligibility Records
        # Rahul: Passed
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, checked_by)
            VALUES ('DON-2026-0001', 68.5, 14.2, 120, 80, 72, 120, 1, 'staff')
            """
        )
        # Ananya: Passed
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, checked_by)
            VALUES ('DON-2026-0002', 54.0, 13.0, 115, 75, 76, 95, 1, 'staff')
            """
        )
        # Vikram: Passed
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, checked_by)
            VALUES ('DON-2026-0003', 75.0, 15.1, 125, 82, 70, 150, 1, 'staff')
            """
        )
        # Fatima: Passed
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, checked_by)
            VALUES ('DON-2026-0004', 59.0, 13.5, 118, 78, 74, 110, 1, 'staff')
            """
        )
        # Karthik: Passed
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, checked_by)
            VALUES ('DON-2026-0005', 80.0, 14.8, 128, 84, 78, 100, 1, 'staff')
            """
        )
        # Sneha: Passed
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, checked_by)
            VALUES ('DON-2026-0006', 52.0, 12.8, 112, 72, 80, 999, 1, 'staff')
            """
        )
        # Rohan Mehta: Failed (Low Hemoglobin 11.2 g/dL & underweight 47kg) - Demonstrating rejection
        db.execute(
            """
            INSERT INTO eligibility_records (donor_id, weight_kg, hemoglobin_g_dl, systolic_bp, diastolic_bp, pulse, days_since_last_donation, is_eligible, rejection_reason, checked_by)
            VALUES ('DON-2026-0007', 47.0, 11.2, 110, 70, 82, 999, 0, 'Weight 47.0 kg is below minimum requirement (50.0 kg); Hemoglobin 11.2 g/dL is below minimum requirement (12.5 g/dL)', 'staff')
            """
        )

        # 4. Seed Collections & Blood Units
        today = date.today()

        unit_specs = [
            # Expiring soon (in 2 days) to test FEFO and Upcoming Expiry alerts!
            ("UNIT-2026-00001", "DON-2026-0001", "O+", "Packed Red Cells", 350.0, today - timedelta(days=40), today + timedelta(days=2), "Available", "Storage Refrig-A1"),
            ("UNIT-2026-00002", "DON-2026-0001", "O+", "Whole Blood", 450.0, today - timedelta(days=10), today + timedelta(days=25), "Available", "Storage Refrig-A1"),
            ("UNIT-2026-00003", "DON-2026-0002", "A+", "Packed Red Cells", 350.0, today - timedelta(days=15), today + timedelta(days=27), "Available", "Storage Refrig-A2"),
            ("UNIT-2026-00004", "DON-2026-0002", "A+", "Fresh Frozen Plasma", 200.0, today - timedelta(days=15), today + timedelta(days=350), "Available", "Deep Freezer DF-1"),
            ("UNIT-2026-00005", "DON-2026-0003", "B+", "Whole Blood", 450.0, today - timedelta(days=5), today + timedelta(days=30), "Available", "Storage Refrig-B1"),
            ("UNIT-2026-00006", "DON-2026-0003", "B+", "Platelets", 250.0, today - timedelta(days=3), today + timedelta(days=2), "Available", "Agitator Tray-1"),
            ("UNIT-2026-00007", "DON-2026-0004", "O-", "Packed Red Cells", 350.0, today - timedelta(days=8), today + timedelta(days=34), "Available", "Storage Refrig-A3 (Universal)"),
            ("UNIT-2026-00008", "DON-2026-0004", "O-", "Whole Blood", 450.0, today - timedelta(days=8), today + timedelta(days=27), "Available", "Storage Refrig-A3 (Universal)"),
            ("UNIT-2026-00009", "DON-2026-0005", "AB+", "Whole Blood", 450.0, today - timedelta(days=12), today + timedelta(days=23), "Available", "Storage Refrig-AB"),
            ("UNIT-2026-00010", "DON-2026-0005", "AB+", "Fresh Frozen Plasma", 220.0, today - timedelta(days=12), today + timedelta(days=353), "Available", "Deep Freezer DF-1"),
            ("UNIT-2026-00011", "DON-2026-0006", "A-", "Packed Red Cells", 350.0, today - timedelta(days=4), today + timedelta(days=38), "Available", "Storage Refrig-A4"),
            # Expired unit (to test auto-expiry engine BBMS-F-007)
            ("UNIT-2026-00012", "DON-2026-0001", "O+", "Platelets", 250.0, today - timedelta(days=8), today - timedelta(days=3), "Expired", "Decommission Bay"),
            # Quarantined unit (to test quarantine workflow BBMS-F-008)
            ("UNIT-2026-00013", "DON-2026-0002", "A+", "Whole Blood", 450.0, today - timedelta(days=2), today + timedelta(days=33), "Quarantined", "Quarantine Cabinet Q-1"),
        ]

        for i, (uid, did, bg, comp, vol, coll_d, exp_d, st, loc) in enumerate(unit_specs):
            cid = f"COL-2026-{i+1:04d}"
            db.execute(
                """
                INSERT INTO blood_collections (collection_id, donor_id, blood_group, volume_ml, collection_date, status, collected_by)
                VALUES (?, ?, ?, ?, ?, 'Completed', 'staff')
                """,
                (cid, did, bg, vol, coll_d.isoformat())
            )
            db.execute(
                """
                INSERT INTO blood_units (unit_id, collection_id, donor_id, blood_group, component_type, volume_ml, collection_date, expiry_date, status, storage_location)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, cid, did, bg, comp, vol, coll_d.isoformat(), exp_d.isoformat(), st, loc)
            )
            db.execute(
                """
                INSERT INTO unit_status_logs (unit_id, previous_status, new_status, reason, changed_by)
                VALUES (?, 'None', ?, 'Initial processing into inventory', 'staff')
                """,
                (uid, st)
            )

        # 5. Seed Blood Requests
        requests = [
            ("REQ-2026-0001", "City Care Hospital", "Dr. A. Verma", "Ramesh Chandran", "O+", "Packed Red Cells", 1, "Emergency", today, "Approved", "Emergency OT requirement approved immediately", "staff", today.isoformat()),
            ("REQ-2026-0002", "Manipal Hospital", "Dr. Sunita Rao", "Deepika Sen", "A+", "Whole Blood", 1, "Urgent", today + timedelta(days=1), "Pending", None, None, None),
            ("REQ-2026-0003", "St. John Medical Center", "Dr. George K.", "Suresh Nair", "B+", "Whole Blood", 1, "Normal", today + timedelta(days=3), "Pending", None, None, None),
        ]

        for rid, hosp, req_by, pat, pbg, comp, qty, urg, req_d, st, dec_r, dec_by, dec_at in requests:
            db.execute(
                """
                INSERT INTO blood_requests (
                    request_id, hospital_name, requester_name, patient_name,
                    patient_blood_group, component_type, quantity, urgency,
                    required_date, status, decision_reason, decision_by, decision_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, hosp, req_by, pat, pbg, comp, qty, urg, req_d.isoformat(), st, dec_r, dec_by, dec_at)
            )

        # Allocate UNIT-2026-00001 to REQ-2026-0001 (demonstrating FEFO reservation)
        db.execute(
            """
            INSERT INTO allocations (allocation_id, request_id, unit_id, allocated_by, status)
            VALUES ('ALC-2026-0001', 'REQ-2026-0001', 'UNIT-2026-00001', 'staff', 'Allocated')
            """
        )
        db.execute("UPDATE blood_units SET status = 'Reserved' WHERE unit_id = 'UNIT-2026-00001'")

        # 6. Seed Sample Issue Transaction (REQ-2026-0000 completed prior)
        db.execute(
            """
            INSERT INTO blood_requests (
                request_id, hospital_name, requester_name, patient_name,
                patient_blood_group, component_type, quantity, urgency,
                required_date, status, decision_reason, decision_by, decision_at
            )
            VALUES ('REQ-2026-0000', 'Victoria Hospital', 'Dr. Mahesh', 'Kavita Reddy', 'B+', 'Whole Blood', 1, 'Emergency', ?, 'Fulfilled', 'Emergency delivery completed', 'staff', ?)
            """,
            ((today - timedelta(days=2)).isoformat(), (today - timedelta(days=2)).isoformat())
        )
        db.execute(
            """
            INSERT INTO issue_transactions (
                issue_id, request_id, unit_id, hospital_name, patient_name, issuing_staff, issue_timestamp, verification_notes
            )
            VALUES ('ISS-2026-0001', 'REQ-2026-0000', 'UNIT-2026-00005', 'Victoria Hospital', 'Kavita Reddy', 'staff', ?, 'Pre-transfusion crossmatch match 100% verified')
            """,
            ((today - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),)
        )
        db.execute("UPDATE blood_units SET status = 'Issued' WHERE unit_id = 'UNIT-2026-00005'")

        # 7. Seed Initial Audit Logs
        db.execute(
            """
            INSERT INTO audit_logs (actor_username, actor_role, action, entity_type, entity_id, details)
            VALUES ('admin', 'admin', 'SYSTEM_INITIALIZE', 'SYSTEM', 'DATABASE', 'Initial database schema and baseline data configured.')
            """
        )

        print("Database seeded with realistic demo data successfully!")
