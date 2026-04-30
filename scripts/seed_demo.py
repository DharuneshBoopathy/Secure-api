"""
Register sample OpenAPI and push synthetic + realistic traffic for ML training.
Run after: uvicorn + MySQL up.  python scripts/seed_demo.py
"""
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
KEY = "change-me-local-dev-key"


def main() -> None:
    h = {"X-Monitor-Key": KEY}
    spec = (Path(__file__).resolve().parent.parent / "openapi" / "sample_api.yaml").read_text(
        encoding="utf-8"
    )
    with httpx.Client(timeout=30.0) as c:
        r = c.post(
            f"{BASE}/api/registry/openapi",
            headers=h,
            json={"title": "Demo Monitored API", "version": "1.0.0", "spec_yaml": spec},
        )
        r.raise_for_status()
        print("registry:", r.json())

        events = []
        for i in range(60):
            events.append(
                {
                    "method": "GET",
                    "path": f"/demo/v1/users/{i % 20}",
                    "status_code": 200,
                    "latency_ms": 12.0 + (i % 7),
                    "client_ip": "10.0.0.1",
                    "auth_present": True,
                    "body_bytes": 120,
                    "gateway": "seed",
                }
            )
        # Shadow / undocumented traffic
        for i in range(15):
            events.append(
                {
                    "method": "POST",
                    "path": "/demo/internal/debug/echo",
                    "status_code": 200,
                    "latency_ms": 80.0,
                    "auth_present": False,
                    "body_bytes": 50,
                    "gateway": "seed",
                }
            )
        r2 = c.post(f"{BASE}/api/ingest/batch", headers=h, json={"events": events})
        r2.raise_for_status()
        print("ingest:", r2.json())

        r3 = c.get(f"{BASE}/api/inventory/shadow", headers=h)
        r3.raise_for_status()
        print("shadow APIs:", r3.json())

        r4 = c.get(f"{BASE}/api/alerts", headers=h)
        r4.raise_for_status()
        print("alerts:", r4.json())


if __name__ == "__main__":
    main()
