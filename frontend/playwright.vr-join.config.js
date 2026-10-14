import { defineConfig } from '@playwright/test'
import isolated from './playwright.scrywrite-browser.config.js'

process.env.NADOC_WORKSPACE = process.env.SCRYWRITE_TEST_WORKSPACE
process.env.NADOC_E2E_FRONTEND_PORT = process.env.SCRYWRITE_FRONTEND_PORT || '5293'
process.env.NADOC_E2E_API_BASE = `http://127.0.0.1:${process.env.SCRYWRITE_BACKEND_PORT || '8193'}`

export default defineConfig({
  ...isolated,
  testDir: './e2e', testMatch: ['vr_join.spec.js', 'vr_tours.spec.js'],
  globalTeardown: './e2e/global-teardown.js',
  use: { ...isolated.use, headless: true },
})
