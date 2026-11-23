import { defineConfig } from '@playwright/test'
import isolated from './playwright.multi-overlay.config.js'
export default defineConfig({ ...isolated, testMatch: ['extension_slabs.spec.js'],
  outputDir: '../.development-artifacts/extension-slabs/app', timeout: 180000 })
