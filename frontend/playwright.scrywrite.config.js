import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './scrywrite',
  testIgnore: 'browser_transaction.spec.js',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    trace: 'off',
  },
})
