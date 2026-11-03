import { defineConfig } from '@playwright/test'
import isolated from './playwright.scrywrite-browser.config.js'

// Independent document/workspace/ports, with cloud startup disabled by the base.
// The native viewer still uses the workstation's configured OpenXR runtime.
process.env.NADOC_WORKSPACE ??= process.env.SCRYWRITE_TEST_WORKSPACE
process.env.NADOC_E2E_FRONTEND_PORT ??= process.env.SCRYWRITE_FRONTEND_PORT || '5293'
process.env.NADOC_E2E_API_BASE ??= `http://127.0.0.1:${process.env.SCRYWRITE_BACKEND_PORT || '8193'}`
export default defineConfig({
  ...isolated,
  testDir: './e2e',
  globalTeardown: './e2e/global-teardown.js',
  testMatch: ['vr_sweep.spec.js', 'vr_sweep_edit.spec.js'],
  timeout: 360_000,
  globalTimeout: 420_000,
  use: { ...isolated.use, headless: true, trace: 'off' },
})
