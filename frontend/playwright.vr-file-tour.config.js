import { defineConfig } from '@playwright/test'
import isolated from './playwright.scrywrite-browser.config.js'
process.env.NADOC_WORKSPACE = process.env.SCRYWRITE_TEST_WORKSPACE
process.env.NADOC_E2E_FRONTEND_PORT = process.env.SCRYWRITE_FRONTEND_PORT || '5293'
export default defineConfig({
  ...isolated, testDir: './e2e', testMatch: 'vr_file_tour.spec.js',
  globalTeardown: './e2e/global-teardown.js', timeout: 600_000,
  use: { ...isolated.use, headless: false, trace: 'retain-on-failure' },
})
