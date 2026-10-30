from fastapi import APIRouter, Depends
from app.services.notification_service import (
    list_notifications, mark_notification_read, mark_all_notifications_read
)
from app.routers.auth import require_roles

router = APIRouter(prefix="/api/notifications", tags=["Notifications & Alerts"])

@router.get("")
def get_alerts(unread_only: bool = False, current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Retrieve operational alerts: low stock, upcoming expiry, urgent requests (BBMS-F-018). Staff and Admin only."""
    return list_notifications(unread_only=unread_only)

@router.post("/{alert_id}/read")
def read_alert(alert_id: int, current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Mark single notification alert as read. Staff and Admin only."""
    mark_notification_read(alert_id)
    return {"message": "Notification marked as read."}

@router.post("/read-all")
def read_all(current_user: dict = Depends(require_roles(["staff", "admin"]))):
    """Mark all notification alerts as read. Staff and Admin only."""
    mark_all_notifications_read()
    return {"message": "All notifications marked as read."}
