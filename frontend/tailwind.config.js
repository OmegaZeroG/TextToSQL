/** @type {import('tailwindcss').Config} */

// Colours are CSS variables holding oklch channels so every utility supports
// opacity modifiers (e.g. bg-primary/10). The values live in src/index.css.
const token = (name) => `oklch(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: token("background"),
        foreground: token("foreground"),
        card: token("card"),
        border: token("border"),
        input: token("input"),
        muted: { DEFAULT: token("muted"), foreground: token("muted-foreground") },
        primary: { DEFAULT: token("primary"), foreground: token("primary-foreground") },
        secondary: { DEFAULT: token("secondary"), foreground: token("secondary-foreground") },
        accent: { DEFAULT: token("accent"), foreground: token("accent-foreground") },
        destructive: token("destructive"),
        warning: { DEFAULT: token("warning"), foreground: token("warning-foreground") },
        ring: token("ring"),
        syntax: {
          keyword: token("syn-keyword"),
          string: token("syn-string"),
          number: token("syn-number"),
          comment: token("syn-comment"),
          function: token("syn-function"),
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        serif: ['"Instrument Serif"', "Georgia", "serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 6px 24px -20px oklch(var(--foreground) / 1)",
        pop: "0 12px 32px -16px oklch(var(--foreground) / 0.35)",
      },
      keyframes: {
        "rise-in": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.97)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        shimmer: { to: { transform: "translateX(100%)" } },
        "soft-pulse": { "50%": { opacity: "0.45" } },
        "pop-check": {
          "0%": { transform: "scale(0.4)", opacity: "0" },
          "70%": { transform: "scale(1.15)", opacity: "1" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        "rise-in": "rise-in 0.5s cubic-bezier(0.2, 0.7, 0.2, 1) both",
        "fade-in": "fade-in 0.25s ease-out both",
        "scale-in": "scale-in 0.2s ease-out both",
        shimmer: "shimmer 1.6s ease-in-out infinite",
        "soft-pulse": "soft-pulse 1.6s ease-in-out infinite",
        "pop-check": "pop-check 0.35s ease-out both",
      },
    },
  },
  plugins: [],
};
