from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

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


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
