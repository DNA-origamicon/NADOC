import { defineConfig } from '@playwright/test'
import isolated from './playwright.vr-join.config.js'
export default defineConfig({ ...isolated, testMatch: ['oxdna_strain_real.spec.js'],
  timeout: 240000, globalTimeout: 1500000,
  outputDir: '../.development-artifacts/oxdna-strain-review/app',
  webServer: isolated.webServer.map((server, i) => i === 0 ? { ...server, env: { ...server.env, NADOC_PRECOMPUTE_WORKER: '1' } } : server),
  use: { ...isolated.use, launchOptions: { args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=gl'] }, viewport: { width: 1500, height: 1000 }, trace: 'off' },
})
