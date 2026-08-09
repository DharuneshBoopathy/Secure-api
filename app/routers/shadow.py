from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import OrgContext, get_current_user, require_org_role
from app.models import KnownEndpoint, ShadowEndpoint, User
from app.schemas import ShadowAcknowledgeIn, ShadowOut
from app.security import OrgRole, utc_now
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/shadow", tags=["shadow"])


@router.get("")
def list_shadow(
    ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)),
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    risk_level: str | None = None,
    sort_by: str = Query(default="risk_score"),
) -> dict:
    q = db.query(ShadowEndpoint).filter(ShadowEndpoint.org_id == ctx.org_id)
    if risk_level:
        q = q.filter(ShadowEndpoint.risk_level == risk_level.upper())
    if sort_by == "hit_count":
        q = q.order_by(ShadowEndpoint.hit_count.desc())
    else:
        q = q.order_by(ShadowEndpoint.risk_score.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [ShadowOut.model_validate(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/{shadow_id}/acknowledge")
def acknowledge_shadow(
    shadow_id: int,
    body: ShadowAcknowledgeIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    row = db.query(ShadowEndpoint).filter(ShadowEndpoint.id == shadow_id, ShadowEndpoint.org_id == ctx.org_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Shadow endpoint not found")
    row.acknowledged = True
    row.acknowledged_reason = body.reason
    row.acknowledged_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="shadow_acknowledged",
        actor=current_user.username,
        target=f"{row.method} {row.path_normalized}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"reason": body.reason},
        success=True,
    )
    return {"id": row.id, "acknowledged": True}


@router.post("/{shadow_id}/add-to-registry")
def add_shadow_to_registry(
    shadow_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    row = db.query(ShadowEndpoint).filter(ShadowEndpoint.id == shadow_id, ShadowEndpoint.org_id == ctx.org_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Shadow endpoint not found")
    exists = (
        db.query(KnownEndpoint)
        .filter(
            KnownEndpoint.org_id == ctx.org_id,
            KnownEndpoint.method == row.method,
            KnownEndpoint.path_template == row.path_normalized,
        )
        .one_or_none()
    )
    if exists is None:
        db.add(
            KnownEndpoint(
                org_id=ctx.org_id, method=row.method, path_template=row.path_normalized, source="shadow_promotion"
            )
        )
    row.acknowledged = True
    row.acknowledged_reason = "Promoted to registry"
    row.acknowledged_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="shadow_promoted",
        actor=current_user.username,
        target=f"{row.method} {row.path_normalized}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"id": row.id, "promoted": True}
