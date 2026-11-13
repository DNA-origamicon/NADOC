import { defineConfig } from '@playwright/test'
import path from 'node:path'
import isolated from './playwright.vr-sweep.config.js'

export default defineConfig({
  ...isolated,
  testMatch: ['multi_overlay_simulation.spec.js'],
  timeout: 180000,
  globalTimeout: 360000,
  outputDir: path.resolve(import.meta.dirname, '../.development-artifacts/multi-overlay-app'),
  use: { ...isolated.use, viewport: { width: 1400, height: 1000 }, trace: 'retain-on-failure' },
})
