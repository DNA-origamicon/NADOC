import { defineConfig } from '@playwright/test'
import isolated from './playwright.scrywrite-browser.config.js'

// Sweep authoring uses a disposable workspace and no cloud startup hooks.
export default defineConfig({
  ...isolated, testDir: './e2e', testMatch: 'sweep*.spec.js',
  use: { ...isolated.use, headless: true },
})
