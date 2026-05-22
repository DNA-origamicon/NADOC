import base from './playwright.config.js'

/**
 * Bench config for the LOD FPS sweep.
 *
 * The default playwright.config.js carries a `webServer` block whose backend
 * entry probes http://127.0.0.1:8000/docs and (on this WSL2 box, where
 * localhost ≠ 127.0.0.1) times out, then tries to spawn uvicorn in
 * /home/jojo/Work/NADOC — a path that only exists on the OTHER computer. That
 * stalls Playwright in setup before any test runs.
 *
 * Both dev servers are expected to be already running (`just dev` + `just
 * frontend`); the app reaches the backend through Vite's /api proxy, so
 * Playwright needs to manage nothing. We drop `webServer` and point baseURL at
 * the localhost form that actually resolves here.
 */
export default {
  ...base,
  webServer: undefined,
  use: { ...base.use, baseURL: 'http://localhost:5173' },
}
