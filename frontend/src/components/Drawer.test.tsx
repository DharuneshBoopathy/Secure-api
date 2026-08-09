import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Drawer } from "./Drawer";

describe("Drawer", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <Drawer open={false} title="Detail" onClose={() => {}}>
        content
      </Drawer>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders title, subtitle, and children when open", () => {
    render(
      <Drawer open title="Alert detail" subtitle="traffic_anomaly" onClose={() => {}}>
        <p>raw event body</p>
      </Drawer>,
    );
    expect(screen.getByText("Alert detail")).toBeInTheDocument();
    expect(screen.getByText("traffic_anomaly")).toBeInTheDocument();
    expect(screen.getByText("raw event body")).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <Drawer open title="Detail" onClose={onClose}>
        content
      </Drawer>,
    );
    fireEvent.click(screen.getByRole("button", { name: /close panel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose on Escape keydown", () => {
    const onClose = vi.fn();
    render(
      <Drawer open title="Detail" onClose={onClose}>
        content
      </Drawer>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
