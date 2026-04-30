import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

from app.models import Alert, DiscoveredEndpoint, KnownEndpoint, TrafficDailySummary, TrafficEvent
from app.security import utc_now
from app.services import metrics as prom
from app.services.alerts_util import recent_duplicate
from app.services.discovery_service import (
    get_known_templates,
    touch_known_endpoint_usage,
    upsert_discovered,
    upsert_shadow_endpoint,
)
from app.services.ml_anomaly import is_anomaly, load_model, score_event
from app.services.pathutil import is_documented, normalize_path_for_discovery


def process_single_event(
    db: Session,
    *,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    client_ip: str | None,
    user_agent: str | None,
    auth_present: bool,
    body_bytes: int,
    request_size_bytes: int,
    response_size_bytes: int,
    content_type: str | None,
    x_forwarded_for: str | None,
    referer: str | None,
    monitor_key: str | None,
    session_id: str | None,
    gateway: str | None,
    raw_ref: str | None,
    model,
    commit: bool = True,
    templates: list[tuple[str, str]] | None = None,
) -> TrafficEvent:
    # `templates` is an optional pre-fetched cache so batch callers don't
    # re-query KnownEndpoint per event (was N+1 for 10k-event batches).
    if templates is None:
        templates = get_known_templates(db)
    doc = is_documented(method, path, templates)
    norm = normalize_path_for_discovery(path)
    m = method.upper()

    event = TrafficEvent(
        ts=utc_now(),
        method=m,
        path=path[:1024],
        status_code=status_code,
        latency_ms=latency_ms,
        response_time_ms=latency_ms,
        client_ip=client_ip,
        source_ip=client_ip,
        user_agent=(user_agent or "")[:512] or None,
        content_type=(content_type or "")[:128] or None,
        x_forwarded_for=(x_forwarded_for or "")[:256] or None,
        referer=(referer or "")[:512] or None,
        auth_present=auth_present,
        body_bytes=body_bytes,
        request_size_bytes=max(0, request_size_bytes),
        response_size_bytes=max(0, response_size_bytes),
        monitor_key=(monitor_key or "")[:128] or None,
        session_id=(session_id or "")[:256] or None,
        gateway=gateway,
        raw_ref=raw_ref,
        is_documented=doc,
    )
    db.add(event)
    db.flush()

    # Never let a malformed / stale model pickle crash the ingest path.
    # If scoring fails we record a zero score and let the next scheduled
    # retrain rebuild the model from fresh traffic.
    try:
        score, features = score_event(model, event, is_new_path=not doc)
        anomalous = is_anomaly(model, score)
    except Exception:
        log.exception(
            "ML scoring failed for %s %s — degrading to score=0", m, path[:120]
        )
        score, features, anomalous = 0.0, {}, False
    event.anomaly_score = score
    event.is_anomaly = anomalous
    event.anomaly_features = features
    prom.API_REQUESTS_TOTAL.labels(method=m, path=norm[:120], status=str(status_code)).inc()
    prom.API_REQUEST_DURATION_SECONDS.labels(method=m, path=norm[:120]).inc(max(0.0, latency_ms / 1000.0))
    if anomalous and not recent_duplicate(
        db, alert_type="traffic_anomaly", method=m, path=path[:1024], within_hours=1
    ):
        prom.ANOMALY_FLAGGED.inc()
        prom.ANOMALY_DETECTIONS_TOTAL.inc()
        db.add(
            Alert(
                alert_type="traffic_anomaly",
                severity="medium",
                title="Anomalous API request pattern",
                detail=f"IsolationForest score={score:.4f} for {m} {path[:500]}",
                method=m,
                path=path[:1024],
            )
        )

    upsert_discovered(db, m, norm, documented=doc)
    if doc:
        touch_known_endpoint_usage(db, m, path)
    if not doc:
        upsert_shadow_endpoint(
            db,
            method=m,
            path=path,
            client_ip=client_ip,
            auth_present=auth_present,
            status_code=status_code,
        )
        prom.UNDOCUMENTED_HIT.inc()
        if not recent_duplicate(
            db, alert_type="undocumented_api", method=m, path=norm[:1024], within_hours=6
        ):
            db.add(
                Alert(
                    alert_type="undocumented_api",
                    severity="high",
                    title="Traffic to undocumented endpoint",
                    detail=f"Observed {m} {norm} — not present in registered OpenAPI.",
                    method=m,
                    path=norm[:1024],
                )
            )

    prom.EVENTS_INGESTED.labels(gateway=gateway or "unknown").inc()
    if commit:
        db.commit()
        db.refresh(event)
    return event


def refresh_gauges(db: Session) -> None:
    from app.services.discovery_service import update_prometheus_gauges

    update_prometheus_gauges(db)


def aggregate_and_prune_old_traffic(db: Session, *, keep_days: int = 30, chunk_size: int = 5000) -> int:
    """Aggregate expired traffic rows into daily summaries and delete them.

    Rows are processed in chunks of ``chunk_size`` to keep memory flat —
    the previous .all() approach loaded every expired row at once.
    Each chunk is committed independently so a mid-run failure leaves
    already-processed data in the summary table rather than rolling back
    everything.
    """
    cutoff = utc_now() - timedelta(days=keep_days)
    total_pruned = 0

    while True:
        rows = (
            db.query(TrafficEvent)
            .filter(TrafficEvent.ts < cutoff)
            .order_by(TrafficEvent.id)
            .limit(chunk_size)
            .all()
        )
        if not rows:
            break

        # Aggregate this chunk into a local dict keyed by (method, path, day).
        grouped: dict[tuple[str, str, datetime], dict] = {}
        for row in rows:
            day = row.ts.replace(hour=0, minute=0, second=0, microsecond=0)
            key = (row.method, normalize_path_for_discovery(row.path), day)
            if key not in grouped:
                grouped[key] = {"count": 0, "rt_sum": 0.0, "errors": 0}
            grouped[key]["count"] += 1
            grouped[key]["rt_sum"] += row.response_time_ms or 0.0
            grouped[key]["errors"] += 1 if row.status_code >= 400 else 0

        # Upsert into TrafficDailySummary.
        for (method, path, day), agg in grouped.items():
            count = agg["count"]
            avg_rt = agg["rt_sum"] / float(max(1, count))
            errors = agg["errors"]
            existing = (
                db.query(TrafficDailySummary)
                .filter(
                    TrafficDailySummary.day == day,
                    TrafficDailySummary.method == method,
                    TrafficDailySummary.path_normalized == path,
                )
                .one_or_none()
            )
            if existing:
                existing.request_count += count
                existing.error_count += errors
                existing.avg_response_time_ms = avg_rt
            else:
                db.add(
                    TrafficDailySummary(
                        day=day,
                        method=method,
                        path_normalized=path,
                        request_count=count,
                        error_count=errors,
                        avg_response_time_ms=avg_rt,
                    )
                )

        # Delete the chunk and commit before loading the next one.
        ids = [r.id for r in rows]
        db.query(TrafficEvent).filter(TrafficEvent.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        total_pruned += len(rows)

        # Fewer rows than the chunk limit means we've reached the end.
        if len(rows) < chunk_size:
            break

    return total_pruned
