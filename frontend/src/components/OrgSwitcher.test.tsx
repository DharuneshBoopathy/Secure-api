import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OrgSwitcher } from "./OrgSwitcher";

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    isAuthenticated: () => true,
    listMyOrgs: vi.fn().mockResolvedValue([
      { id: 1, name: "Acme Inc", slug: "acme-inc", owner_user_id: 1, created_at: "2026-01-01T00:00:00Z", my_role: "owner" },
      { id: 2, name: "Globex", slug: "globex", owner_user_id: 2, created_at: "2026-01-01T00:00:00Z", my_role: "viewer" },
    ]),
  };
});

describe("OrgSwitcher", () => {
  it("renders an option per organization the caller belongs to", async () => {
    render(<OrgSwitcher />);
    expect(await screen.findByRole("option", { name: "Acme Inc" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Globex" })).toBeInTheDocument();
  });
});
