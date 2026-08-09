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
from app.models import Alert, MLModelState, TrafficEvent
from app.security import utc_now
from app.services.pathutil import normalize_path_for_discovery

# Below this many events in the lookback window, an org doesn't get a model
# at all (too little signal to fit IsolationForest/LOF meaningfully).
MIN_SAMPLES_GLOBAL = 50
# Below this many events for a specific (method, path template), that
# endpoint falls back to the org's global model instead of getting its own
# baseline — a GET /health and a POST /payments/transfer have very different
# "normal" traffic shapes, but an endpoint with 10 hits/week doesn't have
# enough data to learn its own shape yet.
MIN_SAMPLES_ENDPOINT = 200
# Versions kept per org so a bad retrain can be rolled back (see save_model /
# app/routers/ml_models.py). Bounded so ml_model_state doesn't grow forever.
MAX_MODEL_VERSIONS = 5

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


log = logging.getLogger(__name__)


def _endpoint_key(method: str | None, path: str | None) -> str:
    return f"{(method or 'GET').upper()} {normalize_path_for_discovery(path or '')}"


def _train_submodel(df: pd.DataFrame) -> dict:
    """Fit one IsolationForest+LOF pair (plus per-feature mean/std, used for
    explainability) on the given rows. Shared by the global model and each
    per-endpoint baseline."""
    X = df[FEATURE_COLS].values.astype(np.float64)
    if_model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42, n_jobs=1)
    if_model.fit(X)
    # n_neighbors must be < n_samples; the MIN_SAMPLES_* thresholds already
    # guarantee this in practice, but guard anyway rather than let LOF crash
    # if those thresholds are ever lowered.
    n_neighbors = min(35, max(1, len(df) - 1))
    lof_model = LocalOutlierFactor(n_neighbors=n_neighbors, contamination=0.05, novelty=True)
    lof_model.fit(X)
    feature_stats = {c: {"mean": float(df[c].mean()), "std": float(df[c].std(ddof=0))} for c in FEATURE_COLS}
    return {"iforest": if_model, "lof": lof_model, "feature_stats": feature_stats, "sample_count": len(df)}


def train_from_db(db: Session, org_id: int, lookback_hours: int = 168) -> dict | None:
    """Train one org's model: a global baseline over all its traffic, plus a
    per-(method, path template) baseline for any endpoint with enough volume
    (falls back to the global model for low-volume endpoints at scoring
    time — see score_event).

    Events tied to an alert a human confirmed as a real finding
    (Alert.feedback == "true_positive") are excluded from the training set:
    otherwise a confirmed attack would get folded into "normal" behavior on
    the very next retrain.
    """
    since = utc_now() - timedelta(hours=lookback_hours)
    rows = (
        db.query(TrafficEvent)
        .filter(TrafficEvent.org_id == org_id, TrafficEvent.ts >= since)
        .limit(50_000)
        .all()
    )
    confirmed_anomaly_event_ids = {
        r.event_id
        for r in db.query(Alert.event_id)
        .filter(Alert.org_id == org_id, Alert.event_id.isnot(None), Alert.feedback == "true_positive")
        .all()
    }
    if confirmed_anomaly_event_ids:
        rows = [r for r in rows if r.id not in confirmed_anomaly_event_ids]
    if len(rows) < MIN_SAMPLES_GLOBAL:
        return None

    df = pd.DataFrame([_row_features(r) for r in rows])
    df["_endpoint_key"] = [_endpoint_key(r.method, r.path) for r in rows]

    global_model = _train_submodel(df)
    endpoints: dict[str, dict] = {}
    for key, group in df.groupby("_endpoint_key"):
        if len(group) >= MIN_SAMPLES_ENDPOINT:
            endpoints[key] = _train_submodel(group)
    return {"global": global_model, "endpoints": endpoints}


def save_model(db: Session, org_id: int, model: dict) -> None:
    """Insert a new active model version for this org, deactivating the
    previous one and pruning anything beyond MAX_MODEL_VERSIONS so history
    doesn't grow unbounded. Older (now-inactive) versions are kept, not
    deleted, so an admin can roll back via app/routers/ml_models.py."""
    buf = io.BytesIO()
    pickle.dump(model, buf)
    blob = _sign_blob(buf.getvalue())
    sample_count = model.get("global", {}).get("sample_count", 0)

    db.query(MLModelState).filter(MLModelState.org_id == org_id).update({"is_active": False})
    db.add(
        MLModelState(
            org_id=org_id,
            sklearn_version=skl_version,
            blob=blob,
            is_active=True,
            sample_count=sample_count,
        )
    )
    db.flush()
    _prune_old_versions(db, org_id)
    db.commit()


