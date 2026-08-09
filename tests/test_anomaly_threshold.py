"""
Validates Task 4: Configurable anomaly threshold via ANOMALY_THRESHOLD env var.

Confirms that:
  1. The default threshold in Settings is 0.8.
  2. is_anomaly() returns True when score >= threshold and False when below.
  3. Setting ANOMALY_THRESHOLD=1.0 causes all scores < 1.0 to return False
     (high threshold suppresses all but the most extreme anomalies).
  4. Setting ANOMALY_THRESHOLD=0.0 causes any non-None score to return True
     (low threshold flags everything).
  5. is_anomaly() with a None score always returns False regardless of threshold.
  6. The threshold is read from get_settings() at call time, so changes via
     monkeypatch / env override are honoured without restarting.
"""

from unittest.mock import patch

from app.services.ml_anomaly import is_anomaly


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_threshold(threshold: float):
    """Context manager: patch get_settings to return a Settings-like object
    with the given anomaly_threshold without touching the real .env or cache."""
    from unittest.mock import MagicMock
    mock_settings = MagicMock()
    mock_settings.anomaly_threshold = threshold
    return patch("app.services.ml_anomaly.get_settings", return_value=mock_settings)


# ---------------------------------------------------------------------------
# Default threshold (0.8)
# ---------------------------------------------------------------------------

def test_default_threshold_is_0_8():
    from app.config import Settings
    s = Settings.model_fields["anomaly_threshold"]
    assert s.default == 0.8


def test_score_above_default_threshold_is_anomaly():
    with _with_threshold(0.8):
        assert is_anomaly(model={}, score=0.85) is True


def test_score_equal_to_default_threshold_is_anomaly():
    with _with_threshold(0.8):
        assert is_anomaly(model={}, score=0.8) is True


def test_score_below_default_threshold_is_not_anomaly():
    with _with_threshold(0.8):
        assert is_anomaly(model={}, score=0.79) is False


# ---------------------------------------------------------------------------
# High threshold (1.0) — operator tunes down false-positive rate
# ---------------------------------------------------------------------------

def test_threshold_1_0_suppresses_score_0_99():
    """With threshold=1.0, score=0.99 must NOT be flagged as anomalous."""
    with _with_threshold(1.0):
        assert is_anomaly(model={}, score=0.99) is False


def test_threshold_1_0_suppresses_score_0_8():
    """A score that would fire at default 0.8 is ignored when threshold=1.0."""
    with _with_threshold(1.0):
        assert is_anomaly(model={}, score=0.8) is False


def test_threshold_1_0_fires_only_at_exactly_1_0():
    with _with_threshold(1.0):
        assert is_anomaly(model={}, score=1.0) is True


# ---------------------------------------------------------------------------
# Low threshold (0.0) — operator maximises sensitivity
# ---------------------------------------------------------------------------

def test_threshold_0_flags_any_nonzero_score():
    with _with_threshold(0.0):
        assert is_anomaly(model={}, score=0.01) is True


def test_threshold_0_flags_score_0():
    with _with_threshold(0.0):
        assert is_anomaly(model={}, score=0.0) is True


# ---------------------------------------------------------------------------
# None score always returns False
# ---------------------------------------------------------------------------

def test_none_score_returns_false_at_default_threshold():
    with _with_threshold(0.8):
        assert is_anomaly(model={}, score=None) is False


def test_none_score_returns_false_at_zero_threshold():
    with _with_threshold(0.0):
        assert is_anomaly(model={}, score=None) is False


def test_none_score_returns_false_at_high_threshold():
    with _with_threshold(1.0):
        assert is_anomaly(model={}, score=None) is False


# ---------------------------------------------------------------------------
# Environment variable override
# ---------------------------------------------------------------------------

def test_anomaly_threshold_read_from_env(monkeypatch):
    """ANOMALY_THRESHOLD env var overrides the default when Settings is constructed."""
    from app.config import Settings
    monkeypatch.setenv("ANOMALY_THRESHOLD", "0.5")
    s = Settings()
    assert s.anomaly_threshold == 0.5


def test_anomaly_threshold_env_1_0_suppresses_score_0_9(monkeypatch):
    """End-to-end: ANOMALY_THRESHOLD=1.0 → score 0.9 is not flagged."""
    from app.config import Settings
    monkeypatch.setenv("ANOMALY_THRESHOLD", "1.0")
    # Bypass lru_cache so the monkeypatched env is picked up.
    with patch("app.services.ml_anomaly.get_settings", return_value=Settings()):
        result = is_anomaly(model={}, score=0.9)
    assert result is False


def test_anomaly_threshold_env_0_2_flags_score_0_3(monkeypatch):
    """End-to-end: ANOMALY_THRESHOLD=0.2 → score 0.3 is flagged."""
    from app.config import Settings
    monkeypatch.setenv("ANOMALY_THRESHOLD", "0.2")
    with patch("app.services.ml_anomaly.get_settings", return_value=Settings()):
        result = is_anomaly(model={}, score=0.3)
    assert result is True
