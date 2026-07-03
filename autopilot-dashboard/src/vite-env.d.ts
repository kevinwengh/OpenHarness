/**
 * Implement the autopilot dashboard's vite env module.
 *
 * Integration: Consumed by the Vite/React dashboard and its generated autopilot snapshot data.
 *
 * Event loop: Rendering and animation callbacks run in the browser event loop; avoid blocking
 * frames or leaking scheduled work.
 *
 * Change safety: Preserve component props, snapshot-data assumptions, responsive rendering, and the
 * dashboard build contract.
 */

/// <reference types="vite/client" />
