import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAlertToasts } from "./useAlertToasts";
import { useAppStore } from "@/store/appStore";

const getStreamTicket = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return { ...actual, getStreamTicket };
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

function TestHarness() {
  useAlertToasts();
  return null;
}

/** The connection is opened after an awaited ticket fetch, so nothing exists
 * synchronously after render. */
async function firstSource() {
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
  return FakeEventSource.instances[0];
}

describe("useAlertToasts", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
     
    (globalThis as any).EventSource = FakeEventSource;
    useAppStore.setState({ toasts: [], accessToken: "" });
    localStorage.clear();
    getStreamTicket.mockReset();
    getStreamTicket.mockResolvedValue({ ticket: "ticket-abc", expires_in: 60 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not open a connection when unauthenticated", () => {
    render(<TestHarness />);
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(getStreamTicket).not.toHaveBeenCalled();
  });

  it("authenticates with a short-lived ticket, never the access token", async () => {
    useAppStore.setState({ accessToken: "jwt-123" });
    render(<TestHarness />);
    const source = await firstSource();

    expect(source.url).toBe("/api/alerts/stream?ticket=ticket-abc");
    // The regression this guards: the access token used to be placed in the
    // URL, which put it into every access log along the request path.
    expect(source.url).not.toContain("jwt-123");
    expect(source.url).not.toContain("auth=");
  });

  it("pushes a toast for each streamed alert, severity mapped to variant", async () => {
    useAppStore.setState({ accessToken: "jwt-123" });
    render(<TestHarness />);
    const source = await firstSource();

    source.emit({ id: 1, alert_type: "undocumented_api", severity: "high", title: "New shadow endpoint", detail: "GET /api/secret" });
    source.emit({ id: 2, alert_type: "traffic_anomaly", severity: "medium", title: "Anomalous request", detail: "score=0.9" });

    const toasts = useAppStore.getState().toasts;
    expect(toasts).toHaveLength(2);
    expect(toasts[0]).toMatchObject({ title: "New shadow endpoint", variant: "bad", href: "/alerts" });
    expect(toasts[1]).toMatchObject({ title: "Anomalous request", variant: "warn" });
  });

  it("closes the EventSource on unmount", async () => {
    useAppStore.setState({ accessToken: "jwt-123" });
    const { unmount } = render(<TestHarness />);
    const source = await firstSource();
    expect(source.closed).toBe(false);
    unmount();
    expect(source.closed).toBe(true);
  });

  it("reconnects with a freshly minted ticket after a drop", async () => {
    // A ticket outlives neither the stream nor a network blip, so the retry
    // has to mint a new one — replaying the old URL would loop on a 401.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    useAppStore.setState({ accessToken: "jwt-123" });
    render(<TestHarness />);
    const first = await firstSource();

    getStreamTicket.mockResolvedValue({ ticket: "ticket-second", expires_in: 60 });
    first.onerror?.();
    expect(first.closed).toBe(true);

    await vi.advanceTimersByTimeAsync(1_500);
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(2));
    expect(FakeEventSource.instances[1].url).toBe("/api/alerts/stream?ticket=ticket-second");
    expect(getStreamTicket).toHaveBeenCalledTimes(2);
  });

  it("does not reconnect after unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    useAppStore.setState({ accessToken: "jwt-123" });
    const { unmount } = render(<TestHarness />);
    const source = await firstSource();

    source.onerror?.();
    unmount();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
