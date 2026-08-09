/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      // Locally-available faces only — see the note in index.html about why
      // the Google Fonts link was removed. Each stack names the preferred
      // face first (used if the OS happens to have it) then falls back
      // through the standard system UI / monospace stacks.
      fontFamily: {
        sans: [
          "Plus Jakarta Sans",
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        // Editorial serif for page titles and display numbers. System faces
        // only — the reference design uses a licensed face we can't ship.
        display: [
          "Iowan Old Style",
          "Palatino Linotype",
          "Palatino",
          "Georgia",
          "Times New Roman",
          "serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      colors: {
        // Warm neutral ramp. The reference design sits on a cream/near-black
        // axis rather than the blue-grey slate this app used before, which is
        // most of why it reads as "soft" — every neutral carries a little red
        // and yellow instead of blue.
        // Lightness is matched step-for-step to Tailwind's `slate`, which this
        // replaced — the hue is warm but ink-500 is as dark as slate-500 was,
        // so swapping the scale in didn't quietly wash out every piece of
        // secondary text.
        ink: {
          0: "#FFFFFF",
          50: "#FAF8F5",
          100: "#F4F1EC",
          200: "#E7E3DC",
          300: "#D3CDC3",
          400: "#A8A29A",
          500: "#7A756C",
          600: "#5C574F",
          700: "#47433C",
          800: "#2E2B27",
          900: "#1A1918",
          950: "#141312",
        },
        // Accent — the teal pulled from the reference page's primary CTA.
        accent: {
          50: "#EDF7F8",
          100: "#DEF7F9",
          200: "#B7E5EA",
          300: "#7FCBD5",
          400: "#43A9B7",
          500: "#20808D",
          600: "#1A6B76",
          700: "#155860",
          800: "#12464C",
          900: "#0E373C",
          950: "#082226",
        },
        // Full ramps rather than a few stops: every semantic colour in the app
        // was previously a Tailwind hue (emerald/amber/rose) used across its
        // whole scale, so these have to cover the same range to swap in
        // without collapsing distinctions.
        positive: {
          50: "#F1F8F4",
          100: "#DFF1E7",
          200: "#BFE3CF",
          300: "#93CDAE",
          400: "#5CAF86",
          500: "#2E7D5B",
          600: "#256848",
          700: "#1E543A",
          800: "#19422F",
          900: "#123328",
          950: "#0A1F18",
        },
        warning: {
          50: "#FDF6EE",
          100: "#FBEBDA",
          200: "#F5D5B0",
          300: "#EBB57C",
          400: "#DC8F46",
          500: "#C2691E",
          600: "#A0561A",
          700: "#7E4416",
          800: "#613613",
          900: "#4A2A0C",
          950: "#2B1806",
        },
        negative: {
          50: "#FDF3F2",
          100: "#FBE3E1",
          200: "#F6C6C2",
          300: "#EC9C95",
          400: "#DB6960",
          500: "#BE3B32",
          600: "#9E2F28",
          700: "#7E2620",
          800: "#631E1A",
          900: "#4A1613",
          950: "#2A0C0A",
        },
      },
      borderRadius: {
        // The reference design clusters on 14/16px for controls and ~24px for
        // panels; Tailwind's defaults are a step smaller than that.
        lg: "0.75rem",
        xl: "0.875rem",
        "2xl": "1.125rem",
        "3xl": "1.5rem",
        glass: "1.375rem",
      },
      boxShadow: {
        card: "0 1px 2px rgb(26 25 24 / 0.04), 0 4px 16px -4px rgb(26 25 24 / 0.06)",
        "card-hover": "0 8px 32px -8px rgb(26 25 24 / 0.14)",
        // Frosted panel: a soft ambient drop plus the inner top highlight that
        // reads as a lit rim on the glass edge.
        glass: "0 8px 32px -8px rgb(26 25 24 / 0.12), inset 0 1px 0 rgb(255 255 255 / 0.85)",
        "glass-dark": "0 8px 32px -8px rgb(0 0 0 / 0.5), inset 0 1px 0 rgb(255 255 255 / 0.10)",
        glow: "0 0 0 1px rgb(32 128 141 / 0.18), 0 6px 24px -6px rgb(32 128 141 / 0.35)",
      },
      backdropBlur: {
        glass: "20px",
      },
      keyframes: {
        "fade-rise": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-rise": "fade-rise 0.35s cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};
