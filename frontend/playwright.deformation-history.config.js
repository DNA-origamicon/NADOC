import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.dirname(fileURLToPath(import.meta.url))
const root = process.env.NADOC_HISTORY_E2E_ROOT
if (!root || !path.isAbsolute(root)) throw new Error('Use scripts/run_deformation_history_e2e.py')
export default defineConfig({
  testDir: './e2e', testMatch: process.env.NADOC_HISTORY_E2E_SEALED === '1' ? ['sealed_history.spec.js'] : ['deformation_history.spec.js', 'bend_release.spec.js', 'sweep_history.spec.js', 'extrude_history.spec.js', 'routing_history.spec.js', 'bend_preview_latency.spec.js'],
  grep: process.env.NADOC_HISTORY_E2E_GREP ? new RegExp(process.env.NADOC_HISTORY_E2E_GREP) : undefined,
  workers: 1, fullyParallel: false, retries: 0, timeout: 60000,
  outputDir: path.join(root, 'playwright'), reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5177', headless: true, screenshot: 'off', trace: 'off', video: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: 'uv run --no-sync uvicorn tests.deformation_history_app:create_app --factory --host 127.0.0.1 --port 8004',
      cwd: path.resolve(frontend, '..'), url: 'http://127.0.0.1:8004/docs', reuseExistingServer: false, timeout: 30000 },
    { command: 'node node_modules/vite/bin/vite.js --configLoader runner --config e2e/deformation_history_vite.js --host 127.0.0.1 --port 5177 --strictPort',
      cwd: frontend, env: { VITE_API_PORT: '8004', NADOC_SHARE_AUTOSTART: '0' },
      url: 'http://127.0.0.1:5177', reuseExistingServer: false, timeout: 30000 },
  ],
})
