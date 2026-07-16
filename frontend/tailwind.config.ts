import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17202a",
        panel: "#f7f9fb",
        brand: "#0f766e",
        accent: "#b7791f"
      }
    }
  },
  plugins: []
};

export default config;
