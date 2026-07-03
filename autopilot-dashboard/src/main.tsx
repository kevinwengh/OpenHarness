/**
 * Implement the autopilot dashboard's main module.
 *
 * Integration: Consumed by the Vite/React dashboard and its generated autopilot snapshot data.
 *
 * Event loop: Rendering and animation callbacks run in the browser event loop; avoid blocking
 * frames or leaking scheduled work.
 *
 * Change safety: Preserve component props, snapshot-data assumptions, responsive rendering, and the
 * dashboard build contract.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
