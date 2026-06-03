import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Resolve server CWDs relative to this config file so the e2e/boot gate works on
// any checkout (previously hardcoded to one machine's absolute path, which made
// webServer auto-start fail with spawn ENOENT elsewhere).
const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')

/**
 * Playwright config for NADOC end-to-end tests.
 *
 * Targets the Vite dev server on port 5173 (proxies /api → FastAPI on 8000).
 *
 * Usage:
 *   # Ensure both servers are running first:
 *   #   Terminal 1: just dev           (FastAPI on :8000)
 *   #   Terminal 2: just frontend      (Vite on :5173)
 *
 *   bun run test:e2e          # headless
 *   bun run test:e2e:ui       # Playwright UI mode
 *   bun run test:e2e:headed   # headed browser
 *
 * webServer entries auto-start the servers when not already running.
 */
export default defineConfig({
  testDir: './e2e',
  globalTeardown: './e2e/global-teardown.js',  // remove __e2e__* workspace artifacts after the run
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,

  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],

  use: {
    baseURL: 'http://127.0.0.1:5173',
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
      // FastAPI backend — use 127.0.0.1 explicitly; localhost may resolve to ::1
      command: 'uv run uvicorn backend.api.main:app --port 8000 --host 127.0.0.1',
      cwd: REPO_ROOT,
      url: 'http://127.0.0.1:8000/docs',
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Vite dev server — use 127.0.0.1 explicitly
      command: 'npx vite --port 5173 --host 127.0.0.1',
      cwd: FRONTEND_DIR,
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: true,
      timeout: 20_000,
    },
  ],
})
