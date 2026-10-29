from fastapi import APIRouter
from app.services.notification_service import (
    list_notifications, mark_notification_read, mark_all_notifications_read
)

router = APIRouter(prefix="/api/notifications", tags=["Notifications & Alerts"])

@router.get("")
def get_alerts(unread_only: bool = False):
    """Retrieve operational alerts: low stock, upcoming expiry, urgent requests (BBMS-F-018)."""
    return list_notifications(unread_only=unread_only)

@router.post("/{alert_id}/read")
def read_alert(alert_id: int):
    mark_notification_read(alert_id)
    return {"message": "Notification marked as read."}

@router.post("/read-all")
def read_all():
    mark_all_notifications_read()
    return {"message": "All notifications marked as read."}
