import functools
import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Organization, RefreshToken, TrafficEvent
from app.security import utc_now
from app.services import leader
from app.services import metrics as prom
from app.services.discovery_service import recompute_zombie_states, scan_idle_documented_endpoints, update_prometheus_gauges
from app.services.ml_anomaly import save_model, train_from_db
from app.services.traffic_processor import aggregate_and_prune_old_traffic, refresh_gauges

log = logging.getLogger(__name__)


def _leader_only(fn):
    """Skip this job on every replica except the elected leader (see
    app/services/leader.py) — for jobs that WRITE shared state (retrain,
    prune, idle-scan): running them on every replica would duplicate work
    and race on the same rows. NOT applied to _gauges: that one only sets
    this process's own in-memory Prometheus metric objects, and Prometheus
    scrapes each replica's /metrics independently — gating it would leave
    non-leader replicas serving stale/zero metrics forever, which is worse
    than the "runs N times" problem this decorator exists to solve."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not leader.is_leader():
            log.debug("Skipping %s: not the elected leader in this Redis-coordinated deployment", fn.__name__)
            return
        return fn(*args, **kwargs)

    return wrapper


@_leader_only
def _retrain_ml():
    # One model per org (see app/services/ml_anomaly.py) — training org A's
    # and org B's traffic together would leak each tenant's behavioral
    # baseline into the other's model, on top of just being less accurate.
    db = SessionLocal()
    try:
        for org_id in [row.id for row in db.query(Organization.id).all()]:
            try:
                model = train_from_db(db, org_id)
                if model:
                    save_model(db, org_id, model)
                    log.info("ML model retrained and persisted (org_id=%s)", org_id)
            except Exception:
                log.exception("ML retrain failed for org_id=%s", org_id)
        prom.ML_LAST_RETRAIN_TIMESTAMP.set(utc_now().timestamp())
    except Exception:
        log.exception("ML retrain failed")
    finally:
        db.close()


@_leader_only
def _idle_scan():
    db = SessionLocal()
    try:
        # Idle/zombie state is per-org (matching against org A's KnownEndpoint
        # templates and org B's traffic to the same path would misclassify
        # both), so this loops every organization rather than running once
        # globally.
        for org_id in [row.id for row in db.query(Organization.id).all()]:
            scan_idle_documented_endpoints(db, org_id)
            recompute_zombie_states(db, org_id)
        refresh_gauges(db)
    except Exception:
        log.exception("Idle scan failed")
    finally:
        db.close()


def _gauges():
    db = SessionLocal()
    try:
        update_prometheus_gauges(db)
    except Exception:
        log.exception("Gauge refresh failed")
    finally:
        db.close()


@_leader_only
def _traffic_rollup():
    db = SessionLocal()
    try:
        aggregate_and_prune_old_traffic(db, keep_days=30)
    except Exception:
        log.exception("Traffic rollup failed")
    finally:
        db.close()


def prune_stale_traffic(db: Session, *, chunk_size: int = 5000) -> int:
    """Delete TrafficEvent rows older than ``zombie_window_days`` in bounded chunks.

    Chunked deletion prevents long table locks:
    - Fetch up to ``chunk_size`` IDs matching the cutoff filter.
    - Delete exactly those IDs and commit.
    - Repeat until no rows remain.

    Returns the total number of rows deleted.
    """
    settings = get_settings()
    cutoff = utc_now() - timedelta(days=settings.zombie_window_days)
    total_deleted = 0

    while True:
        ids = [
            row.id
            for row in db.query(TrafficEvent.id)
            .filter(TrafficEvent.ts < cutoff)
            .limit(chunk_size)
            .all()
        ]
        if not ids:
            break

        deleted = (
            db.query(TrafficEvent)
            .filter(TrafficEvent.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        total_deleted += deleted
        log.info(
            "Pruned %d stale traffic events in this chunk (running total: %d)",
            deleted,
            total_deleted,
        )

        # If we got fewer rows than the chunk limit, there are no more to delete.
        if len(ids) < chunk_size:
            break

    return total_deleted


@_leader_only
def _prune_stale_traffic():
    db = SessionLocal()
    try:
        total = prune_stale_traffic(db)
        if total:
            log.info("Traffic pruning complete: %d rows removed", total)
        else:
            log.debug("Traffic pruning: no stale rows found")
    except Exception:
        log.exception("Traffic pruning failed")
        db.rollback()
    finally:
        db.close()


@_leader_only
def _prune_expired_refresh_tokens():
    """Delete expired and old revoked refresh token rows.

    Removes:
    - Any token whose ``expires_at`` is in the past (can never be used again).
    - Revoked tokens whose ``created_at`` is older than 30 days (audit grace period
      has elapsed; no replay risk remains).

    Non-expired, non-revoked tokens are never touched.
    """
    db = SessionLocal()
    try:
        now = utc_now()
        revoked_cutoff = now - timedelta(days=30)
        deleted = (
            db.query(RefreshToken)
            .filter(
                (RefreshToken.expires_at < now)
                | (
                    (RefreshToken.revoked.is_(True))
                    & (RefreshToken.created_at < revoked_cutoff)
                )
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            log.info("Pruned %d expired/revoked refresh token rows", deleted)
        else:
            log.debug("Refresh token pruning: nothing to remove")
    except Exception:
        log.exception("Refresh token pruning failed")
        db.rollback()
    finally:
        db.close()


def run_bootstrap_training() -> None:
    """Background-friendly one-shot train after startup."""
    _retrain_ml()


def register_jobs(sched: BackgroundScheduler) -> None:
    settings = get_settings()
    sched.add_job(
        _retrain_ml,
        "interval",
        minutes=max(settings.ml_retrain_minutes, 5),
        id="ml_retrain",
        replace_existing=True,
    )
    sched.add_job(_idle_scan, "interval", minutes=30, id="idle_scan")
    sched.add_job(_gauges, "interval", minutes=2, id="gauges")
    sched.add_job(_traffic_rollup, "interval", hours=24, id="traffic_rollup")
    sched.add_job(_prune_stale_traffic, "interval", hours=12, id="prune_stale_traffic")
    sched.add_job(_prune_expired_refresh_tokens, "interval", hours=24, id="prune_refresh_tokens")
