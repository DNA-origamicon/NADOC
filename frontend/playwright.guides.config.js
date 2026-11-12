import { defineConfig } from '@playwright/test'
import path from 'node:path'

const root = process.env.NADOC_HISTORY_E2E_ROOT
if (!root || !process.env.NADOC_GUIDE_OUTPUT) throw new Error('Use python -m scripts.generate_feature_guide')
export default defineConfig({
  testDir: './guides', testMatch: 'extrude.spec.js', workers: 1, retries: 0,
  timeout: 900000, globalTimeout: 960000, expect: { timeout: 20000 },
  reporter: 'list', outputDir: path.join(root, 'playwright'),
  use: { baseURL: 'http://127.0.0.1:5189', viewport: { width: 1920, height: 1080 },
    headless: true, trace: 'off', video: 'off', screenshot: 'off' },
  webServer: [
    { command: '.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8019 --lifespan off',
      cwd: path.resolve(import.meta.dirname, '..'),
      url: 'http://127.0.0.1:8019/docs', reuseExistingServer: false, timeout: 60000 },
    { command: 'node node_modules/vite/bin/vite.js --configLoader runner --config e2e/smoke_vite.js --host 127.0.0.1 --port 5189 --strictPort',
      cwd: import.meta.dirname, env: { VITE_API_PORT: '8019', NADOC_SHARE_AUTOSTART: '0' },
      url: 'http://127.0.0.1:5189', reuseExistingServer: false, timeout: 30000 },
  ],
})
