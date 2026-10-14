import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas, oklch(0.99 0 0))",
        surface: {
          DEFAULT: "var(--surface, #ffffff)",
          soft: "var(--surface-soft, oklch(0.94 0 0))",
          muted: "var(--surface-muted, oklch(0.97 0 0))",
        },
        border: {
          DEFAULT: "var(--border, oklch(0.92 0 0))",
          subtle: "var(--border-subtle, oklch(0.94 0 0))",
          active: "var(--border-active, oklch(0.72 0 0))",
        },
        text: {
          main: "var(--text-main, oklch(0 0 0))",
          muted: "var(--text-muted, oklch(0.44 0 0))",
          dim: "var(--text-dim, oklch(0.55 0 0))",
        },
        primary: {
          DEFAULT: "var(--primary, oklch(0 0 0))",
          hover: "var(--primary-hover, oklch(0.2 0 0))",
          soft: "var(--primary-soft, oklch(0.94 0 0))",
        },
        info: "var(--info, oklch(0.55 0.22 264.53))",
        warning: "var(--warning, oklch(0.81 0.17 75.35))",
        danger: "var(--danger, oklch(0.63 0.19 23.03))",
        success: "var(--success, oklch(0.55 0.22 264.53))",
      },
      borderColor: {
        DEFAULT: "var(--border, oklch(0.92 0 0))",
      },
      fontFamily: {
        sans: [
          "var(--font-geist)",
          "Geist",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        serif: ["Newsreader", "Georgia", "Cambria", "Times New Roman", "Times", "serif"],
        mono: [
          "var(--font-geist-mono)",
          "Geist Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        sm: "0 1px 3px 0 rgba(0, 0, 0, 0.07), 0 1px 2px -1px rgba(0, 0, 0, 0.06)",
        md: "0 4px 14px -2px rgba(0, 0, 0, 0.09)",
        lg: "0 10px 24px -4px rgba(0, 0, 0, 0.11)",
        xl: "0 16px 32px -6px rgba(0, 0, 0, 0.13)",
        neu: "inset 0 1px 1px rgba(255, 255, 255, 0.7), 0 1px 2px rgba(0, 0, 0, 0.06)",
        "neu-pressed": "inset 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 1px rgba(255, 255, 255, 0.6)",
        glass: "0 8px 32px rgba(0, 0, 0, 0.12)",
        glow: "0 0 20px -3px rgba(0, 0, 0, 0.16)",
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};
export default config;
