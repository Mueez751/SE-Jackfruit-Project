import io
import csv
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from app.database import get_db
from app.services.inventory_service import auto_mark_expired_units

def generate_inventory_report() -> List[Dict[str, Any]]:
    """Report on inventory stock levels by group, component and status (BBMS-F-017)."""
    auto_mark_expired_units()
    with get_db() as db:
        rows = db.execute(
            """
            SELECT blood_group, component_type, status, COUNT(*) as count, SUM(volume_ml) as total_volume_ml
            FROM blood_units
            GROUP BY blood_group, component_type, status
            ORDER BY blood_group, component_type, status
            """
        ).fetchall()
        return [dict(r) for r in rows]

def generate_donations_report(from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Report on donations and collections over a given period (BBMS-F-017)."""
    with get_db() as db:
        sql = """
        SELECT c.collection_id, c.donor_id, d.full_name as donor_name, c.blood_group,
               c.volume_ml, c.collection_date, c.collected_by, u.unit_id, u.status as unit_status
        FROM blood_collections c
        JOIN donors d ON c.donor_id = d.donor_id
        LEFT JOIN blood_units u ON c.collection_id = u.collection_id
        WHERE 1=1
        """
        params = []
        if from_date:
            sql += " AND c.collection_date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND c.collection_date <= ?"
            params.append(to_date)
        sql += " ORDER BY c.collection_date DESC"
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def generate_issues_report(from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Report on issued blood units and recipients (BBMS-F-017)."""
    with get_db() as db:
        sql = """
        SELECT i.issue_id, i.request_id, i.unit_id, u.blood_group, u.component_type,
               i.hospital_name, i.patient_name, i.issuing_staff, i.issue_timestamp
        FROM issue_transactions i
        JOIN blood_units u ON i.unit_id = u.unit_id
        WHERE 1=1
        """
        params = []
        if from_date:
            sql += " AND date(i.issue_timestamp) >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND date(i.issue_timestamp) <= ?"
            params.append(to_date)
        sql += " ORDER BY i.issue_timestamp DESC"
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def generate_discards_and_expiries_report() -> List[Dict[str, Any]]:
    """Report on expired and discarded units with recorded reasons (BBMS-F-017)."""
    auto_mark_expired_units()
    with get_db() as db:
        rows = db.execute(
            """
            SELECT u.unit_id, u.blood_group, u.component_type, u.expiry_date, u.status,
                   l.reason, l.changed_by, l.timestamp as logged_at
            FROM blood_units u
            LEFT JOIN unit_status_logs l ON u.unit_id = l.unit_id AND l.new_status = u.status
            WHERE u.status IN ('Expired', 'Discarded')
            ORDER BY u.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

def export_report_to_csv(report_type: str) -> str:
    """Export selected report data to standard CSV string for spreadsheet analysis (BBMS-F-017)."""
    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "inventory":
        data = generate_inventory_report()
        writer.writerow(["Blood Group", "Component Type", "Status", "Unit Count", "Total Volume (mL)"])
        for r in data:
            writer.writerow([r["blood_group"], r["component_type"], r["status"], r["count"], r["total_volume_ml"]])

    elif report_type == "donations":
        data = generate_donations_report()
        writer.writerow(["Collection ID", "Donor ID", "Donor Name", "Blood Group", "Volume (mL)", "Collection Date", "Collected By", "Unit ID", "Unit Status"])
        for r in data:
            writer.writerow([r["collection_id"], r["donor_id"], r["donor_name"], r["blood_group"], r["volume_ml"], r["collection_date"], r["collected_by"], r["unit_id"], r["unit_status"]])

    elif report_type == "issues":
        data = generate_issues_report()
        writer.writerow(["Issue ID", "Request ID", "Unit ID", "Blood Group", "Component", "Hospital Name", "Patient Name", "Issuing Staff", "Issue Timestamp"])
        for r in data:
            writer.writerow([r["issue_id"], r["request_id"], r["unit_id"], r["blood_group"], r["component_type"], r["hospital_name"], r["patient_name"], r["issuing_staff"], r["issue_timestamp"]])

    elif report_type == "discards_expiries":
        data = generate_discards_and_expiries_report()
        writer.writerow(["Unit ID", "Blood Group", "Component", "Expiry Date", "Status", "Reason", "Action By", "Timestamp"])
        for r in data:
            writer.writerow([r["unit_id"], r["blood_group"], r["component_type"], r["expiry_date"], r["status"], r["reason"], r["changed_by"], r["logged_at"]])

    else:
        writer.writerow(["Error", "Unknown report type"])

    return output.getvalue()
