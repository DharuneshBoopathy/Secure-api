from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Alert, DiscoveredEndpoint, KnownEndpoint, ShadowEndpoint, TrafficEvent, ZombieEndpointState
from app.services import metrics as prom
from app.services.alerts_util import recent_duplicate
from app.services.pathutil import is_documented, normalize_path_for_discovery
from app.security import utc_now


def get_known_templates(db: Session) -> list[tuple[str, str]]:
    rows = db.query(KnownEndpoint).all()
    return [(r.method, r.path_template) for r in rows]


def touch_known_endpoint_usage(db: Session, method: str, path: str) -> None:
    """Update last_traffic_at for matching OpenAPI path templates."""
    m = method.upper()
    for row in db.query(KnownEndpoint).filter(KnownEndpoint.method == m).all():
        if is_documented(method, path, [(row.method, row.path_template)]):
            row.last_traffic_at = utc_now()


def upsert_discovered(db: Session, method: str, path_normalized: str, *, documented: bool) -> None:
    row = (
        db.query(DiscoveredEndpoint)
        .filter(
            DiscoveredEndpoint.method == method,
            DiscoveredEndpoint.path_normalized == path_normalized,
        )
        .one_or_none()
    )
    now = utc_now()
    if row:
        row.last_seen = now
        row.hit_count = (row.hit_count or 0) + 1
        row.documented = documented
    else:
        db.add(
            DiscoveredEndpoint(
                method=method,
                path_normalized=path_normalized,
                first_seen=now,
                last_seen=now,
                hit_count=1,
                documented=documented,
            )
        )


def _shadow_risk(method: str, hit_count: int, auth_present: bool) -> tuple[int, str]:
    m = method.upper()
    if m in {"POST", "PUT", "PATCH", "DELETE"} and hit_count >= 10:
        return 95, "CRITICAL"
    if auth_present:
        return 78, "HIGH"
    if m == "GET" and hit_count <= 1:
        return 20, "LOW"
    if m == "GET":
        return 55, "MEDIUM"
    return 70, "HIGH"


def upsert_shadow_endpoint(
    db: Session,
    *,
    method: str,
    path: str,
    client_ip: str | None,
    auth_present: bool,
    status_code: int,
) -> ShadowEndpoint:
    norm = normalize_path_for_discovery(path)
    row = (
        db.query(ShadowEndpoint)
        .filter(ShadowEndpoint.method == method, ShadowEndpoint.path_normalized == norm)
        .one_or_none()
    )
    now = utc_now()
    if row is None:
        score, level = _shadow_risk(method, 1, auth_present)
        row = ShadowEndpoint(
            method=method,
            path_normalized=norm,
            first_seen=now,
            last_seen=now,
            hit_count=1,
            risk_score=score,
            risk_level=level,
            sample_ips=[client_ip] if client_ip else [],
            evidence={"recent_events": [{"ts": now.isoformat(), "status_code": status_code}]},
        )
        db.add(row)
        db.flush()
        return row

    row.last_seen = now
    row.hit_count += 1
    score, level = _shadow_risk(method, row.hit_count, auth_present)
    row.risk_score = score
    row.risk_level = level
    ips = list(row.sample_ips or [])
    if client_ip and client_ip not in ips:
        ips.append(client_ip)
    row.sample_ips = ips[-10:]
    ev = dict(row.evidence or {})
    recent = list(ev.get("recent_events") or [])
    recent.append({"ts": now.isoformat(), "status_code": status_code})
    ev["recent_events"] = recent[-25:]
    row.evidence = ev
    return row


def recompute_discovered_documented_flags(db: Session) -> None:
    templates = get_known_templates(db)
    for d in db.query(DiscoveredEndpoint).all():
        d.documented = is_documented(d.method, d.path_normalized, templates)
    db.commit()


def _zombie_risk(status: str, method: str) -> str:
    write_method = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    if status == "DEAD" and write_method:
        return "CRITICAL"
    if status == "DEAD":
        return "HIGH"
    if status == "ZOMBIE":
        return "HIGH"
    if status == "IDLE":
        return "MEDIUM"
    if status == "DECLINING":
        return "LOW"
    return "LOW"


def _classify_zombie_status(
    now: datetime,
    last_request_at: datetime | None,
    r14: int,
    r30: int,
    avg_rpd: float,
    settings,
) -> str:
    age_days = (now - last_request_at).total_seconds() / 86400.0 if last_request_at else 10_000.0
    if age_days >= settings.zombie_dead_threshold_days:
        return "DEAD"
    if age_days >= settings.zombie_idle_threshold_days:
        return "ZOMBIE"
    if age_days >= 7:
        return "IDLE"
    if r14 < max(1, (r30 / 2)):
        return "DECLINING"
    if avg_rpd <= settings.zombie_low_traffic_rpd and age_days >= 1:
        return "DECLINING"
    return "ACTIVE"


