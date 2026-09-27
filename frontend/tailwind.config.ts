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
        canvas: "#F6F7F5",
        surface: {
          DEFAULT: "#FFFFFF",
          soft: "#FBFCFA",
        },
        border: "#E7EAE5",
        text: {
          main: "#171A17",
          muted: "#68706A",
        },
        primary: {
          DEFAULT: "#173F35",
          hover: "#285C4F",
          soft: "#E8F0EC",
        },
        info: "#2F6B9A",
        warning: "#A87517",
        danger: "#B84B4B",
        success: "#2F7154",
      },
      borderColor: {
        DEFAULT: "#E7EAE5",
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
        xs: "0 1px 2px 0 rgba(23, 26, 23, 0.05)",
        sm: "0 1px 3px 0 rgba(23, 26, 23, 0.07), 0 1px 2px -1px rgba(23, 26, 23, 0.07)",
        md: "0 4px 14px 0 rgba(25, 35, 28, 0.06)",
        lg: "0 10px 24px -3px rgba(25, 35, 28, 0.08)",
        xl: "0 16px 32px -4px rgba(25, 35, 28, 0.10)",
        neu: "inset 0 1px 1px rgba(255, 255, 255, 0.9), 0 1px 2px rgba(23, 26, 23, 0.05)",
        "neu-pressed": "inset 0 1px 3px rgba(23, 26, 23, 0.08), 0 1px 1px rgba(255, 255, 255, 0.8)",
        glass: "0 8px 30px rgba(0, 0, 0, 0.04)",
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};
export default config;
