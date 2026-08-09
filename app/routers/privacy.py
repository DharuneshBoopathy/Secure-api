from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import User
from app.routers.auth import limiter
from app.security import Role
from app.services.audit_service import log_audit_event
from app.services.traffic_processor import delete_traffic_for_client

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.delete("/traffic-data")
@limiter.limit("10/minute")
def delete_traffic_data(
    request: Request,
    current_user: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
    client_ip: str | None = Query(default=None, max_length=64),
    session_id: str | None = Query(default=None, max_length=256),
) -> dict:
    """Right-to-delete: permanently purge captured traffic for an IP and/or
    session (admin only). At least one identifier is required."""
    if not client_ip and not session_id:
        raise HTTPException(status_code=422, detail="client_ip or session_id is required")
    deleted = delete_traffic_for_client(db, client_ip=client_ip, session_id=session_id)
    log_audit_event(
        db,
        event_type="traffic_data_deleted",
        actor=current_user.username,
        target="traffic_events",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"client_ip": client_ip, "session_id": session_id, "deleted": deleted},
    )
    return {"deleted": deleted}
