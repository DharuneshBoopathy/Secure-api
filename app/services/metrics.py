from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

EVENTS_INGESTED = Counter(
    "apimonitor_events_ingested_total",
    "Traffic events stored",
    ["gateway"],
)
UNDOCUMENTED_HIT = Counter(
    "apimonitor_undocumented_endpoint_hits_total",
    "Hits to endpoints not in OpenAPI registry",
)
ANOMALY_FLAGGED = Counter(
    "apimonitor_anomaly_events_total",
    "Events scored as anomalous by ML",
)
IDLE_DOCUMENTED = Gauge(
    "apimonitor_idle_documented_endpoints",
    "Documented endpoints with no traffic in idle window",
)
OPEN_ALERTS = Gauge(
    "apimonitor_open_alerts",
    "Unacknowledged alerts",
)
DISCOVERED_SHADOW = Gauge(
    "apimonitor_discovered_undocumented_endpoints",
    "Unique discovered paths not in registry",
)
API_REQUESTS_TOTAL = Counter(
    "api_requests_total",
    "API requests by method/path/status",
    ["method", "path", "status"],
)
API_REQUEST_DURATION_SECONDS = Counter(
    "api_request_duration_seconds",
    "Total request duration seconds by method/path",
    ["method", "path"],
)
SHADOW_APIS_DETECTED_TOTAL = Gauge(
    "shadow_apis_detected_total",
    "Total detected shadow APIs",
)
ZOMBIE_APIS_TOTAL = Gauge(
    "zombie_apis_total",
    "Total zombie APIs by status",
    ["status"],
)
ANOMALY_DETECTIONS_TOTAL = Counter(
    "anomaly_detections_total",
    "Count of anomaly detections",
)
ACTIVE_ALERTS_TOTAL = Gauge(
    "active_alerts_total",
    "Open alerts by severity",
    ["severity"],
)
# api_request_duration_seconds (above) is a Counter — good for an average via
# rate(), but has no bucket data, so p95/p99 SLO dashboards/alerts can't be
# built from it. This Histogram fills that gap. Deliberately unlabeled by
# path (unlike the counter above) to avoid unbounded label cardinality on a
# metric that fans out into 10+ time series per label combination already.
REQUEST_DURATION_HISTOGRAM = Histogram(
    "apimonitor_request_duration_seconds",
    "Request duration in seconds (global, for p50/p95/p99 SLO dashboards and alerting)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
ML_LAST_RETRAIN_TIMESTAMP = Gauge(
    "apimonitor_ml_last_retrain_timestamp",
    "Unix timestamp of the last successful ML retrain pass (across all orgs)",
)
INGEST_QUEUE_DEPTH = Gauge(
    "apimonitor_ingest_queue_depth",
    "Pending entries in the Redis ingest stream (0 / absent when queueing is disabled)",
)
INGEST_QUEUE_DEAD_LETTER_TOTAL = Counter(
    "apimonitor_ingest_queue_dead_letter_total",
    "Ingest events moved to the dead-letter stream after repeated processing failures",
)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
