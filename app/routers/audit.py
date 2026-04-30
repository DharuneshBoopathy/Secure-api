from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import AuditLog
from app.routers.auth import limiter
from app.schemas import AuditOut
from app.security import Role

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", dependencies=[Depends(require_role(Role.ADMIN))])
@limiter.limit("60/minute")
def list_audit(
    request: Request,
    db: Session = Depends(get_db),
    cursor_id: int | None = Query(default=None, ge=1, description="Return rows with id < cursor_id (keyset pagination)"),
    limit: int = Query(default=25, ge=1, le=100),
    event_type: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> dict:
    q = db.query(AuditLog)
    if cursor_id is not None:
        q = q.filter(AuditLog.id < cursor_id)
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if from_ts:
        q = q.filter(AuditLog.timestamp >= from_ts)
    if to_ts:
        q = q.filter(AuditLog.timestamp <= to_ts)
    rows = q.order_by(AuditLog.id.desc()).limit(limit).all()
    next_cursor_id = rows[-1].id if len(rows) == limit else None
    return {
        "items": [AuditOut.model_validate(r) for r in rows],
        "next_cursor_id": next_cursor_id,
    }
