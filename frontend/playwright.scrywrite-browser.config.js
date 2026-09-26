import { defineConfig, devices } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// Independent ports, backend, workspace, and artifacts: safe alongside CPD tests.
// Disable lifespan: browser UI tests must not autoconnect cloud providers or reap jobs.
const root = path.resolve(import.meta.dirname, '..')
const backendPort = process.env.SCRYWRITE_BACKEND_PORT || '8193'
const frontendPort = process.env.SCRYWRITE_FRONTEND_PORT || '5293'
process.env.SCRYWRITE_TEST_WORKSPACE ??= mkdtempSync(path.join(os.tmpdir(), 'nadoc-scry-browser-'))
const workspace = process.env.SCRYWRITE_TEST_WORKSPACE
export default defineConfig({
  testDir: './scrywrite',
  testMatch: 'browser_transaction.spec.js',
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: path.join(workspace, 'artifacts'),
  use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${frontendPort}`, trace: 'retain-on-failure' },
  webServer: [
    { command: `${root}/.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port ${backendPort} --lifespan off`,
      cwd: root, url: `http://127.0.0.1:${backendPort}/docs`, reuseExistingServer: false, timeout: 60000,
      env: { NADOC_WORKSPACE: workspace, NADOC_DISABLE_SESSION_CACHE: '1', NADOC_MD_PLAYBACK_CACHE_DIR: path.join(workspace, 'md-cache') } },
    { command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      cwd: import.meta.dirname, url: `http://127.0.0.1:${frontendPort}`, reuseExistingServer: false, timeout: 30000,
      env: { NADOC_SHARE_AUTOSTART: '0', VITE_API_PORT: backendPort } },
  ],
})
