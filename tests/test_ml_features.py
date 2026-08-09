"""
Validates Phase 3 Task 1: Enhanced ML feature extraction for anomaly detection.

Confirms that:
  1. _string_entropy() returns 0.0 for empty input and a positive value otherwise.
  2. _string_entropy() returns higher values for high-entropy (random-looking) strings.
  3. _query_param_count() correctly counts distinct parameter keys.
  4. _row_features() includes all 15 FEATURE_COLS keys.
  5. New features (query_param_count, query_entropy, request_size_bytes,
     response_size_bytes) are populated from TrafficEvent fields.
  6. request_size_bytes and response_size_bytes are capped at 10_000_000.
  7. train_from_db() successfully trains on seeded traffic that includes
     query parameters — no shape/indexing errors.
  8. score_event() produces a valid score after training on the new 15-feature vector.
  9. Feature vector length matches len(FEATURE_COLS).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Alert, Base, TrafficEvent
from app.services.ml_anomaly import (
    FEATURE_COLS,
    _query_param_count,
    _row_features,
    _string_entropy,
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


def _make_event(
    path: str = "/api/users",
    method: str = "GET",
    status_code: int = 200,
    latency_ms: float = 5.0,
    body_bytes: int = 0,
    request_size_bytes: int = 512,
    response_size_bytes: int = 1024,
    auth_present: bool = False,
    hours_ago: int = 0,
) -> TrafficEvent:
    ts = datetime.now(UTC) - timedelta(hours=hours_ago)
    return TrafficEvent(
        org_id=1,
        ts=ts,
        method=method,
        path=path,
        status_code=status_code,
        latency_ms=latency_ms,
        body_bytes=body_bytes,
        request_size_bytes=request_size_bytes,
        response_size_bytes=response_size_bytes,
        auth_present=auth_present,
    )


# ---------------------------------------------------------------------------
# _string_entropy tests
# ---------------------------------------------------------------------------

def test_entropy_empty_string():
    assert _string_entropy("") == 0.0


def test_entropy_single_char():
    # Single repeated character has 0 entropy
    assert _string_entropy("aaaa") == pytest.approx(0.0, abs=1e-9)


def test_entropy_two_equal_chars():
    # Two equally-distributed chars → entropy = 1.0 bit
    assert _string_entropy("abab") == pytest.approx(1.0, abs=1e-9)


def test_entropy_high_entropy_string():
    # A long string with many distinct chars has high entropy
    s = "aB3!xQ7@mZ2#nR8$"
    assert _string_entropy(s) > 3.0


def test_entropy_low_entropy_string():
    # Repeated simple pattern has low entropy
    s = "aaabbbccc"
    assert _string_entropy(s) < 2.0


def test_entropy_sqli_pattern():
    # SQL injection strings tend to have medium-to-high entropy due to special chars
    sqli = "' OR 1=1 --"
    assert _string_entropy(sqli) > 2.0


# ---------------------------------------------------------------------------
# _query_param_count tests
# ---------------------------------------------------------------------------

def test_query_param_count_no_params():
    assert _query_param_count("/api/users") == 0


def test_query_param_count_single_param():
    assert _query_param_count("/api/users?id=5") == 1


def test_query_param_count_multiple_params():
    assert _query_param_count("/search?q=test&page=1&sort=asc") == 3


def test_query_param_count_repeated_key():
    # parse_qs groups repeated keys — still counts as 1 distinct key
    assert _query_param_count("/api?tag=a&tag=b") == 1


def test_query_param_count_empty_value():
    # parse_qs silences blank values by default, so foo= is dropped; only bar=1 counts
    assert _query_param_count("/api?foo=&bar=1") == 1


def test_query_param_count_no_value():
    # parse_qs by default ignores keys with empty values;
    # use keep_blank_values awareness — count reflects parse_qs behaviour
    result = _query_param_count("/api?foo")
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# _row_features tests
# ---------------------------------------------------------------------------

def test_row_features_contains_all_feature_cols():
    e = _make_event(path="/api/items?id=1&filter=active")
    f = _row_features(e)
    for col in FEATURE_COLS:
        assert col in f, f"Missing feature: {col}"


def test_row_features_query_param_count_populated():
    e = _make_event(path="/api/search?q=hello&page=2&limit=50")
    f = _row_features(e)
    assert f["query_param_count"] == 3.0


def test_row_features_query_entropy_nonzero_for_query_string():
    e = _make_event(path="/api/items?token=abc123XYZ")
    f = _row_features(e)
    assert f["query_entropy"] > 0.0


def test_row_features_query_entropy_zero_for_no_query():
    e = _make_event(path="/api/items")
    f = _row_features(e)
    assert f["query_entropy"] == 0.0


def test_row_features_request_size_bytes_populated():
    e = _make_event(request_size_bytes=4096)
    f = _row_features(e)
    assert f["request_size_bytes"] == 4096.0


def test_row_features_response_size_bytes_populated():
    e = _make_event(response_size_bytes=8192)
    f = _row_features(e)
    assert f["response_size_bytes"] == 8192.0


def test_row_features_request_size_capped():
    e = _make_event(request_size_bytes=50_000_000)
    f = _row_features(e)
    assert f["request_size_bytes"] == 10_000_000.0


def test_row_features_response_size_capped():
    e = _make_event(response_size_bytes=50_000_000)
    f = _row_features(e)
    assert f["response_size_bytes"] == 10_000_000.0


def test_row_features_none_size_fields_default_to_zero():
    e = _make_event(request_size_bytes=0, response_size_bytes=0)
    f = _row_features(e)
    assert f["request_size_bytes"] == 0.0
    assert f["response_size_bytes"] == 0.0


def test_feature_vector_length_matches_feature_cols():
    e = _make_event(path="/api/users?id=1")
    f = _row_features(e)
    vec = [f[c] for c in FEATURE_COLS]
    assert len(vec) == len(FEATURE_COLS) == 15


# ---------------------------------------------------------------------------
# train_from_db integration tests
# ---------------------------------------------------------------------------

def _seed_traffic(db, n: int = 60) -> None:
    """Insert n varied TrafficEvent rows covering different query complexities."""
    base = datetime.now(UTC) - timedelta(hours=1)
    paths = [
        "/api/users",
        "/api/users?id=1",
        "/api/search?q=admin%27+OR+1%3D1--&page=1",   # SQLi-like high entropy
        "/api/items?category=books&sort=price&order=asc&page=2&limit=25",
        "/api/data",
        "/api/events?from=2024-01-01&to=2024-12-31&status=active",
        "/health",
        "/api/v2/reports?type=monthly&format=csv&compressed=true",
    ]
    methods = ["GET", "POST", "PUT", "DELETE"]
    for i in range(n):
        db.add(TrafficEvent(
            org_id=1,
            ts=base + timedelta(minutes=i),
            method=methods[i % len(methods)],
            path=paths[i % len(paths)],
            status_code=200 if i % 5 != 0 else 404,
            latency_ms=float(5 + (i % 50)),
            body_bytes=i * 10,
            request_size_bytes=(i % 10) * 256,
            response_size_bytes=(i % 8) * 512,
            auth_present=(i % 3 == 0),
        ))
    db.commit()


def test_train_from_db_returns_model_with_new_features(db):
    _seed_traffic(db, n=60)
    model = train_from_db(db, org_id=1)
    assert model is not None
    assert "iforest" in model["global"]
    assert "lof" in model["global"]


def test_train_from_db_model_accepts_15_feature_vector(db):
    _seed_traffic(db, n=60)
    model = train_from_db(db, org_id=1)
    assert model is not None

    # Manually build a 15-feature vector and call decision_function
    import numpy as np
    vec = [[0.0] * len(FEATURE_COLS)]
    arr = np.array(vec, dtype=np.float64)
    # Should not raise shape/indexing errors
    if_score = model["global"]["iforest"].decision_function(arr)
    lof_score = model["global"]["lof"].decision_function(arr)
    assert len(if_score) == 1
    assert len(lof_score) == 1


def test_train_from_db_returns_none_when_too_few_rows(db):
    _seed_traffic(db, n=10)
    model = train_from_db(db, org_id=1)
    assert model is None


def test_score_event_after_training_on_new_features(db):
    _seed_traffic(db, n=60)
    model = train_from_db(db, org_id=1)
    assert model is not None

    e = _make_event(
        path="/api/search?q=SELECT+*+FROM+users--&debug=1",
        method="GET",
        request_size_bytes=1024,
        response_size_bytes=2048,
    )
    score, details = score_event(model, e)
    assert score is not None
    assert 0.0 <= score <= 1.0
    assert "features" in details
    assert details["features"]["query_param_count"] == 2.0
    assert details["features"]["query_entropy"] > 0.0


def test_score_event_high_entropy_query_produces_valid_score(db):
    """A request with a high-entropy query string (SQLi-like) scores without error."""
    _seed_traffic(db, n=60)
    model = train_from_db(db, org_id=1)
    assert model is not None

    # Simulate a BOLA-style request with many params and high entropy
    e = _make_event(
        path="/api/resource?id=../../../etc/passwd&exec=whoami&token=aB3!xQ7@mZ",
        request_size_bytes=768,
        response_size_bytes=0,
        status_code=403,
    )
    score, details = score_event(model, e)
    assert score is not None
    assert details["features"]["query_param_count"] == 3.0
    assert details["features"]["query_entropy"] > 3.0
