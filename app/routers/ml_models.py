from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import OrgContext, get_current_user, require_org_role
from app.models import MLModelState, User
from app.schemas import MLModelVersionOut
from app.security import OrgRole
from app.services.audit_service import log_audit_event
from app.services.ml_anomaly import decode_model_row

router = APIRouter(prefix="/ml-models", tags=["ml-models"])


@router.get("")
def list_model_versions(
    ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)),
    db: Session = Depends(get_db),
) -> list[MLModelVersionOut]:
    rows = (
        db.query(MLModelState)
        .filter(MLModelState.org_id == ctx.org_id)
        .order_by(MLModelState.id.desc())
        .all()
    )
    return [MLModelVersionOut.model_validate(r) for r in rows]


@router.post("/{model_id}/activate")
def activate_model_version(
    model_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.OWNER)),
    db: Session = Depends(get_db),
):
    """Roll back (or forward) to a specific previously-trained model
    version. Owner-gated: swapping which model scores every request for the
    org is more consequential than acknowledging one alert, so it sits
    above the editor-level bar used elsewhere in this router group."""
    target = (
        db.query(MLModelState)
        .filter(MLModelState.id == model_id, MLModelState.org_id == ctx.org_id)
        .one_or_none()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Model version not found")
    if decode_model_row(target) is None:
        raise HTTPException(status_code=422, detail="This model version failed verification and cannot be activated")

    db.query(MLModelState).filter(MLModelState.org_id == ctx.org_id).update({"is_active": False})
    target.is_active = True
    db.commit()
    log_audit_event(
        db,
        event_type="ml_model_activated",
        actor=current_user.username,
        target=f"ml_model_state:{model_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"id": model_id, "is_active": True}
