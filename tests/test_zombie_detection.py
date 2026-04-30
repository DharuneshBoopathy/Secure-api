from app.services.discovery_service import _zombie_risk


def test_zombie_risk_levels() -> None:
    assert _zombie_risk("DEAD", "POST") == "CRITICAL"
    assert _zombie_risk("DEAD", "GET") == "HIGH"
    assert _zombie_risk("ZOMBIE", "GET") == "HIGH"
    assert _zombie_risk("IDLE", "GET") == "MEDIUM"
    assert _zombie_risk("DECLINING", "GET") == "LOW"
