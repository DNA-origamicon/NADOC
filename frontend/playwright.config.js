import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Resolve server CWDs relative to this config file so the e2e/boot gate works on
// any checkout (previously hardcoded to one machine's absolute path, which made
// webServer auto-start fail with spawn ENOENT elsewhere).
const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')

// DEDICATED ports + reuseExistingServer:false so an e2e run never reuses, mutates,
// or STARVES the user's dev backend on :8000.  Previously this used
// reuseExistingServer:true on :8000, so running the suite while a dev server was up
// ran every test IN the user's live backend — creating a session doc per test in
// their workspace/.session/.  (The session docs still land on shared disk because
// this backend shares workspace/; ./e2e/global-teardown.js removes the test ones so
// they don't survive to be restored on the user's next restart.  Full workspace
// isolation is NOT used: the assembly harness saves parts to a cwd-relative
// workspace/ path but loads them relative to the backend's workspace, so an override
// would split those apart.)
const BACKEND_PORT = process.env.NADOC_E2E_BACKEND_PORT || '8002'
const FRONTEND_PORT = process.env.NADOC_E2E_FRONTEND_PORT || '5175'

// Specs/helpers that call the API directly (scene_harness.js) must hit this
// throwaway backend, not the proxied dev one.
process.env.NADOC_E2E_API_BASE ??= `http://127.0.0.1:${BACKEND_PORT}`

/**
 * Playwright config for NADOC end-to-end tests.
 *
 * Stands up its OWN throwaway servers (backend :8002, Vite :5175 proxying /api →
 * :8002) and tears them down — it never reuses or starves the user's dev servers
 * on :8000 / :5173.  Playwright auto-starts them.
 *
 * Usage:
 *   bun run test:e2e          # headless
 *   bun run test:e2e:ui       # Playwright UI mode
 *   bun run test:e2e:headed   # headed browser
 */
export default defineConfig({
  testDir: './e2e',
  globalTeardown: './e2e/global-teardown.js',  // remove __e2e__* workspace artifacts after the run
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,

  // Cleanup reporter runs last and removes screenshots/traces/.last-run even
  // after a failed or timed-out spec. Persistent HTML reports are intentionally
  // disabled by the repository's no-Playwright-artifacts policy.
  reporter: [['list'], ['./e2e/artifact-cleanup-reporter.js']],

  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: [
    {
      // Throwaway FastAPI backend on a DEDICATED port (never the user's :8000).
      // NADOC_DISABLE_SESSION_CACHE → it never autosaves .session/<doc> dirs into
      // the shared workspace/ (nor restores them), so a run leaves no session-doc
      // clutter that would be restored on the user's next dev-server restart.
      command: `uv run uvicorn backend.api.main:app --port ${BACKEND_PORT} --host 127.0.0.1`,
      cwd: REPO_ROOT,
      env: { NADOC_DISABLE_SESSION_CACHE: '1' },
      url: `http://127.0.0.1:${BACKEND_PORT}/docs`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      // Throwaway Vite — proxies /api → the throwaway backend via VITE_API_PORT.
      command: `npx vite --port ${FRONTEND_PORT} --host 127.0.0.1 --strictPort`,
      cwd: FRONTEND_DIR,
      env: { VITE_API_PORT: BACKEND_PORT },
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 20_000,
    },
  ],
})
