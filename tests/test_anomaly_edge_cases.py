"""
Edge-case tests for ML anomaly detection (beyond test_anomaly_scoring.py and test_ml_features.py).

Covers:
  1. score_event with a trained model returns a float score in [0.0, 1.0].
  2. score_event with None path falls back to "" without crashing.
  3. score_event with None method falls back to "GET" without crashing.
  4. score_event with extreme latency (e.g. 1e9 ms) does not crash.
  5. score_event with body_bytes above the 1M cap: feature is capped, no crash.
  6. score_event with request/response sizes above the 10M cap: capped, no crash.
  7. score_event with a corrupt model dict (missing keys) returns (None, {}).
  8. score_event with an empty model dict returns (None, {}).
  9. train_from_db with 49 rows returns None (below minimum threshold).
  10. train_from_db with exactly 50 rows returns a trained model dict.
  11. features dict in score_event details contains all 15 FEATURE_COLS keys.
  12. is_anomaly with score exactly at threshold returns True (boundary inclusive).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from app.models import Alert, Base, TrafficEvent
from app.services.ml_anomaly import (
    FEATURE_COLS,
    _row_features,
    is_anomaly,
    score_event,
    train_from_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[TrafficEvent.__table__, Alert.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _event(**overrides) -> TrafficEvent:
    defaults = dict(
        org_id=1,
        ts=datetime.now(UTC),
        method="GET",
        path="/api/items",
        status_code=200,
        latency_ms=10.0,
        body_bytes=512,
        request_size_bytes=256,
        response_size_bytes=1024,
        auth_present=False,
    )
    defaults.update(overrides)
    return TrafficEvent(**defaults)


def _seed(db, n: int) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(n):
        db.add(TrafficEvent(
            org_id=1,
            ts=base + timedelta(seconds=i),
            method=["GET", "POST", "PUT"][i % 3],
            path=["/api/users", "/api/items?id=1", "/health"][i % 3],
            status_code=[200, 201, 404][i % 3],
            latency_ms=float(5 + i % 20),
            body_bytes=(i % 10) * 100,
            request_size_bytes=(i % 5) * 512,
            response_size_bytes=(i % 8) * 256,
            auth_present=(i % 2 == 0),
        ))
    db.commit()


@pytest.fixture()
def trained_model(db):
    _seed(db, 60)
    return train_from_db(db, org_id=1)


# ---------------------------------------------------------------------------
# score_event with a trained model
# ---------------------------------------------------------------------------

def test_score_event_with_trained_model_returns_float_in_range(trained_model):
    e = _event()
    score, details = score_event(trained_model, e)
    assert score is not None
    assert 0.0 <= score <= 1.0


def test_score_event_details_contain_iforest_and_lof_scores(trained_model):
    e = _event()
    _, details = score_event(trained_model, e)
    assert "iforest_score" in details
    assert "lof_score" in details
    assert "combined_score" in details


def test_score_event_features_dict_contains_all_feature_cols(trained_model):
    e = _event()
    _, details = score_event(trained_model, e)
    for col in FEATURE_COLS:
        assert col in details["features"], f"Missing feature key: {col}"


# ---------------------------------------------------------------------------
# Degenerate inputs — must not crash
# ---------------------------------------------------------------------------

def test_score_event_none_path_does_not_crash(trained_model):
    e = _event(path=None)
    score, _ = score_event(trained_model, e)
    assert score is not None


def test_score_event_none_method_does_not_crash(trained_model):
    e = _event(method=None)
    score, _ = score_event(trained_model, e)
    assert score is not None


def test_score_event_extreme_latency_does_not_crash(trained_model):
    e = _event(latency_ms=1_000_000.0)
    score, _ = score_event(trained_model, e)
    assert score is not None


def test_score_event_zero_latency_does_not_crash(trained_model):
    e = _event(latency_ms=0.0)
    score, _ = score_event(trained_model, e)
    assert score is not None


def test_score_event_empty_path_does_not_crash(trained_model):
    e = _event(path="")
    score, _ = score_event(trained_model, e)
    assert score is not None


def test_score_event_path_with_only_query_string(trained_model):
    e = _event(path="?foo=bar&baz=1")
    score, _ = score_event(trained_model, e)
    assert score is not None


# ---------------------------------------------------------------------------
# Feature capping
# ---------------------------------------------------------------------------

def test_body_bytes_capped_at_1m():
    e = _event(body_bytes=5_000_000)
    f = _row_features(e)
    assert f["body_bytes"] == 1_000_000.0


def test_request_size_bytes_capped_at_10m():
    e = _event(request_size_bytes=50_000_000)
    f = _row_features(e)
    assert f["request_size_bytes"] == 10_000_000.0


def test_response_size_bytes_capped_at_10m():
    e = _event(response_size_bytes=50_000_000)
    f = _row_features(e)
    assert f["response_size_bytes"] == 10_000_000.0


def test_body_bytes_exactly_at_cap_is_not_truncated():
    e = _event(body_bytes=1_000_000)
    f = _row_features(e)
    assert f["body_bytes"] == 1_000_000.0


# ---------------------------------------------------------------------------
# Corrupt / empty model
# ---------------------------------------------------------------------------

def test_score_event_with_empty_model_dict_returns_none():
    e = _event()
    score, details = score_event({}, e)
    assert score is None
    assert details == {}


def test_score_event_with_missing_lof_key_returns_none():
    e = _event()
    from unittest.mock import MagicMock
    broken_model = {"iforest": MagicMock()}  # no "lof" key
    score, details = score_event(broken_model, e)
    assert score is None
    assert details == {}


def test_score_event_with_none_model_returns_none():
    e = _event()
    score, details = score_event(None, e)
    assert score is None
    assert details == {}


# ---------------------------------------------------------------------------
# train_from_db boundary: 49 vs 50 rows
# ---------------------------------------------------------------------------

def test_train_from_db_with_49_rows_returns_none(db):
    _seed(db, 49)
    model = train_from_db(db, org_id=1)
    assert model is None, "Should return None when fewer than 50 rows are available"


def test_train_from_db_with_50_rows_returns_model(db):
    _seed(db, 50)
    model = train_from_db(db, org_id=1)
    assert model is not None, "Should return a trained model when exactly 50 rows are available"
    assert "iforest" in model["global"]
    assert "lof" in model["global"]


def test_train_from_db_with_empty_table_returns_none(db):
    model = train_from_db(db, org_id=1)
    assert model is None


# ---------------------------------------------------------------------------
# is_anomaly boundary conditions
# ---------------------------------------------------------------------------

def test_is_anomaly_score_exactly_at_threshold_is_true():
    with patch("app.services.ml_anomaly.get_settings") as mock:
        mock.return_value.anomaly_threshold = 0.8
        assert is_anomaly(model={}, score=0.8) is True


def test_is_anomaly_score_just_below_threshold_is_false():
    with patch("app.services.ml_anomaly.get_settings") as mock:
        mock.return_value.anomaly_threshold = 0.8
        assert is_anomaly(model={}, score=0.7999) is False


def test_is_anomaly_score_just_above_threshold_is_true():
    with patch("app.services.ml_anomaly.get_settings") as mock:
        mock.return_value.anomaly_threshold = 0.8
        assert is_anomaly(model={}, score=0.8001) is True
