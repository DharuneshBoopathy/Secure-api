import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
      { id: 3, username: "root", email: "root@example.com", role: "super_admin", is_active: true, created_at: "2026-01-03T00:00:00Z", mfa_enabled: true },
      { id: 4, username: "dana", email: "dana@example.com", role: "viewer", is_active: false, created_at: "2026-01-04T00:00:00Z", mfa_enabled: false },
    ]),
  };
});

const ADMIN = { id: 1, username: "admin", email: null, role: "admin", is_active: true };
const SUPER_ADMIN = { id: 3, username: "root", email: null, role: "super_admin", is_active: true };

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
    useAppStore.setState({ user: ADMIN });
    renderUsers();
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(screen.getAllByText("admin").length).toBeGreaterThan(0);
  });

  it("lists users for a super admin caller", async () => {
    useAppStore.setState({ user: SUPER_ADMIN });
    renderUsers();
    expect(await screen.findByText("bob")).toBeInTheDocument();
  });

  it("disables create button until required fields are valid", () => {
    useAppStore.setState({ user: ADMIN });
    renderUsers();
    expect(screen.getByRole("button", { name: /create/i })).toBeDisabled();
  });

  it("hides the admin option from a plain admin's role dropdowns", async () => {
    useAppStore.setState({ user: ADMIN });
    renderUsers();
    const select = await screen.findByLabelText("Role for bob");
    expect(select).toBeInTheDocument();
    expect(within(select).queryByRole("option", { name: "admin" })).not.toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "editor" })).toBeInTheDocument();
  });

  it("offers the admin option to a super admin", async () => {
    useAppStore.setState({ user: SUPER_ADMIN });
    renderUsers();
    const select = await screen.findByLabelText("Role for bob");
    expect(within(select).getByRole("option", { name: "admin" })).toBeInTheDocument();
  });

  it("locks the super admin row for everyone, including the super admin", async () => {
    for (const caller of [ADMIN, SUPER_ADMIN]) {
      useAppStore.setState({ user: caller });
      const { unmount } = renderUsers();
      expect(await screen.findByText("bob")).toBeInTheDocument();
      expect(screen.queryByLabelText("Role for root")).not.toBeInTheDocument();
      expect(
        screen.getByLabelText("The super admin account cannot be modified"),
      ).toBeInTheDocument();
      unmount();
    }
  });

  it("locks a peer admin's row for a plain admin but not for the super admin", async () => {
    useAppStore.setState({ user: SUPER_ADMIN });
    const { unmount } = renderUsers();
    expect(await screen.findByLabelText("Role for admin")).toBeInTheDocument();
    unmount();

    // The reported bug: as a peer admin there was no way to demote this row.
    // It is now explicitly locked with a reason rather than silently failing.
    useAppStore.setState({ user: ADMIN });
    renderUsers();
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(screen.queryByLabelText("Role for admin")).not.toBeInTheDocument();
  });

  it("offers a reactivate action for a deactivated user", async () => {
    useAppStore.setState({ user: ADMIN });
    renderUsers();
    expect(await screen.findByRole("button", { name: /reactivate/i })).toBeInTheDocument();
  });
});
