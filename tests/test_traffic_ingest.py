from app.schemas import IngestBatchItem


def test_ingest_batch_item_fields() -> None:
    row = IngestBatchItem(method="GET", path="/health", status_code=200, latency_ms=10.2, request_size_bytes=12)
    assert row.method == "GET"
    assert row.path == "/health"
    assert row.request_size_bytes == 12
