from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import Alert, User
from app.schemas import AlertOut
from app.security import Role
from app.services.discovery_service import update_prometheus_gauges
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", dependencies=[Depends(require_role(Role.VIEWER))])
def list_alerts(
    db: Session = Depends(get_db),
    limit: int = 100,
    open_only: bool = True,
) -> list[AlertOut]:
    q = db.query(Alert).order_by(Alert.created_at.desc())
    if open_only:
        q = q.filter(Alert.acknowledged.is_(False))
    rows = q.limit(min(limit, 500)).all()
    return [AlertOut.model_validate(r) for r in rows]


@router.post("/{alert_id}/ack")
def ack_alert(
    alert_id: int,
    request: Request,
    current_user: User = Depends(require_role(Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.query(Alert).filter(Alert.id == alert_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.acknowledged = True
    db.commit()
    update_prometheus_gauges(db)
    log_audit_event(
        db,
        event_type="alert_acknowledged",
        actor=current_user.username,
        target=f"{row.alert_type}:{row.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"id": alert_id, "acknowledged": True}
