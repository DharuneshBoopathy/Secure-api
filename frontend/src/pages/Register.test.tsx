import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Register } from "@/pages/Register";

describe("Register page", () => {
  it("has no placeholders and keeps every field labelled", () => {
    render(
      <MemoryRouter>
        <Register />
      </MemoryRouter>,
    );
    // The four selectors the Playwright specs now use.
    for (const label of ["Username", "Email", "Confirm password"]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByLabelText("Password", { exact: true })).toBeInTheDocument();

    for (const input of document.querySelectorAll("input")) {
      expect(input.getAttribute("placeholder")).toBeNull();
    }
  });
});
