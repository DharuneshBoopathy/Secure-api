"""
Phase 4 (ML maturity) coverage: model versioning/rollback, per-org isolation,
per-endpoint baselining, explainability, and the false-positive/true-positive
feedback loop.

Covers:
  1. save_model / load_model round-trip per org; one org never sees another
     org's active model.
  2. save_model deactivates the previous version and prunes beyond
     MAX_MODEL_VERSIONS, keeping history for rollback.
  3. GET /ml-models lists versions newest-first with correct is_active flags.
  4. POST /ml-models/{id}/activate rolls back to an older version.
  5. Activating a version with a corrupted/tampered blob is rejected.
  6. explain_anomaly ranks features by |z-score| descending.
  7. An endpoint with >= MIN_SAMPLES_ENDPOINT events gets its own baseline;
     score_event uses it for that endpoint and the global model otherwise.
  8. Alert.feedback == "true_positive" excludes the linked TrafficEvent from
     the next retrain's baseline.
  9. POST /alerts/{id}/feedback records the label, timestamp, and audit log.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import OrgContext
from app.models import Alert, AuditLog, Base, MLModelState, Organization, OrgMembership, TrafficEvent, User
from app.routers.alerts import submit_alert_feedback
from app.routers.ml_models import activate_model_version, list_model_versions
from app.schemas import AlertFeedbackIn
from app.security import OrgRole, hash_password
from app.services.ml_anomaly import (
    MAX_MODEL_VERSIONS,
    MIN_SAMPLES_ENDPOINT,
    explain_anomaly,
    load_model,
    save_model,
    score_event,
    train_from_db,
)

_TABLES = [
    User.__table__, Organization.__table__, OrgMembership.__table__, AuditLog.__table__,
    TrafficEvent.__table__, Alert.__table__, MLModelState.__table__,
]


class _FakeRequest:
    class client:
        host = "127.0.0.1"

    class headers:
        @staticmethod
        def get(key, default=None):
            return default


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def two_orgs(db):
    owner_a = User(username="owner_a", password_hash=hash_password("P@ssw0rd123!"), role="editor", is_active=True)
    owner_b = User(username="owner_b", password_hash=hash_password("P@ssw0rd123!"), role="editor", is_active=True)
    db.add_all([owner_a, owner_b])
    db.commit()
    db.refresh(owner_a)
    db.refresh(owner_b)

    org_a = Organization(name="Org A", slug="org-a", owner_user_id=owner_a.id)
    org_b = Organization(name="Org B", slug="org-b", owner_user_id=owner_b.id)
    db.add_all([org_a, org_b])
    db.commit()
    db.refresh(org_a)
    db.refresh(org_b)
    return org_a, org_b


def _fake_model(sample_count: int) -> dict:
    # A minimal, plain-data stand-in for a trained model — save_model only
    # needs model["global"]["sample_count"], and pickling a dict of ints is
    # far cheaper than actually fitting sklearn estimators for tests that
    # only exercise versioning/rollback, not scoring.
    return {"global": {"sample_count": sample_count}, "endpoints": {}}


# ---------------------------------------------------------------------------
# save_model / load_model round-trip, per-org isolation
# ---------------------------------------------------------------------------

def test_save_and_load_model_round_trip_per_org(db, two_orgs):
    org_a, org_b = two_orgs
    save_model(db, org_a.id, _fake_model(42))

    loaded_a = load_model(db, org_a.id)
    assert loaded_a is not None
    assert loaded_a["global"]["sample_count"] == 42

    assert load_model(db, org_b.id) is None


def test_save_model_deactivates_previous_and_prunes_old_versions(db, two_orgs):
    org_a, _ = two_orgs
    for i in range(MAX_MODEL_VERSIONS + 3):
        save_model(db, org_a.id, _fake_model(i))

    rows = db.query(MLModelState).filter(MLModelState.org_id == org_a.id).order_by(MLModelState.id.desc()).all()
    assert len(rows) == MAX_MODEL_VERSIONS, "should prune anything beyond MAX_MODEL_VERSIONS"
    assert rows[0].is_active is True
    assert all(r.is_active is False for r in rows[1:])
    # The most recently saved model survives pruning.
    assert rows[0].sample_count == MAX_MODEL_VERSIONS + 2


# ---------------------------------------------------------------------------
# GET /ml-models, POST /ml-models/{id}/activate
# ---------------------------------------------------------------------------

def test_list_model_versions_endpoint_newest_first(db, two_orgs):
    org_a, _ = two_orgs
    save_model(db, org_a.id, _fake_model(1))
    save_model(db, org_a.id, _fake_model(2))

    ctx = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    versions = list_model_versions(ctx=ctx, db=db)

    assert [v.sample_count for v in versions] == [2, 1]
    assert versions[0].is_active is True
    assert versions[1].is_active is False


def test_activate_rolls_back_to_older_version(db, two_orgs):
    org_a, _ = two_orgs
    owner = db.query(User).filter(User.username == "owner_a").one()
    save_model(db, org_a.id, _fake_model(1))
    save_model(db, org_a.id, _fake_model(2))
    old_id = db.query(MLModelState).filter(MLModelState.sample_count == 1).one().id

    ctx = OrgContext(org_id=org_a.id, role=OrgRole.OWNER)
    activate_model_version(model_id=old_id, request=_FakeRequest(), current_user=owner, ctx=ctx, db=db)

    loaded = load_model(db, org_a.id)
    assert loaded["global"]["sample_count"] == 1

    audit_row = db.query(AuditLog).filter(AuditLog.event_type == "ml_model_activated").one()
    assert audit_row.target == f"ml_model_state:{old_id}"


def test_activate_rejects_corrupted_version(db, two_orgs):
    org_a, _ = two_orgs
    owner = db.query(User).filter(User.username == "owner_a").one()
    bad = MLModelState(org_id=org_a.id, sklearn_version="1.5.0", blob=b"not-a-valid-signed-blob", is_active=False, sample_count=0)
    db.add(bad)
    db.commit()
    db.refresh(bad)

    ctx = OrgContext(org_id=org_a.id, role=OrgRole.OWNER)
    with pytest.raises(HTTPException) as exc_info:
        activate_model_version(model_id=bad.id, request=_FakeRequest(), current_user=owner, ctx=ctx, db=db)
    assert exc_info.value.status_code == 422


def test_activate_returns_404_for_other_orgs_version(db, two_orgs):
    org_a, org_b = two_orgs
    owner_b = db.query(User).filter(User.username == "owner_b").one()
    save_model(db, org_a.id, _fake_model(1))
    other_org_model_id = db.query(MLModelState).one().id

    ctx_b = OrgContext(org_id=org_b.id, role=OrgRole.OWNER)
    with pytest.raises(HTTPException) as exc_info:
        activate_model_version(model_id=other_org_model_id, request=_FakeRequest(), current_user=owner_b, ctx=ctx_b, db=db)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# explain_anomaly
# ---------------------------------------------------------------------------

def test_explain_anomaly_ranks_by_zscore_descending():
    feature_stats = {
        "latency_ms": {"mean": 20.0, "std": 5.0},
        "query_entropy": {"mean": 1.0, "std": 0.5},
        "status_code": {"mean": 200.0, "std": 10.0},
    }
    features = {"latency_ms": 25.0, "query_entropy": 4.5, "status_code": 205.0}
    result = explain_anomaly(feature_stats, features, top_n=2)

    assert len(result) == 2
    assert result[0]["feature"] == "query_entropy"  # z = (4.5-1.0)/0.5 = 7.0, largest
    assert result[1]["feature"] == "latency_ms"  # z = (25-20)/5 = 1.0, second largest


def test_explain_anomaly_skips_zero_variance_features():
    feature_stats = {"status_code": {"mean": 200.0, "std": 0.0}}
    result = explain_anomaly(feature_stats, {"status_code": 200.0})
    assert result == []


# ---------------------------------------------------------------------------
# Per-endpoint baselining
# ---------------------------------------------------------------------------

def _seed_events(db, org_id: int, *, path: str, method: str, n: int, start_minutes_ago: int = 0) -> list[int]:
    base = datetime.now(UTC) - timedelta(hours=2) + timedelta(minutes=start_minutes_ago)
    ids = []
    for i in range(n):
        e = TrafficEvent(
            org_id=org_id,
            ts=base + timedelta(seconds=i),
            method=method,
            path=path,
            status_code=200,
            latency_ms=float(5 + i % 20),
            body_bytes=(i % 10) * 100,
            request_size_bytes=(i % 5) * 512,
            response_size_bytes=(i % 8) * 256,
            auth_present=(i % 2 == 0),
        )
        db.add(e)
        db.flush()
        ids.append(e.id)
    db.commit()
    return ids


def test_high_volume_endpoint_gets_its_own_baseline(db, two_orgs):
    org_a, _ = two_orgs
    _seed_events(db, org_a.id, path="/api/hot", method="GET", n=MIN_SAMPLES_ENDPOINT)
    _seed_events(db, org_a.id, path="/api/cold", method="GET", n=10)

    model = train_from_db(db, org_a.id)
    assert model is not None
    assert "GET /api/hot" in model["endpoints"]
    assert "GET /api/cold" not in model["endpoints"]  # too little volume, falls back to global

    hot_event = TrafficEvent(org_id=org_a.id, ts=datetime.now(UTC), method="GET", path="/api/hot", status_code=200, latency_ms=10.0)
    cold_event = TrafficEvent(org_id=org_a.id, ts=datetime.now(UTC), method="GET", path="/api/cold", status_code=200, latency_ms=10.0)

    _, hot_details = score_event(model, hot_event)
    _, cold_details = score_event(model, cold_event)
    assert hot_details["model_scope"] == "endpoint"
    assert cold_details["model_scope"] == "global"
    assert "explanation" in hot_details


# ---------------------------------------------------------------------------
# Feedback loop excludes confirmed true positives from training
# ---------------------------------------------------------------------------

def test_true_positive_feedback_excludes_event_from_training(db, two_orgs):
    org_a, _ = two_orgs
    # 51 seeded so that excluding 1 confirmed-attack event still clears
    # MIN_SAMPLES_GLOBAL (50) — otherwise train_from_db legitimately
    # returns None for "too little data", which would also make
    # sample_count == 49 look like exclusion when it's actually a no-model case.
    ids = _seed_events(db, org_a.id, path="/api/misc", method="GET", n=51)

    confirmed_attack = Alert(
        org_id=org_a.id,
        alert_type="traffic_anomaly",
        severity="medium",
        title="x",
        detail="x",
        event_id=ids[0],
        feedback="true_positive",
    )
    db.add(confirmed_attack)
    db.commit()

    model = train_from_db(db, org_a.id)
    assert model is not None
    assert model["global"]["sample_count"] == 50, "the confirmed-attack event must be excluded from the baseline"


def test_false_positive_feedback_does_not_exclude_event(db, two_orgs):
    org_a, _ = two_orgs
    ids = _seed_events(db, org_a.id, path="/api/misc", method="GET", n=50)
    db.add(Alert(
        org_id=org_a.id, alert_type="traffic_anomaly", severity="medium", title="x", detail="x",
        event_id=ids[0], feedback="false_positive",
    ))
    db.commit()

    model = train_from_db(db, org_a.id)
    assert model["global"]["sample_count"] == 50


# ---------------------------------------------------------------------------
# POST /alerts/{id}/feedback
# ---------------------------------------------------------------------------

def test_submit_alert_feedback_sets_label_and_audit_log(db, two_orgs):
    org_a, _ = two_orgs
    editor = db.query(User).filter(User.username == "owner_a").one()
    alert = Alert(org_id=org_a.id, alert_type="traffic_anomaly", severity="medium", title="x", detail="x")
    db.add(alert)
    db.commit()
    db.refresh(alert)

    ctx = OrgContext(org_id=org_a.id, role=OrgRole.EDITOR)
    result = submit_alert_feedback(
        alert_id=alert.id,
        body=AlertFeedbackIn(label="false_positive"),
        request=_FakeRequest(),
        current_user=editor,
        ctx=ctx,
        db=db,
    )
    assert result == {"id": alert.id, "feedback": "false_positive"}

    db.refresh(alert)
    assert alert.feedback == "false_positive"
    assert alert.feedback_at is not None

    audit_row = db.query(AuditLog).filter(AuditLog.event_type == "alert_feedback").one()
    assert audit_row.details == {"label": "false_positive"}


def test_submit_alert_feedback_404_for_other_org(db, two_orgs):
    org_a, org_b = two_orgs
    editor_b = db.query(User).filter(User.username == "owner_b").one()
    alert = Alert(org_id=org_a.id, alert_type="traffic_anomaly", severity="medium", title="x", detail="x")
    db.add(alert)
    db.commit()
    db.refresh(alert)

    ctx_b = OrgContext(org_id=org_b.id, role=OrgRole.EDITOR)
    with pytest.raises(HTTPException) as exc_info:
        submit_alert_feedback(
            alert_id=alert.id,
            body=AlertFeedbackIn(label="true_positive"),
            request=_FakeRequest(),
            current_user=editor_b,
            ctx=ctx_b,
            db=db,
        )
    assert exc_info.value.status_code == 404
