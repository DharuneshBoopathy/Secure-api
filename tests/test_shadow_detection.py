from app.services.discovery_service import _shadow_risk
from app.services.pathutil import normalize_path_for_discovery


def test_shadow_path_normalization_uuid_and_int() -> None:
    assert normalize_path_for_discovery("/users/123/profile") == "/users/{id}/profile"
    assert (
        normalize_path_for_discovery("/sessions/550e8400-e29b-41d4-a716-446655440000/events")
        == "/sessions/{uuid}/events"
    )


def test_shadow_risk_scoring() -> None:
    score, level = _shadow_risk("POST", 20, False)
    assert score >= 90
    assert level == "CRITICAL"
    score2, level2 = _shadow_risk("GET", 1, False)
    assert score2 < 40
    assert level2 == "LOW"
