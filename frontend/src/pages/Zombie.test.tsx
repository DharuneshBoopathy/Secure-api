import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Zombie } from "./Zombie";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    apiFetch: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 }),
  };
});

describe("Zombie page", () => {
  it("renders page heading", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <Zombie />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/Zombie \/ Idle APIs/i)).toBeInTheDocument();
  });
});
