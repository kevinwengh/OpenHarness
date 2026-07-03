/**
 * Implement the autopilot dashboard's vite.config module.
 *
 * Integration: Consumed by the Vite/React dashboard and its generated autopilot snapshot data.
 *
 * Event loop: Rendering and animation callbacks run in the browser event loop; avoid blocking
 * frames or leaking scheduled work.
 *
 * Change safety: Preserve component props, snapshot-data assumptions, responsive rendering, and the
 * dashboard build contract.
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../docs/autopilot",
    emptyOutDir: false,
  },
});
