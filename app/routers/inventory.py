from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import require_role
from app.models import DiscoveredEndpoint, KnownEndpoint, TrafficEvent
from app.routers.auth import limiter
from app.schemas import DiscoveredOut, IdleEndpointOut, StatsOut
from app.security import Role, utc_now

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/discovered", dependencies=[Depends(require_role(Role.VIEWER))])
@limiter.limit("120/minute")
def list_discovered(request: Request, db: Session = Depends(get_db)) -> list[DiscoveredOut]:
    rows = db.query(DiscoveredEndpoint).order_by(DiscoveredEndpoint.last_seen.desc()).limit(500).all()
    return [DiscoveredOut.model_validate(r) for r in rows]


@router.get("/shadow", dependencies=[Depends(require_role(Role.VIEWER))])
@limiter.limit("120/minute")
def list_shadow_apis(request: Request, db: Session = Depends(get_db)) -> list[DiscoveredOut]:
    rows = (
        db.query(DiscoveredEndpoint)
        .filter(DiscoveredEndpoint.documented.is_(False))
        .order_by(DiscoveredEndpoint.hit_count.desc())
        .limit(500)
        .all()
    )
    return [DiscoveredOut.model_validate(r) for r in rows]


@router.get("/idle", dependencies=[Depends(require_role(Role.VIEWER))])
@limiter.limit("120/minute")
def list_idle_registered(request: Request, db: Session = Depends(get_db)) -> list[IdleEndpointOut]:
    settings = get_settings()
    cutoff = utc_now() - timedelta(hours=settings.idle_threshold_hours)
    out: list[IdleEndpointOut] = []
    for row in db.query(KnownEndpoint).all():
        if row.last_traffic_at is None or row.last_traffic_at < cutoff:
            hrs = None
            if row.last_traffic_at:
                hrs = (utc_now() - row.last_traffic_at).total_seconds() / 3600.0
            out.append(
                IdleEndpointOut(
                    method=row.method,
                    path_template=row.path_template,
                    last_traffic=row.last_traffic_at,
                    hours_since_traffic=hrs,
                )
            )
    return out


@router.get("/stats", dependencies=[Depends(require_role(Role.VIEWER))])
@limiter.limit("120/minute")
def stats(request: Request, db: Session = Depends(get_db)) -> StatsOut:
    since = utc_now() - timedelta(hours=1)
    ev = db.query(func.count(TrafficEvent.id)).filter(TrafficEvent.ts >= since).scalar() or 0
    undoc = (
        db.query(func.count(DiscoveredEndpoint.id))
        .filter(DiscoveredEndpoint.documented.is_(False))
        .scalar()
        or 0
    )
    from app.models import Alert

    alerts = db.query(func.count(Alert.id)).filter(Alert.acknowledged.is_(False)).scalar() or 0
    known = db.query(func.count(KnownEndpoint.id)).scalar() or 0
    return StatsOut(
        events_last_hour=int(ev),
        discovered_undocumented=int(undoc),
        open_alerts=int(alerts),
        known_endpoints=int(known),
    )
