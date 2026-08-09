import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

/**
 * The type-checker already covers types, so this config is aimed at the
 * classes of bug tsc cannot see: stale closures and missing effect
 * dependencies (react-hooks), unhandled promises, and accidental `any`
 * leaking through API boundaries.
 */
export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules", "playwright-report", "test-results"] },

  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,

  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.json", "./tsconfig.node.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // A floating promise in an event handler swallows its own failure, which
      // is how a request can fail with nothing shown to the user.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",

      // Unused variables are usually a leftover from a refactor; the
      // underscore escape hatch keeps intentional signature padding readable.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],

      // --- warnings rather than errors, deliberately ---
      //
      // These are worth seeing but shouldn't block a build on a codebase that
      // predates the linter. Promote them to "error" once the existing
      // occurrences are worked through.

      // Flags the ordinary `useEffect(() => { void load(); }, [load])`
      // fetch-on-mount pattern this app uses throughout. It's a performance
      // recommendation, not a correctness rule — unlike rules-of-hooks and
      // exhaustive-deps above it, which stay errors.
      "react-hooks/set-state-in-effect": "warn",

      // `any` arriving from JSON.parse at the API boundary. Real, but fixing
      // it properly means typing the wire format, not silencing the rule.
      "@typescript-eslint/no-unsafe-assignment": "warn",
      "@typescript-eslint/no-unsafe-member-access": "warn",
      "@typescript-eslint/no-unsafe-call": "warn",
      "@typescript-eslint/no-unsafe-argument": "warn",
      "@typescript-eslint/no-unsafe-return": "warn",
      "@typescript-eslint/require-await": "warn",
      "@typescript-eslint/no-unnecessary-type-assertion": "warn",
    },
  },

  // Tests reach into mocks and fixtures where precise typing costs more than
  // it returns; keep the correctness rules, drop the strictness-only ones.
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**/*"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-unsafe-return": "off",
    },
  },

  // Config files run in Node, not the browser.
  {
    files: ["*.config.{js,ts}", "vite.config.ts", "vitest.config.ts", "playwright.config.ts"],
    languageOptions: { globals: globals.node },
    rules: { "@typescript-eslint/no-unsafe-assignment": "off" },
  },
);
