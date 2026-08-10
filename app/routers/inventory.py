from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import OrgContext, require_org_role
from app.models import DiscoveredEndpoint, KnownEndpoint, TrafficDailySummary, TrafficEvent
from app.routers.auth import limiter
from app.schemas import DiscoveredOut, IdleEndpointOut, StatsOut, TrafficTrendPoint
from app.security import OrgRole, utc_now

router = APIRouter(prefix="/inventory", tags=["inventory"])

# Raw TrafficEvent rows only survive this long — the daily rollup job
# (app/services/traffic_processor.py::aggregate_and_prune_old_traffic, run by
# the scheduler with keep_days=30) folds anything older into
# traffic_daily_summary and deletes the raw rows. Any trend window reaching
# past this boundary therefore *has* to read the summary table; that's what
# it exists for.
RAW_RETENTION_DAYS = 30

# Upper bound on the trend window. Declared once so the request validation and
# the loop that materializes the series cannot drift apart: the bound is what
# keeps a caller from asking for a series with millions of points, and it needs
# to hold locally rather than only in the endpoint signature.
MAX_TREND_DAYS = 365


@router.get("/discovered")
@limiter.limit("120/minute")
def list_discovered(
    request: Request, ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)), db: Session = Depends(get_db)
) -> list[DiscoveredOut]:
    rows = (
        db.query(DiscoveredEndpoint)
        .filter(DiscoveredEndpoint.org_id == ctx.org_id)
        .order_by(DiscoveredEndpoint.last_seen.desc())
        .limit(500)
        .all()
    )
    return [DiscoveredOut.model_validate(r) for r in rows]


@router.get("/shadow")
@limiter.limit("120/minute")
def list_shadow_apis(
    request: Request, ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)), db: Session = Depends(get_db)
) -> list[DiscoveredOut]:
    rows = (
        db.query(DiscoveredEndpoint)
        .filter(DiscoveredEndpoint.org_id == ctx.org_id, DiscoveredEndpoint.documented.is_(False))
        .order_by(DiscoveredEndpoint.hit_count.desc())
        .limit(500)
        .all()
    )
    return [DiscoveredOut.model_validate(r) for r in rows]


@router.get("/idle")
@limiter.limit("120/minute")
def list_idle_registered(
    request: Request, ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)), db: Session = Depends(get_db)
) -> list[IdleEndpointOut]:
    settings = get_settings()
    cutoff = utc_now() - timedelta(hours=settings.idle_threshold_hours)
    out: list[IdleEndpointOut] = []
    for row in db.query(KnownEndpoint).filter(KnownEndpoint.org_id == ctx.org_id).all():
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


@router.get("/stats")
@limiter.limit("120/minute")
def stats(
    request: Request, ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)), db: Session = Depends(get_db)
) -> StatsOut:
    since = utc_now() - timedelta(hours=1)
    ev = (
        db.query(func.count(TrafficEvent.id))
        .filter(TrafficEvent.org_id == ctx.org_id, TrafficEvent.ts >= since)
        .scalar()
        or 0
    )
    undoc = (
        db.query(func.count(DiscoveredEndpoint.id))
        .filter(DiscoveredEndpoint.org_id == ctx.org_id, DiscoveredEndpoint.documented.is_(False))
        .scalar()
        or 0
    )
    from app.models import Alert

    alerts = (
        db.query(func.count(Alert.id))
        .filter(Alert.org_id == ctx.org_id, Alert.acknowledged.is_(False))
        .scalar()
        or 0
    )
    known = db.query(func.count(KnownEndpoint.id)).filter(KnownEndpoint.org_id == ctx.org_id).scalar() or 0
    return StatsOut(
        events_last_hour=int(ev),
        discovered_undocumented=int(undoc),
        open_alerts=int(alerts),
        known_endpoints=int(known),
    )


def _as_day(value: object) -> str | None:
    """Normalize a driver-dependent date value to an ISO date string.

    SQLite's date() returns a str; MySQL's DATE() returns a datetime.date.
    Both dialects are in play (SQLite in tests, MySQL in production), so the
    grouping key is normalized here rather than trusting either one.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


@router.get("/traffic-trend")
@limiter.limit("120/minute")
def traffic_trend(
    request: Request,
    ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)),
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=1, le=MAX_TREND_DAYS),
) -> list[TrafficTrendPoint]:
    """Daily request/error counts over the last ``days`` days.

    Reads from two sources and stitches them together, because neither one
    alone covers a window longer than the raw-retention period:

    * days newer than RAW_RETENTION_DAYS  -> aggregated from ``traffic_events``
      (the rollup job hasn't reached them yet, so the summary has no rows)
    * days older than that                -> read from ``traffic_daily_summary``
      (the raw rows have already been aggregated away and deleted)

    Both halves are bounded by an index on (org_id, ts) / (org_id, day)
    respectively and return at most ``days`` rows, so this stays cheap even
    once ``traffic_events`` is large.
    """
    now = utc_now()
    window_start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    raw_boundary = (now - timedelta(days=RAW_RETENTION_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)

    buckets: dict[str, dict[str, int]] = {}

    # --- Recent range: aggregate raw events on the fly. ---
    raw_rows = (
        db.query(
            func.date(TrafficEvent.ts).label("day"),
            func.count(TrafficEvent.id).label("requests"),
            func.sum(case((TrafficEvent.status_code >= 400, 1), else_=0)).label("errors"),
        )
        .filter(TrafficEvent.org_id == ctx.org_id, TrafficEvent.ts >= max(window_start, raw_boundary))
        .group_by(func.date(TrafficEvent.ts))
        .all()
    )
    for row in raw_rows:
        key = _as_day(row.day)
        if key:
            buckets[key] = {"requests": int(row.requests or 0), "errors": int(row.errors or 0)}

    # --- Older range: the raw rows are gone; only the summary has them. ---
    if window_start < raw_boundary:
        summary_rows = (
            db.query(
                func.date(TrafficDailySummary.day).label("day"),
                func.sum(TrafficDailySummary.request_count).label("requests"),
                func.sum(TrafficDailySummary.error_count).label("errors"),
            )
            .filter(
                TrafficDailySummary.org_id == ctx.org_id,
                TrafficDailySummary.day >= window_start,
                TrafficDailySummary.day < raw_boundary,
            )
            .group_by(func.date(TrafficDailySummary.day))
            .all()
        )
        for row in summary_rows:
            key = _as_day(row.day)
            if key:
                buckets[key] = {"requests": int(row.requests or 0), "errors": int(row.errors or 0)}

    # Emit a dense series (zero-filled) so the chart doesn't silently
    # compress quiet days into a misleadingly smooth line.
    out: list[TrafficTrendPoint] = []
    for offset in range(min(days, MAX_TREND_DAYS)):
        day = (window_start + timedelta(days=offset)).date().isoformat()
        point = buckets.get(day, {"requests": 0, "errors": 0})
        out.append(TrafficTrendPoint(day=day, requests=point["requests"], errors=point["errors"]))
    return out
