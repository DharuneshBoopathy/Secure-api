from datetime import UTC, datetime

from app.models import TrafficEvent
from app.services.ml_anomaly import score_event


def test_score_event_without_model() -> None:
    e = TrafficEvent(
        ts=datetime.now(UTC),
        method="GET",
        path="/health",
        status_code=200,
        latency_ms=5.0,
        response_time_ms=5.0,
        body_bytes=10,
        request_size_bytes=10,
        response_size_bytes=10,
        auth_present=False,
    )
    score, features = score_event(None, e, is_new_path=False)
    assert score is None
    assert features == {}
