import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  // The daemon serves this bundle from its own root, so paths stay relative.
  base: "./",
  server: {
    strictPort: true,
  },
  test: {
    environment: "jsdom",
  },
});
