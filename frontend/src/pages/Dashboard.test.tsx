import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Dashboard } from "./Dashboard";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    getApiKey: () => "test-key",
    apiFetch: vi.fn().mockResolvedValue({}),
  };
});

describe("Dashboard page", () => {
  it("renders overview header", () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Overview/i)).toBeInTheDocument();
  });
});
