import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Members } from "./Members";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    isAuthenticated: () => true,
    listMyOrgs: vi.fn().mockResolvedValue([
      { id: 1, name: "Acme Inc", slug: "acme-inc", owner_user_id: 1, created_at: "2026-01-01T00:00:00Z", my_role: "owner" },
    ]),
    listOrgMembers: vi.fn().mockResolvedValue([
      { id: 1, user_id: 1, username: "alice", org_id: 1, role: "owner", status: "active", created_at: "2026-01-01T00:00:00Z", decided_at: "2026-01-01T00:00:00Z" },
      { id: 2, user_id: 2, username: "bob", org_id: 1, role: "viewer", status: "pending", created_at: "2026-01-02T00:00:00Z", decided_at: null },
    ]),
  };
});

describe("Members page", () => {
  it("renders page title and the caller's organization", async () => {
    render(
      <MemoryRouter>
        <Members />
      </MemoryRouter>,
    );
    expect(screen.getByText(/^Members$/)).toBeInTheDocument();
    expect(await screen.findByText("Acme Inc")).toBeInTheDocument();
  });

  it("shows a pending join request with approve/reject actions for an owner", async () => {
    render(
      <MemoryRouter>
        <Members />
      </MemoryRouter>,
    );
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
  });
});
