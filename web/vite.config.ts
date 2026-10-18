/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs separately (`uv run tri-al serve`); Vite proxies /api to it.
const api = process.env.TRI_AL_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: api } },
  },
  preview: { port: 4173, proxy: { "/api": { target: api } } },
  build: {
    target: "es2022",
    manifest: true, // scripts/budget.mjs reads it
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
  },
});
