import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Shadow } from "./Shadow";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    getApiKey: () => "test-key",
    apiFetch: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 }),
  };
});

describe("Shadow page", () => {
  it("renders page title", () => {
    render(
      <MemoryRouter>
        <Shadow />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Shadow APIs/i)).toBeInTheDocument();
  });
});
