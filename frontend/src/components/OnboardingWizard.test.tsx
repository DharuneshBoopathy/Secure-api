import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { OnboardingWizard } from "./OnboardingWizard";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    apiFetch: vi.fn().mockResolvedValue({ ingested: 2, skipped: 0 }),
  };
});

const emptyStats = { events_last_hour: 0, discovered_undocumented: 0, open_alerts: 0, known_endpoints: 0 };

function renderWizard(stats = emptyStats, onDataChanged = vi.fn(), onDismiss = vi.fn()) {
  return render(
    <MemoryRouter>
      <OnboardingWizard stats={stats} onDataChanged={onDataChanged} onDismiss={onDismiss} />
    </MemoryRouter>,
  );
}

describe("OnboardingWizard", () => {
  it("shows all three steps as not-done when the account is empty", () => {
    renderWizard();
    expect(screen.getByText("Register your API")).toBeInTheDocument();
    expect(screen.getByText("See traffic flow in")).toBeInTheDocument();
    expect(screen.getByText("Spot your first shadow endpoint")).toBeInTheDocument();
  });

  it("marks step 1 done once known_endpoints > 0", () => {
    renderWizard({ ...emptyStats, known_endpoints: 3 });
    expect(screen.getByText("Register your API")).toHaveClass("line-through");
  });

  it("calls onDismiss when Skip is clicked", () => {
    const onDismiss = vi.fn();
    renderWizard(emptyStats, vi.fn(), onDismiss);
    fireEvent.click(screen.getByRole("button", { name: /skip for now/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("sends demo traffic and calls onDataChanged on success", async () => {
    const onDataChanged = vi.fn();
    renderWizard(emptyStats, onDataChanged);
    fireEvent.click(screen.getByRole("button", { name: /send demo traffic/i }));
    await waitFor(() => expect(onDataChanged).toHaveBeenCalledTimes(1));
  });
});
