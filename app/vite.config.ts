import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Port 1420 is what src-tauri/tauri.conf.json points the dev window at.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, host: "127.0.0.1" },
  build: { target: "safari15", outDir: "dist" },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
