import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    exclude: ["tests/e2e/**", "node_modules/**"],
    coverage: { provider: "v8", reporter: ["text", "html"] },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
});
