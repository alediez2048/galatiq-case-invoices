/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FastAPI (P5-01) listens on 127.0.0.1:8000 by default; override with API_PORT.
const apiTarget = `http://127.0.0.1:${process.env.API_PORT ?? "8000"}`;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["node_modules", "dist", "e2e/**"],
    css: false,
    restoreMocks: true,
    unstubGlobals: true,
  },
});
