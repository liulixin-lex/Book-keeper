import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const api = process.env.BK_API ?? "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { "/api": { target: api, changeOrigin: false } },
  },
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 600 },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], globals: false },
});
