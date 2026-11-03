import type { Config } from "tailwindcss";

// TM11-142: the palettes below are the dark theme. `neutral`, `accent` and the status
// colours keep their usual names so existing classes (bg-neutral-100, text-rose-700, …)
// pick up dark-safe values: low numbers are dark tints of the navy ground, high numbers
// are light text. docs/FRONTEND.md lists what each one is for.
export default {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
      },
      colors: {
        // Navy tints for surfaces and hovers, then light inks. Inverted on purpose.
        neutral: {
          50: "#0f1c3d",
          100: "#13234a",
          200: "#1c2c58",
          300: "#2a3c70",
          400: "#7c86a3",
          500: "#a3acc6",
          600: "#c4cadb",
          700: "#d9dbe3",
          800: "#e8e1d0",
          900: "#f1e7d0",
        },
        // Cream. 50–200 are navy tints for selected states; 500–700 are the cream itself.
        accent: {
          50: "#13234a",
          100: "#1c2c58",
          200: "#2a3c70",
          500: "#e8d9b5",
          600: "#f1e7d0",
          700: "#f1e7d0",
        },
        // Status colours: a dark tinted fill (50) with light text (600+) that passes AA on it.
        rose: {
          50: "#2a1220",
          200: "#5a2236",
          300: "#8a3a52",
          600: "#f2b8c6",
          700: "#f2b8c6",
          800: "#f8d3dc",
        },
        red: {
          50: "#2a1220",
          300: "#8a3a52",
          700: "#f2b8c6",
          800: "#f8d3dc",
        },
        emerald: {
          50: "#0e2a26",
          200: "#1f5247",
          700: "#9fe3c8",
          800: "#c3f0dd",
        },
        amber: {
          500: "#f0c674",
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.3)",
        lift: "0 12px 32px -8px rgb(0 0 0 / 0.6), 0 2px 6px -2px rgb(0 0 0 / 0.4)",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0.3" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s cubic-bezier(0.16,1,0.3,1) both",
        "fade-in": "fade-in 0.6s cubic-bezier(0.4,0,0.2,1) both",
      },
    },
  },
  plugins: [],
} satisfies Config;
