import { defineConfig } from '@playwright/test'
import isolated from './playwright.scrywrite-browser.config.js'
export default defineConfig({
  ...isolated,
  testDir: './e2e', testMatch: ['cluster_join*.spec.js', 't_junction_previews.spec.js'],
  outputDir: './test-results',
  reporter: [['list'], ['./e2e/artifact-cleanup-reporter.js']],
  use: { ...isolated.use, headless: true },
})
