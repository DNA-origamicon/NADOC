import { defineConfig, devices } from '@playwright/test'

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
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,

  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],

  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        executablePath: '/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe',
      },
    },
  ],

  webServer: [
    {
      // FastAPI backend
      command: `PATH=/home/joshua/.local/bin:$PATH uv run uvicorn backend.api.main:app --port 8000 --host 127.0.0.1`,
      cwd: '/home/joshua/NADOC',
      url: 'http://localhost:8000/docs',
      reuseExistingServer: true,
      timeout: 20_000,
    },
    {
      // Vite dev server
      command: 'npx vite --port 5173 --host 127.0.0.1',
      cwd: '/home/joshua/NADOC/frontend',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 20_000,
    },
  ],
})
