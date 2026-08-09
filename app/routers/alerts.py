import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import OrgContext, get_current_user, require_org_role, require_stream_org_role
from app.models import Alert, User
from app.routers.auth import limiter
from app.schemas import AlertFeedbackIn, AlertOut
from app.security import OrgRole, utc_now
from app.services.discovery_service import update_prometheus_gauges
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)),
    db: Session = Depends(get_db),
    limit: int = 100,
    open_only: bool = True,
) -> list[AlertOut]:
    q = db.query(Alert).filter(Alert.org_id == ctx.org_id).order_by(Alert.created_at.desc())
    if open_only:
        q = q.filter(Alert.acknowledged.is_(False))
    rows = q.limit(min(limit, 500)).all()
    return [AlertOut.model_validate(r) for r in rows]


@router.get("/stream")
@limiter.limit("30/minute")
def stream_alerts(
    request: Request,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_stream_org_role(OrgRole.VIEWER)),
):
    """Server-Sent Events feed of newly-created alerts for the caller's org
    — polls for rows with id > last-seen every 2s, same shape as
    GET /alerts/stream's sibling in app/routers/traffic.py. Lets the
    frontend push a toast for a new alert instead of requiring a manual
    Alerts-page refresh."""
    org_id = ctx.org_id
    # Computed here, synchronously, at request time — not inside
    # event_stream() below. Async generators run none of their body until
    # first consumed, so computing this inside one would capture whatever
    # is "current" at first-read time (which, in production, follows the
    # request by only milliseconds — but is trivially provable-wrong in a
    # test that constructs the response and reads from it as separate
    # steps). Start at the current max id, not 0 — unlike traffic.py's
    # stream (a live feed, meant to show history), this one only notifies
    # about *new* alerts; starting at 0 would flood a client that just
    # connected with every alert the org has ever had.
    last_seen_id = (
        db.query(Alert.id).filter(Alert.org_id == org_id).order_by(Alert.id.desc()).limit(1).scalar() or 0
    )

    async def event_stream():
        nonlocal last_seen_id
        while True:
            rows = await run_in_threadpool(
                lambda lid=last_seen_id: db.query(Alert)
                .filter(Alert.org_id == org_id, Alert.id > lid)
                .order_by(Alert.id.asc())
                .limit(25)
                .all()
            )
            for row in rows:
                last_seen_id = row.id
                payload = AlertOut.model_validate(row).model_dump(mode="json")
                yield f"data: {json.dumps(payload)}\n\n"
            if not rows:
                yield f"event: heartbeat\ndata: {utc_now().isoformat()}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{alert_id}/ack")
def ack_alert(
    alert_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.query(Alert).filter(Alert.id == alert_id, Alert.org_id == ctx.org_id).one_or_none()
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


@router.post("/{alert_id}/feedback")
def submit_alert_feedback(
    alert_id: int,
    body: AlertFeedbackIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
):
    """Mark an alert as a confirmed real finding or a false positive.

    Feeds the ML retrain loop (app/services/ml_anomaly.py::train_from_db):
    events behind a "true_positive" alert are excluded from the next
    retrain's "normal" baseline so a confirmed attack doesn't get folded
    into what the model considers ordinary traffic. "false_positive" labels
    are recorded and surfaced (see GET /ml-models) but do not automatically
    retune per-endpoint sensitivity — an automatic feedback loop there would
    let anyone with editor access on a compromised account quietly suppress
    future detections by mass-mislabeling alerts as false positives.
    """
    row = db.query(Alert).filter(Alert.id == alert_id, Alert.org_id == ctx.org_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.feedback = body.label
    row.feedback_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="alert_feedback",
        actor=current_user.username,
        target=f"{row.alert_type}:{row.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"label": body.label},
        success=True,
    )
    return {"id": alert_id, "feedback": body.label}
