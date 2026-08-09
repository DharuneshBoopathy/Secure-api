import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Connections } from "./Connections";

// vi.mock is hoisted above every const in this file, so the fixtures it reads
// have to be hoisted with it.
const fixtures = vi.hoisted(() => ({
  providers: [
    {
      id: "anthropic",
      label: "Anthropic (Claude)",
      base_url: "https://api.anthropic.com",
      key_hint: "sk-ant-…",
      docs_url: "https://console.anthropic.com/settings/keys",
      endpoint_count: 12,
      requires_base_url: false,
    },
    {
      id: "custom",
      label: "Other / custom API",
      base_url: "",
      key_hint: "any key",
      docs_url: null,
      endpoint_count: 0,
      requires_base_url: true,
    },
  ],
  connection: {
    id: 7,
    name: "Claude production",
    provider: "anthropic",
    provider_label: "Anthropic (Claude)",
    base_url: "https://api.anthropic.com",
    key_masked: "sk-ant-a…9f2c",
    endpoints_registered: 12,
    status: "active" as const,
    last_checked_at: "2026-08-09T10:00:00Z",
    last_check_detail: "HTTP 200 from GET /v1/models — key accepted.",
    created_at: "2026-08-09T09:00:00Z",
  },
}));

const createConnection = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    isAuthenticated: () => true,
    listProviders: vi.fn().mockResolvedValue(fixtures.providers),
    listConnections: vi.fn().mockResolvedValue([fixtures.connection]),
    createConnection,
    verifyConnection: vi.fn().mockResolvedValue(fixtures.connection),
    deleteConnection: vi.fn().mockResolvedValue({ deleted: true, endpoints_removed: 12 }),
  };
});

const connection = fixtures.connection;

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Connections />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Connections page", () => {
  beforeEach(() => {
    createConnection.mockReset();
    createConnection.mockResolvedValue({ ...connection, id: 8, name: "New API" });
  });

  it("lists existing connections with a masked key", async () => {
    renderPage();
    expect(await screen.findByText("Claude production")).toBeInTheDocument();
    expect(screen.getByText("sk-ant-a…9f2c")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("keeps the connect button disabled until a name and key are entered", async () => {
    renderPage();
    const submit = screen.getByRole("button", { name: /connect api/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "My Claude" } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "sk-ant-api03-abcdefghijkl" } });
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("submits the pasted key to the backend", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "My Claude" } });
    fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "sk-ant-api03-abcdefghijkl" } });
    fireEvent.click(screen.getByRole("button", { name: /connect api/i }));

    await waitFor(() =>
      expect(createConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "anthropic",
          name: "My Claude",
          api_key: "sk-ant-api03-abcdefghijkl",
          verify: true,
        }),
      ),
    );
  });

  it("asks for a base URL and endpoint list only for a custom API", async () => {
    renderPage();
    expect(screen.queryByLabelText(/base url/i)).not.toBeInTheDocument();

    await screen.findByRole("option", { name: /custom/i });
    fireEvent.change(screen.getByLabelText(/^provider$/i), { target: { value: "custom" } });

    expect(screen.getByLabelText(/base url/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/endpoints to monitor/i)).toBeInTheDocument();
    // Name + key alone are no longer enough once a custom target is selected.
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "Internal billing" } });
    fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "abcdefghijkl" } });
    expect(screen.getByRole("button", { name: /connect api/i })).toBeDisabled();
  });
});
