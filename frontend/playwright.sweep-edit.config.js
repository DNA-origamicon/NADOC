import { defineConfig } from '@playwright/test'
import isolated from './playwright.scrywrite-browser.config.js'
process.env.NADOC_WORKSPACE = process.env.SCRYWRITE_TEST_WORKSPACE
process.env.NADOC_E2E_FRONTEND_PORT = process.env.SCRYWRITE_FRONTEND_PORT || '5293'
export default defineConfig({
  ...isolated, testDir:'./e2e', testMatch:'sweep_edit.spec.js',
  globalTeardown:'./e2e/global-teardown.js',
  use:{...isolated.use, headless:true,video:{mode:'on',size:{width:1600,height:1000}}},
})
