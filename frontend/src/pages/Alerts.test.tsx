import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Alerts } from "./Alerts";

// vi.mock factories are hoisted above other top-level code, so the fixture
// referenced inside one must be declared via vi.hoisted rather than a plain
// const — otherwise it's a "used before initialization" error at runtime.
const { sampleAlert } = vi.hoisted(() => ({
  sampleAlert: {
    id: 1,
    created_at: "2026-01-01T00:00:00Z",
    alert_type: "traffic_anomaly",
    severity: "medium",
    title: "Anomalous API request pattern",
    detail: "IsolationForest score=0.91 for GET /api/search",
    method: "GET",
    path: "/api/search",
    acknowledged: false,
    event_id: 42,
    explanation: [{ feature: "query_entropy", value: 5.1, baseline_mean: 1.2, z_score: 4.3 }],
    feedback: null,
    feedback_at: null,
  },
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    isAuthenticated: () => true,
    listAlerts: vi.fn().mockResolvedValue([sampleAlert]),
    submitAlertFeedback: vi.fn().mockResolvedValue({ id: 1, feedback: "true_positive" }),
    ackAlert: vi.fn().mockResolvedValue({ id: 1, acknowledged: true }),
  };
});

describe("Alerts page", () => {
  it("renders the alert list", async () => {
    render(<Alerts />);
    expect(await screen.findByText("Anomalous API request pattern")).toBeInTheDocument();
  });

  it("opens the detail drawer with explanation when a card is clicked", async () => {
    render(<Alerts />);
    const card = await screen.findByText("Anomalous API request pattern");
    card.click();

    expect(await screen.findByText("Why this was flagged")).toBeInTheDocument();
    expect(screen.getByText("query_entropy")).toBeInTheDocument();
    expect(screen.getByText(/z = 4.30/)).toBeInTheDocument();
  });

  it("shows feedback buttons for an anomaly alert with an event_id", async () => {
    render(<Alerts />);
    const card = await screen.findByText("Anomalous API request pattern");
    card.click();

    expect(await screen.findByRole("button", { name: /real finding/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /false positive/i })).toBeInTheDocument();
  });
});
