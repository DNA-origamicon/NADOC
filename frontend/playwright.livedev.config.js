import { defineConfig, devices } from '@playwright/test'

// TROUBLESHOOTING-ONLY config: run a spec against the USER'S ALREADY-RUNNING dev servers
// (backend :8000, Vite :5173) instead of standing up throwaway ones.
//
// Why this exists. playwright.config.js deliberately boots its own backend so a run can
// never starve the user's — and that is the right default. But a spec that needs a REAL
// finished simulation job (a written trajectory, a parsed PSF) cannot use it: a cold
// single-worker backend has to redo the multi-minute MDAnalysis work on an archived job's
// DCD, blocks its own event loop doing it, and the app just sits there showing
// "reconnecting…". The user's dev backend already has that work cached.
//
// Rules for any spec run under this config (see memory/feedback_no_live_server_mutation_
// for_verify.md):
//   • ALWAYS boot on a PINNED ?doc=… so the user's default document is untouched.
//   • READ-ONLY with respect to jobs: never submit, stop, delete or archive one.
//   • Never POST /design {} (that resets the active design) and never write a .nadoc.
//   • Ask before running it while the user has a simulation going — it competes for CPU.
//
// Usage:
//   npx playwright test --config playwright.livedev.config.js e2e/<spec>.spec.js
process.env.NADOC_E2E_API_BASE ??= 'http://localhost:8000'

export default defineConfig({
  testDir: './e2e',
  timeout: 420_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    // No actionTimeout default in Playwright means a click on a hidden element retries
    // FOREVER and eats the whole test budget with a useless "page closed" error. Cap it.
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
    // Software-WebGL readback of VoltronCoreArm can take minutes and distort the
    // timing being audited. The diagnostic's explicit evidence pass owns screenshots;
    // its timing pass disables even Playwright's automatic failure capture.
    screenshot: process.env.NADOC_AUDIT_SCREENSHOTS === '0' ? 'off' : 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // No webServer: both servers must already be up (just dev / just frontend).
})
