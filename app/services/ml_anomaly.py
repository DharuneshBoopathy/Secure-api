import hashlib
import hmac
import io
import logging
import math
import pickle  # nosec B403
from datetime import timedelta
from urllib.parse import parse_qs

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn import __version__ as skl_version
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MLModelState, TrafficEvent
from app.security import utc_now

# The stored blob format is:
#     magic(5) + hmac_sha256_digest(32) + pickle_payload
# The HMAC is computed over the pickle payload using SECRET_KEY.  Any blob that
# fails the HMAC check is treated as tampered / corrupt and refused.  This
# closes the arbitrary-code-execution surface around ``pickle.loads`` even if an
# attacker gains write access to the ``ml_model_state`` table.
_BLOB_MAGIC = b"APMV1"
_HMAC_LEN = 32


def _model_hmac_key() -> bytes:
    return get_settings().secret_key.encode("utf-8")


def _sign_blob(payload: bytes) -> bytes:
    digest = hmac.new(_model_hmac_key(), payload, hashlib.sha256).digest()
    return _BLOB_MAGIC + digest + payload


def _verify_blob(blob: bytes) -> bytes | None:
    """Return the raw pickle payload if the signature is valid, else None."""
    header_len = len(_BLOB_MAGIC) + _HMAC_LEN
    if not blob or len(blob) <= header_len:
        return None
    if blob[: len(_BLOB_MAGIC)] != _BLOB_MAGIC:
        return None
    expected = blob[len(_BLOB_MAGIC) : header_len]
    payload = blob[header_len:]
    computed = hmac.new(_model_hmac_key(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, computed):
        return None
    return payload


FEATURE_COLS = [
    "hour",
    "dow",
    "status_code",
    "latency_ms",
    "body_bytes",
    "auth_int",
    "path_depth",
    "method_get",
    "method_post",
    "method_other",
    "is_new_path",
    "query_param_count",
    "query_entropy",
    "request_size_bytes",
    "response_size_bytes",
]


def _string_entropy(s: str) -> float:
    """Shannon entropy (bits) of a string. Returns 0.0 for empty input."""
    if not s:
        return 0.0
    n = len(s)
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    return -sum((cnt / n) * math.log2(cnt / n) for cnt in freq.values())


def _query_param_count(path: str) -> int:
    """Count of distinct query parameter keys in a path string."""
    qs = path.split("?", 1)[1] if "?" in path else ""
    return len(parse_qs(qs)) if qs else 0


def _row_features(e: TrafficEvent, *, is_new_path: bool = False) -> dict:
    ts = e.ts
    raw_path = e.path or ""
    p = raw_path.split("?", 1)[0].strip("/")
    depth = len([x for x in p.split("/") if x]) if p else 0
    m = (e.method or "GET").upper()
    qs = raw_path.split("?", 1)[1] if "?" in raw_path else ""
    return {
        "hour": ts.hour + ts.minute / 60.0,
        "dow": float(ts.weekday()),
        "status_code": float(e.status_code),
        "latency_ms": float(e.latency_ms or 0),
        "body_bytes": float(min(e.body_bytes or 0, 1_000_000)),
        "auth_int": 1.0 if e.auth_present else 0.0,
        "path_depth": float(depth),
        "method_get": 1.0 if m == "GET" else 0.0,
        "method_post": 1.0 if m == "POST" else 0.0,
        "method_other": 1.0 if m not in {"GET", "POST"} else 0.0,
        "is_new_path": 1.0 if is_new_path else 0.0,
        "query_param_count": float(_query_param_count(raw_path)),
        "query_entropy": _string_entropy(qs),
        "request_size_bytes": float(min(e.request_size_bytes or 0, 10_000_000)),
        "response_size_bytes": float(min(e.response_size_bytes or 0, 10_000_000)),
    }


def train_from_db(db: Session, lookback_hours: int = 168) -> dict | None:
    since = utc_now() - timedelta(hours=lookback_hours)
    rows = db.query(TrafficEvent).filter(TrafficEvent.ts >= since).limit(50_000).all()
    if len(rows) < 50:
        return None
    df = pd.DataFrame([_row_features(r) for r in rows])
    X = df[FEATURE_COLS].values.astype(np.float64)
    if_model = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
        n_jobs=1,
    )
    if_model.fit(X)
    lof_model = LocalOutlierFactor(n_neighbors=35, contamination=0.05, novelty=True)
    lof_model.fit(X)
    return {"iforest": if_model, "lof": lof_model}


def save_model(db: Session, model: dict) -> None:
    buf = io.BytesIO()
    pickle.dump(model, buf)
    blob = _sign_blob(buf.getvalue())
    row = db.query(MLModelState).order_by(MLModelState.id.desc()).first()
    if row:
        row.blob = blob
        row.sklearn_version = skl_version
        row.updated_at = utc_now()
    else:
        db.add(MLModelState(sklearn_version=skl_version, blob=blob))
    db.commit()


log = logging.getLogger(__name__)


def load_model(db: Session) -> dict | None:
    """Load the latest ML model from DB, verified by HMAC-SHA256.

    Defence in depth around ``pickle.loads``:

    1. The blob is prefixed with a magic marker and an HMAC-SHA256 digest
       computed with ``SECRET_KEY``.  A blob missing the marker, truncated,
       or signed with a different key is refused outright — the pickle
       payload is never passed to ``pickle.loads``.
    2. Models trained with a different major sklearn version are refused
       to avoid unpickling objects whose layout has changed.
    3. Any unexpected exception is swallowed and the model is re-trained
       on the next scheduler tick.
    """
    row = db.query(MLModelState).order_by(MLModelState.id.desc()).first()
    if not row or not row.blob:
        return None

    payload = _verify_blob(row.blob)
    if payload is None:
        log.warning(
            "Refusing to load ML model blob: missing/invalid HMAC signature. "
            "Retrain will regenerate a fresh signed model."
        )
        return None

    if row.sklearn_version:
        stored_major = row.sklearn_version.split(".")[0]
        current_major = skl_version.split(".")[0]
        if stored_major != current_major:
            log.warning(
                "Refusing to load ML model trained with sklearn %s "
                "(current: %s) — major version mismatch. Retrain will fix this.",
                row.sklearn_version,
                skl_version,
            )
            return None
    try:
        return pickle.loads(payload)  # nosec B301  # noqa: S301 — payload is HMAC-verified
    except Exception:
        log.warning("Failed to unpickle ML model blob; will retrain.")
        return None


def score_event(model: dict | None, e: TrafficEvent, *, is_new_path: bool = False) -> tuple[float | None, dict]:
    if model is None:
        return None, {}
    f = _row_features(e, is_new_path=is_new_path)
    vec = np.array([[f[c] for c in FEATURE_COLS]], dtype=np.float64)
    try:
        if_score = float(model["iforest"].decision_function(vec)[0])
        lof_score = float(model["lof"].decision_function(vec)[0])
        combined = float((if_score + lof_score) / 2.0)
        min_s = -0.5
        max_s = 0.5
        normalized = 1.0 - min(1.0, max(0.0, (combined - min_s) / (max_s - min_s)))
        return normalized, {
            "iforest_score": if_score,
            "lof_score": lof_score,
            "combined_score": combined,
            "features": f,
        }
    except Exception:
        return None, {}


def is_anomaly(model: dict | None, score: float | None) -> bool:
    if score is None:
        return False
    return score >= get_settings().anomaly_threshold
