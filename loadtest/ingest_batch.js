// k6 load test for POST /api/ingest/batch — the highest-volume write path
// (traffic events -> DB insert + ML scoring, or -> Redis stream if
// REDIS_URL is set; see app/routers/ingest.py).
//
// Run: k6 run loadtest/ingest_batch.js \
//        -e BASE_URL=http://localhost:8000 -e API_KEY=<your apimonitor API key>
//
// See loadtest/README.md for how to get an API_KEY and for the "no
// fabricated numbers" note on the thresholds below.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY;
const BATCH_SIZE = Number(__ENV.BATCH_SIZE || 50);
const RATE = Number(__ENV.RATE || 20); // batches/sec

export const options = {
  scenarios: {
    steady_ingest: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: __ENV.DURATION || "2m",
      preAllocatedVUs: 20,
      maxVUs: 200,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    // Placeholder budget, not a measured SLO — replace once you've run this
    // against your own deployment (see loadtest/README.md).
    http_req_duration: ["p(95)<1000"],
  },
};

const SAMPLE_PATHS = [
  "/api/users",
  "/api/orders",
  "/api/payments/transfer",
  "/health",
  "/api/reports?type=monthly",
];

function randomEvent() {
  return {
    method: Math.random() < 0.7 ? "GET" : "POST",
    path: SAMPLE_PATHS[Math.floor(Math.random() * SAMPLE_PATHS.length)],
    status_code: Math.random() < 0.05 ? 500 : 200,
    latency_ms: Math.random() * 200,
    body_bytes: Math.floor(Math.random() * 2000),
    request_size_bytes: Math.floor(Math.random() * 1000),
    response_size_bytes: Math.floor(Math.random() * 4000),
  };
}

export default function () {
  if (!API_KEY) {
    throw new Error("Set -e API_KEY=<apimonitor per-integration key> — see loadtest/README.md");
  }
  const events = [];
  for (let i = 0; i < BATCH_SIZE; i++) {
    events.push(randomEvent());
  }
  const res = http.post(`${BASE_URL}/api/ingest/batch`, JSON.stringify({ events }), {
    headers: { "Content-Type": "application/json", "X-Monitor-Key": API_KEY },
  });
  check(res, {
    "status is 200": (r) => r.status === 200,
  });
  sleep(0.1);
}
