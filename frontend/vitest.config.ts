import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    // jsdom only implements window.localStorage for a non-opaque (http/https)
    // origin; without this, localStorage.getItem is not a function.
    environmentOptions: { jsdom: { url: "http://localhost:3000" } },
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // e2e/ holds Playwright specs (own runner, own `test`/`expect` API, needs
    // a live backend+frontend — see e2e/README.md) — not vitest's to collect.
    // Setting `exclude` replaces vitest's built-in default list rather than
    // extending it, so the usual defaults are repeated here alongside it.
    exclude: [
      "**/node_modules/**",
      "**/dist/**",
      "**/cypress/**",
      "**/.{idea,git,cache,output,temp}/**",
      "**/{karma,rollup,webpack,vite,vitest,jest,ava,babel,nyc,cypress,tsup,build}.config.*",
      "**/e2e/**",
    ],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      lines: 60,
      functions: 60,
      branches: 60,
      statements: 60,
    },
  },
});
