import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Users } from "./Users";
import { useAppStore } from "@/store/appStore";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    isAuthenticated: () => true,
    listUsers: vi.fn().mockResolvedValue([
      { id: 1, username: "admin", email: "admin@example.com", role: "admin", is_active: true, created_at: "2026-01-01T00:00:00Z", mfa_enabled: true },
      { id: 2, username: "bob", email: "bob@example.com", role: "viewer", is_active: true, created_at: "2026-01-02T00:00:00Z", mfa_enabled: false },
    ]),
  };
});

function renderUsers() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Users />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Users page", () => {
  beforeEach(() => {
    useAppStore.setState({ user: null });
  });

  it("shows an admin-access-required message for a non-admin caller", () => {
    useAppStore.setState({ user: { id: 2, username: "bob", email: null, role: "viewer", is_active: true } });
    renderUsers();
    expect(screen.getByText(/admin access required/i)).toBeInTheDocument();
  });

  it("lists users for an admin caller", async () => {
    useAppStore.setState({ user: { id: 1, username: "admin", email: null, role: "admin", is_active: true } });
    renderUsers();
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(screen.getAllByText("admin").length).toBeGreaterThan(0);
  });

  it("disables create button until required fields are valid", () => {
    useAppStore.setState({ user: { id: 1, username: "admin", email: null, role: "admin", is_active: true } });
    renderUsers();
    expect(screen.getByRole("button", { name: /create/i })).toBeDisabled();
  });
});
