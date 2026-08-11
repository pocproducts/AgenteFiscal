import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const r = (path: string) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
  resolve: {
    alias: [
      { find: "@/lib/db", replacement: r("../backend/db") },
      { find: "@/lib/ai", replacement: r("../backend/ai") },
      { find: "@/lib/artifacts", replacement: r("../backend/artifacts") },
      { find: "@/lib/i18n", replacement: r("./i18n/index.tsx") },
      { find: "@/lib", replacement: r("./lib") },
      { find: "@/components", replacement: r("./components") },
      { find: "@/hooks", replacement: r("./hooks") },
      { find: "@", replacement: r(".") },
    ],
  },
  test: {
    environment: "node",
    include: ["**/*.test.ts"],
    exclude: ["node_modules", ".next", "tests/**"],
  },
});
