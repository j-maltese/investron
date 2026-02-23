/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Custom brand colors
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
        },
        // Financial colors
        gain: {
          DEFAULT: "#22c55e",
          light: "#86efac",
          dark: "#16a34a",
        },
        loss: {
          DEFAULT: "#ef4444",
          light: "#fca5a5",
          dark: "#dc2626",
        },
        // Dark theme surface colors
        surface: {
          DEFAULT: "#0f0f23",
          50: "#1a1a2e",
          100: "#16213e",
          200: "#1e293b",
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
