import { defineConfig, devices } from '@playwright/test'
export default defineConfig({ testDir: './e2e', testMatch: 'prepared_host.spec.js', timeout: 60000,
  fullyParallel: false, reporter: [['list']], use: { headless: true },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'chromium-lan-http', use: { ...devices['Desktop Chrome'], launchOptions: {
      args: ['--host-resolver-rules=MAP nadoc-lan.test 127.0.0.1', '--no-proxy-server'],
    } } },
  ] })
