/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          bg: "#0f1117",
          card: "#1a1d27",
          border: "#2a2d3a",
          surface: "#141620",
        },
        accent: {
          green: "#10b981",
          red: "#ef4444",
          amber: "#f59e0b",
          blue: "#3b82f6",
        },
        primary: {
          50: "#f0fdf4",
          100: "#dcfce7",
          200: "#bbf7d0",
          300: "#86efac",
          400: "#4ade80",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
          800: "#065f46",
          900: "#064e3b",
        },
      },
    },
  },
  plugins: [],
};
