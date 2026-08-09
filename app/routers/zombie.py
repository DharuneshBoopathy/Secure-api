from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import OrgContext, get_current_user, require_org_role
from app.models import User, ZombieEndpointState
from app.schemas import ZombieActionIn, ZombieOut
from app.security import OrgRole, utc_now
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/zombie", tags=["zombie"])


@router.get("")
def list_zombie(
    ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)),
    db: Session = Depends(get_db),
    status: str | None = None,
    risk_level: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    """
    Read from the pre-computed ZombieEndpointState cache.
    Recomputation runs every 30 min via APScheduler — NOT on every GET request.
    """
    q = db.query(ZombieEndpointState).filter(ZombieEndpointState.org_id == ctx.org_id)
    if status:
        q = q.filter(ZombieEndpointState.status == status.upper())
    if risk_level:
        q = q.filter(ZombieEndpointState.risk_level == risk_level.upper())
    total = q.count()
    rows = (
        q.order_by(ZombieEndpointState.status.asc(), ZombieEndpointState.path_template.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": [ZombieOut.model_validate(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/summary")
def zombie_summary(ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)), db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(ZombieEndpointState.status, func.count(ZombieEndpointState.id))
        .filter(ZombieEndpointState.org_id == ctx.org_id)
        .group_by(ZombieEndpointState.status)
        .all()
    )
    return {"counts": {s: int(c) for s, c in rows}}


@router.post("/{state_id}/retire")
def retire_zombie(
    state_id: int,
    body: ZombieActionIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    row = (
        db.query(ZombieEndpointState)
        .filter(ZombieEndpointState.id == state_id, ZombieEndpointState.org_id == ctx.org_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Zombie endpoint state not found")
    row.retired = True
    row.retire_reason = body.reason
    row.retired_at = utc_now()
    row.status = "RETIRED"
    db.commit()
    log_audit_event(
        db,
        event_type="zombie_retired",
        actor=current_user.username,
        target=f"{row.method} {row.path_template}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"reason": body.reason},
        success=True,
    )
    return {"id": row.id, "status": row.status}


@router.post("/{state_id}/reactivate")
def reactivate_zombie(
    state_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    row = (
        db.query(ZombieEndpointState)
        .filter(ZombieEndpointState.id == state_id, ZombieEndpointState.org_id == ctx.org_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Zombie endpoint state not found")
    row.retired = False
    row.retire_reason = None
    row.retired_at = None
    from app.services.discovery_service import recompute_single_zombie_state
    recompute_single_zombie_state(db, row)
    log_audit_event(
        db,
        event_type="zombie_reactivated",
        actor=current_user.username,
        target=f"{row.method} {row.path_template}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"id": row.id, "status": row.status}