def recompute_zombie_states(db: Session) -> int:
    """
    Recompute all zombie states.

    Performance fix: load only documented=True events within the 30-day window
    once, then match against each endpoint template.  This replaces the prior
    O(N * total_events) per-endpoint full-scan with a single bounded query.
    """
    now = utc_now()
    settings = get_settings()
    d7 = now - timedelta(days=7)
    d14 = now - timedelta(days=14)
    d30 = now - timedelta(days=max(30, settings.zombie_window_days))

    # Single SQL query — only documented events in the look-back window.
    recent = (
        db.query(TrafficEvent.ts, TrafficEvent.method, TrafficEvent.path)
        .filter(TrafficEvent.is_documented.is_(True), TrafficEvent.ts >= d30)
        .all()
    )

    # Group by (method, path) so template matching iterates unique paths, not raw rows.
    from collections import defaultdict
    path_ts: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for row in recent:
        path_ts[(row.method.upper(), row.path)].append(row.ts)

    touched = 0
    for endpoint in db.query(KnownEndpoint).all():
        method = endpoint.method.upper()
        tmpl = endpoint.path_template

        matching_ts: list[datetime] = []
        for (m, p), ts_list in path_ts.items():
            if m == method and is_documented(method, p, [(method, tmpl)]):
                matching_ts.extend(ts_list)

        last_request_at = max(matching_ts, default=endpoint.last_traffic_at)
        r7 = sum(1 for ts in matching_ts if ts >= d7)
        r14 = sum(1 for ts in matching_ts if ts >= d14)
        r30 = len(matching_ts)
        avg_rpd = float(r30) / float(max(1, settings.zombie_window_days))

        state = (
            db.query(ZombieEndpointState)
            .filter(ZombieEndpointState.method == method, ZombieEndpointState.path_template == tmpl)
            .one_or_none()
        )
        if state is None:
            state = ZombieEndpointState(method=method, path_template=tmpl)
            db.add(state)

        if not state.retired:
            state.status = _classify_zombie_status(now, last_request_at, r14, r30, avg_rpd, settings)
        state.last_request_at = last_request_at
        state.requests_7d = r7
        state.requests_14d = r14
        state.requests_30d = r30
        state.avg_daily_requests_30d = avg_rpd
        state.risk_level = _zombie_risk(state.status, method)
        touched += 1

    db.commit()
    return touched


def recompute_single_zombie_state(db: Session, state: ZombieEndpointState) -> None:
    """Recompute one endpoint's zombie state — used after reactivation."""
    settings = get_settings()
    now = utc_now()
    d7 = now - timedelta(days=7)
    d14 = now - timedelta(days=14)
    d30 = now - timedelta(days=max(30, settings.zombie_window_days))
    method = state.method.upper()
    tmpl = state.path_template

    rows = (
        db.query(TrafficEvent.ts, TrafficEvent.path)
        .filter(
            TrafficEvent.method == method,
            TrafficEvent.is_documented.is_(True),
            TrafficEvent.ts >= d30,
        )
        .all()
    )
    matching_ts = [r.ts for r in rows if is_documented(method, r.path, [(method, tmpl)])]

    last_request_at = max(matching_ts, default=None)
    r7 = sum(1 for ts in matching_ts if ts >= d7)
    r14 = sum(1 for ts in matching_ts if ts >= d14)
    r30 = len(matching_ts)
    avg_rpd = float(r30) / float(max(1, settings.zombie_window_days))

    state.last_request_at = last_request_at
    state.requests_7d = r7
    state.requests_14d = r14
    state.requests_30d = r30
    state.avg_daily_requests_30d = avg_rpd
    state.status = _classify_zombie_status(now, last_request_at, r14, r30, avg_rpd, settings)
    state.risk_level = _zombie_risk(state.status, method)
    db.commit()


def scan_idle_documented_endpoints(db: Session) -> int:
    """Registered APIs with no hits in the idle window (shadow retirement / misconfig)."""
    settings = get_settings()
    cutoff = utc_now() - timedelta(hours=settings.idle_threshold_hours)
    count = 0
    for row in db.query(KnownEndpoint).all():
        if row.last_traffic_at is None or row.last_traffic_at < cutoff:
            count += 1
            if not recent_duplicate(
                db,
                alert_type="idle_documented_endpoint",
                method=row.method,
                path=row.path_template[:1024],
                within_hours=settings.idle_threshold_hours,
            ):
                db.add(
                    Alert(
                        alert_type="idle_documented_endpoint",
                        severity="low",
                        title="Registered API path idle",
                        detail=(
                            f"No traffic for {row.method} {row.path_template} within "
                            f"{settings.idle_threshold_hours}h."
                        ),
                        method=row.method,
                        path=row.path_template[:1024],
                    )
                )
    prom.IDLE_DOCUMENTED.set(count)
    db.commit()
    return count


def update_prometheus_gauges(db: Session) -> None:
    undoc = (
        db.query(func.count(DiscoveredEndpoint.id))
        .filter(DiscoveredEndpoint.documented.is_(False))
        .scalar()
        or 0
    )
    open_a = (
        db.query(func.count(Alert.id)).filter(Alert.acknowledged.is_(False)).scalar() or 0
    )
    prom.DISCOVERED_SHADOW.set(int(undoc))
    prom.SHADOW_APIS_DETECTED_TOTAL.set(int(undoc))
    prom.OPEN_ALERTS.set(int(open_a))
    sev_rows = db.query(Alert.severity, func.count(Alert.id)).filter(Alert.acknowledged.is_(False)).group_by(Alert.severity).all()
    for severity, count in sev_rows:
        prom.ACTIVE_ALERTS_TOTAL.labels(severity=severity).set(int(count))
    z_rows = db.query(ZombieEndpointState.status, func.count(ZombieEndpointState.id)).group_by(ZombieEndpointState.status).all()
    for status, count in z_rows:
        prom.ZOMBIE_APIS_TOTAL.labels(status=status).set(int(count))
