import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Anomalies } from "./Anomalies";

const { sampleEvent } = vi.hoisted(() => ({
  sampleEvent: {
    id: 7,
    ts: "2026-01-01T00:00:00Z",
    method: "GET",
    path: "/api/search",
    status_code: 200,
    source_ip: "10.0.0.5",
    response_time_ms: 12.5,
    request_size_bytes: 100,
    response_size_bytes: 500,
    user_agent: "curl/8.0",
    content_type: "application/json",
    x_forwarded_for: null,
    referer: null,
    monitor_key: null,
    session_id: "sess-1",
    anomaly_score: 0.91,
    is_anomaly: true,
    anomaly_features: {
      explanation: [{ feature: "query_entropy", value: 5.1, baseline_mean: 1.2, z_score: 4.3 }],
    },
  },
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    apiFetch: vi.fn().mockResolvedValue({ items: [sampleEvent], total: 1, page: 1, page_size: 25 }),
  };
});

function renderAnomalies() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <Anomalies />
    </QueryClientProvider>,
  );
}

describe("Anomalies page", () => {
  it("renders the anomaly table", async () => {
    renderAnomalies();
    expect(await screen.findByText("/api/search")).toBeInTheDocument();
  });

  it("opens the detail drawer with explanation on row click", async () => {
    renderAnomalies();
    const row = await screen.findByText("/api/search");
    row.closest("tr")?.click();

    expect(await screen.findByText("Why this was flagged")).toBeInTheDocument();
    expect(screen.getByText("query_entropy")).toBeInTheDocument();
  });
});
