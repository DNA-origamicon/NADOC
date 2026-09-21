import { defineConfig, devices } from '@playwright/test'
export default defineConfig({ testDir: './e2e', testMatch: 'internet_viewer.spec.js', timeout: 60000,
  fullyParallel: false, reporter: [['list']], use: { ...devices['Desktop Chrome'], headless: true,
    // Only the isolated test fixture has a self-signed certificate. Real sharing
    // uses the provider's publicly trusted certificate with no browser override.
    ignoreHTTPSErrors: true,
  } })
