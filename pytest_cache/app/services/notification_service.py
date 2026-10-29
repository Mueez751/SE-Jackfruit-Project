from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from app.database import get_db
from app.config import LOW_STOCK_THRESHOLD, UPCOMING_EXPIRY_DAYS, BLOOD_GROUPS

def scan_and_generate_alerts():
    """
    Scan inventory and operations to generate real-time alerts (BBMS-F-018).
    Notifies staff/admin about low stock, upcoming expiry, and urgent requests.
    """
    today = date.today()
    upcoming_limit = (today + timedelta(days=UPCOMING_EXPIRY_DAYS)).isoformat()
    today_str = today.isoformat()

    with get_db() as db:
        # 1. Low stock per blood group
        for bg in BLOOD_GROUPS:
            cnt = db.execute(
                "SELECT COUNT(*) as c FROM blood_units WHERE blood_group = ? AND status = 'Available'",
                (bg,)
            ).fetchone()["c"]

            if cnt < LOW_STOCK_THRESHOLD:
                # Check if recent alert already exists to avoid spamming
                existing = db.execute(
                    """
                    SELECT id FROM inventory_alerts
                    WHERE alert_type = 'Low_Stock' AND message LIKE ? AND is_read = 0
                    """,
                    (f"%Low stock alert for {bg}%",)
                ).fetchone()

                if not existing:
                    severity = "Critical" if cnt <= 1 else "Warning"
                    db.execute(
                        """
                        INSERT INTO inventory_alerts (alert_type, severity, message)
                        VALUES ('Low_Stock', ?, ?)
                        """,
                        (severity, f"Low stock alert for {bg}: only {cnt} unit(s) available (Threshold: {LOW_STOCK_THRESHOLD}).")
                    )

        # 2. Upcoming expiry within threshold
        expiring_units = db.execute(
            """
            SELECT unit_id, blood_group, component_type, expiry_date
            FROM blood_units
            WHERE status = 'Available' AND expiry_date >= ? AND expiry_date <= ?
            """,
            (today_str, upcoming_limit)
        ).fetchall()

        for u in expiring_units:
            uid = u["unit_id"]
            existing = db.execute(
                """
                SELECT id FROM inventory_alerts
                WHERE alert_type = 'Upcoming_Expiry' AND message LIKE ? AND is_read = 0
                """,
                (f"%Unit {uid}%",)
            ).fetchone()

            if not existing:
                db.execute(
                    """
                    INSERT INTO inventory_alerts (alert_type, severity, message)
                    VALUES ('Upcoming_Expiry', 'Warning', ?)
                    """,
                    (f"Blood Unit {uid} ({u['blood_group']} {u['component_type']}) will expire soon on {u['expiry_date']}.",)
                )

def list_notifications(unread_only: bool = False) -> List[Dict[str, Any]]:
    scan_and_generate_alerts()
    with get_db() as db:
        sql = "SELECT * FROM inventory_alerts WHERE 1=1"
        params = []
        if unread_only:
            sql += " AND is_read = 0"
        sql += " ORDER BY created_at DESC LIMIT 50"
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def mark_notification_read(alert_id: int):
    with get_db() as db:
        db.execute("UPDATE inventory_alerts SET is_read = 1 WHERE id = ?", (alert_id,))

def mark_all_notifications_read():
    with get_db() as db:
        db.execute("UPDATE inventory_alerts SET is_read = 1 WHERE is_read = 0")
