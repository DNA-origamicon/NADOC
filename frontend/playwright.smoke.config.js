import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Isolated config for the commit-gate smoke run (`just smoke`).
//
// Unlike playwright.config.js (which reuses a running dev server on :8000/:5173
// for ad-hoc troubleshooting specs), this config stands up its OWN throwaway
// servers on dedicated ports (backend :8001, Vite :5174) and tears them down at
// the end — so smoke never touches, mutates, or starves the user's dev server.
//   • reuseExistingServer:false  → always fresh, Playwright-owned, auto-killed.
//   • backend runs WITHOUT --reload → no WSL2 file-watcher wedge.
//   • the test Vite proxies /api → :8001 (VITE_API_PORT), not the user's :8000.
//   • globalTimeout hard-caps the whole run so a stuck run self-aborts (and tears
//     its servers down) instead of hanging.
// Session-doc cleanup (test .session/<doc> dirs) happens in ./e2e/global-teardown.js.
const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')

const BACKEND_PORT = '8001'
const FRONTEND_PORT = '5174'

// Tell the specs/helpers (smoke.spec.js, scene_harness.js) to hit the throwaway
// backend. Set before the workers fork so they inherit it.
process.env.NADOC_E2E_API_BASE ??= `http://127.0.0.1:${BACKEND_PORT}`

export default defineConfig({
  testDir: './e2e',
  globalTeardown: './e2e/global-teardown.js',
  globalTimeout: 360_000,      // 6 min whole-run cap → self-abort + server teardown
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,

  reporter: [['list']],

  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: [
    {
      // Throwaway backend — NO --reload (avoids the WSL2 watcher wedge).
      command: `uv run uvicorn backend.api.main:app --port ${BACKEND_PORT} --host 127.0.0.1`,
      cwd: REPO_ROOT,
      env: { NADOC_DISABLE_SESSION_CACHE: '1' },   // no .session autosave into shared workspace/
      url: `http://127.0.0.1:${BACKEND_PORT}/docs`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      // Throwaway Vite — proxies /api → the throwaway backend via VITE_API_PORT.
      // --strictPort so it fails loudly instead of drifting to another port.
      command: `npx vite --port ${FRONTEND_PORT} --host 127.0.0.1 --strictPort`,
      cwd: FRONTEND_DIR,
      env: { VITE_API_PORT: BACKEND_PORT },
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
