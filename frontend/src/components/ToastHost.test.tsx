import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ToastHost } from "./ToastHost";
import { useAppStore } from "@/store/appStore";

function resetStore() {
  useAppStore.setState({ toasts: [] });
}

describe("ToastHost", () => {
  beforeEach(resetStore);
  afterEach(resetStore);

  it("renders nothing when there are no toasts", () => {
    const { container } = render(
      <MemoryRouter>
        <ToastHost />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a pushed toast with title and description", () => {
    useAppStore.getState().pushToast({
      title: "Traffic to undocumented endpoint",
      description: "undocumented_api — Observed GET /api/secret",
      variant: "warn",
      href: "/alerts",
    });
    render(
      <MemoryRouter>
        <ToastHost />
      </MemoryRouter>,
    );
    expect(screen.getByText("Traffic to undocumented endpoint")).toBeInTheDocument();
    expect(screen.getByText(/undocumented_api/)).toBeInTheDocument();
  });

  it("dismisses a toast when its close button is clicked", () => {
    useAppStore.getState().pushToast({ title: "Anomalous request", variant: "bad" });
    render(
      <MemoryRouter>
        <ToastHost />
      </MemoryRouter>,
    );
    expect(screen.getByText("Anomalous request")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /dismiss notification/i }));
    expect(screen.queryByText("Anomalous request")).not.toBeInTheDocument();
  });
});
