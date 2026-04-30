import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Login } from "./Login";

describe("Login page", () => {
  it("renders sign in form", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});