def _prune_old_versions(db: Session, org_id: int, keep: int = MAX_MODEL_VERSIONS) -> None:
    ids = [
        row.id
        for row in db.query(MLModelState.id)
        .filter(MLModelState.org_id == org_id)
        .order_by(MLModelState.id.desc())
        .all()
    ]
    stale = ids[keep:]
    if stale:
        db.query(MLModelState).filter(MLModelState.id.in_(stale)).delete(synchronize_session=False)


def decode_model_row(row: MLModelState) -> dict | None:
    """Verify + unpickle one MLModelState row. See load_model for the
    defence-in-depth rationale (HMAC signature, sklearn version pin)."""
    payload = _verify_blob(row.blob)
    if payload is None:
        log.warning(
            "Refusing to load ML model blob (org_id=%s): missing/invalid HMAC signature. "
            "Retrain will regenerate a fresh signed model.",
            row.org_id,
        )
        return None
    if row.sklearn_version:
        stored_major = row.sklearn_version.split(".")[0]
        current_major = skl_version.split(".")[0]
        if stored_major != current_major:
            log.warning(
                "Refusing to load ML model trained with sklearn %s (current: %s) "
                "— major version mismatch. Retrain will fix this.",
                row.sklearn_version,
                skl_version,
            )
            return None
    try:
        return pickle.loads(payload)  # nosec B301  # noqa: S301 — payload is HMAC-verified
    except Exception:
        log.warning("Failed to unpickle ML model blob (org_id=%s); will retrain.", row.org_id)
        return None


def load_model(db: Session, org_id: int) -> dict | None:
    """Load this org's currently-active model, verified by HMAC-SHA256.

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
    row = (
        db.query(MLModelState)
        .filter(MLModelState.org_id == org_id, MLModelState.is_active.is_(True))
        .order_by(MLModelState.id.desc())
        .first()
    )
    if not row or not row.blob:
        return None
    return decode_model_row(row)


def explain_anomaly(feature_stats: dict, features: dict, top_n: int = 3) -> list[dict]:
    """Rank features by how many standard deviations they sit from this
    model's training-set baseline, so an alert can say *why* it fired
    instead of just showing a bare score."""
    contributions = []
    for col in FEATURE_COLS:
        stats = feature_stats.get(col)
        if not stats or stats["std"] <= 1e-9:
            continue
        z = (features[col] - stats["mean"]) / stats["std"]
        contributions.append(
            {
                "feature": col,
                "value": features[col],
                "baseline_mean": round(stats["mean"], 4),
                "z_score": round(z, 3),
            }
        )
    contributions.sort(key=lambda c: abs(c["z_score"]), reverse=True)
    return contributions[:top_n]


def score_event(model: dict | None, e: TrafficEvent, *, is_new_path: bool = False) -> tuple[float | None, dict]:
    if model is None:
        return None, {}
    key = _endpoint_key(e.method, e.path)
    endpoints = model.get("endpoints") or {}
    scope = "endpoint" if key in endpoints else "global"
    submodel = endpoints.get(key) or model.get("global")
    if not submodel:
        return None, {}
    f = _row_features(e, is_new_path=is_new_path)
    vec = np.array([[f[c] for c in FEATURE_COLS]], dtype=np.float64)
    try:
        if_score = float(submodel["iforest"].decision_function(vec)[0])
        lof_score = float(submodel["lof"].decision_function(vec)[0])
        combined = float((if_score + lof_score) / 2.0)
        min_s = -0.5
        max_s = 0.5
        normalized = 1.0 - min(1.0, max(0.0, (combined - min_s) / (max_s - min_s)))
        return normalized, {
            "iforest_score": if_score,
            "lof_score": lof_score,
            "combined_score": combined,
            "features": f,
            "model_scope": scope,
            "explanation": explain_anomaly(submodel.get("feature_stats", {}), f),
        }
    except Exception:
        return None, {}


def is_anomaly(model: dict | None, score: float | None) -> bool:
    if score is None:
        return False
    return score >= get_settings().anomaly_threshold
