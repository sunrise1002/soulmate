import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Screens need a device runtime; the pairing and transport rules do not.
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
