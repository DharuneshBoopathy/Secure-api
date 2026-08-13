import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Audit } from "./Audit";
import { listAudit } from "@/api/client";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return { ...actual, listAudit: vi.fn() };
});

const mockListAudit = vi.mocked(listAudit);

function row(id: number) {
  return {
    id,
    event_type: "login_attempt",
    actor: `user${id}`,
    target: null,
    ip: "10.0.0.1",
    user_agent: null,
    timestamp: "2026-01-01T00:00:00Z",
    success: true,
  };
}

function renderAudit() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Audit />
    </QueryClientProvider>,
  );
}

describe("Audit page", () => {
  beforeEach(() => {
    mockListAudit.mockReset();
  });

  it("requests the keyset parameters the endpoint actually declares", async () => {
    // The page used to send ?page=1&page_size=100. FastAPI does not declare
    // either parameter on this route, so both were dropped and the response
    // silently fell back to the default 25 rows.
    mockListAudit.mockResolvedValue({ items: [row(1)], next_cursor_id: null });
    renderAudit();

    expect(await screen.findByText("user1")).toBeInTheDocument();
    expect(mockListAudit).toHaveBeenCalledWith(null);
  });

  it("pages backwards through history with the returned cursor", async () => {
    mockListAudit
      .mockResolvedValueOnce({ items: [row(30)], next_cursor_id: 30 })
      .mockResolvedValueOnce({ items: [row(29)], next_cursor_id: null });
    renderAudit();

    expect(await screen.findByText("user30")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /load older events/i }));

    expect(await screen.findByText("user29")).toBeInTheDocument();
    expect(mockListAudit).toHaveBeenLastCalledWith(30);
    // Older pages accumulate rather than replacing what is already on screen.
    expect(screen.getByText("user30")).toBeInTheDocument();
  });

  it("hides the load-more control once the log is exhausted", async () => {
    mockListAudit.mockResolvedValue({ items: [row(1)], next_cursor_id: null });
    renderAudit();

    expect(await screen.findByText("user1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /load older events/i })).not.toBeInTheDocument();
    expect(screen.getByText(/start of the log/i)).toBeInTheDocument();
  });

  it("shows an empty state rather than a bare table when there are no events", async () => {
    mockListAudit.mockResolvedValue({ items: [], next_cursor_id: null });
    renderAudit();

    expect(await screen.findByText(/no audit entries/i)).toBeInTheDocument();
  });
});
