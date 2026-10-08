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
        canvas: "var(--canvas, #f6f5f1)",
        surface: {
          DEFAULT: "var(--surface, #ffffff)",
          soft: "var(--surface-soft, #f1efe9)",
          muted: "var(--surface-muted, #e9e6de)",
        },
        border: {
          DEFAULT: "var(--border, #e4e1d8)",
          subtle: "var(--border-subtle, #efede6)",
          active: "var(--border-active, #d3cfc2)",
        },
        text: {
          main: "var(--text-main, #1b1e1c)",
          muted: "var(--text-muted, #5f665f)",
          dim: "var(--text-dim, #9aa19b)",
        },
        primary: {
          DEFAULT: "var(--primary, #0c8a5f)",
          hover: "var(--primary-hover, #0a7350)",
          soft: "var(--primary-soft, rgba(12, 138, 95, 0.09))",
        },
        info: "var(--info, #0284c7)",
        warning: "var(--warning, #b45309)",
        danger: "var(--danger, #dc2626)",
        success: "var(--success, #0c8a5f)",
      },
      borderColor: {
        DEFAULT: "var(--border, #e4e1d8)",
      },
      fontFamily: {
        sans: [
          "Inter",
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
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgba(27, 30, 28, 0.05)",
        sm: "0 1px 3px 0 rgba(27, 30, 28, 0.07), 0 1px 2px -1px rgba(27, 30, 28, 0.06)",
        md: "0 4px 14px -2px rgba(27, 30, 28, 0.09)",
        lg: "0 10px 24px -4px rgba(27, 30, 28, 0.11)",
        xl: "0 16px 32px -6px rgba(27, 30, 28, 0.13)",
        neu: "inset 0 1px 1px rgba(255, 255, 255, 0.7), 0 1px 2px rgba(27, 30, 28, 0.06)",
        "neu-pressed": "inset 0 1px 3px rgba(27, 30, 28, 0.08), 0 1px 1px rgba(255, 255, 255, 0.6)",
        glass: "0 8px 32px rgba(27, 30, 28, 0.12)",
        glow: "0 0 20px -3px rgba(12, 138, 95, 0.22)",
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};
export default config;
