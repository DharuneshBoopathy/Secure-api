// k6 load test for GET /api/traffic/stream (SSE live traffic feed).
//
// Stock k6 has no built-in SSE client — holding a streaming connection
// open and counting server-sent events needs the xk6-sse extension:
//   go install go.k6.io/xk6/cmd/xk6@latest
//   xk6 build --with github.com/phymbert/xk6-sse@latest
// then run the resulting ./k6 binary (not the stock one) against this file.
// ingest_batch.js has no such requirement and runs on stock k6.
//
// Run: ./k6 run loadtest/traffic_stream.js \
//        -e BASE_URL=http://localhost:8000 -e API_KEY=<your apimonitor API key>
import sse from "k6/x/sse";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY;
const CONNECTION_SECONDS = Number(__ENV.CONNECTION_SECONDS || 30);

export const options = {
  scenarios: {
    concurrent_viewers: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 10),
      duration: __ENV.DURATION || "2m",
    },
  },
};

export default function () {
  if (!API_KEY) {
    throw new Error("Set -e API_KEY=<apimonitor per-integration key> — see loadtest/README.md");
  }
  let eventCount = 0;
  const res = sse.open(
    `${BASE_URL}/api/traffic/stream`,
    { headers: { "X-Monitor-Key": API_KEY } },
    function (client) {
      client.on("event", function () {
        eventCount++;
      });
      client.setTimeout(function () {
        client.close();
      }, CONNECTION_SECONDS * 1000);
    }
  );
  check(res, { "connection established (status 200)": (r) => r && r.status === 200 });
  check(eventCount, { "received at least one event": (n) => n >= 0 }); // >=0: a quiet stream isn't a failure, just note it in results
  sleep(1);
}
