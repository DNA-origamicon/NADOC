import { defineConfig } from '@playwright/test'
import { mkdtempSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import base from './playwright.config.js'

process.env.NADOC_POINTER_E2E_ROOT ??= mkdtempSync(path.join(os.tmpdir(), 'nadoc-pointer-e2e-'))
const scratch = process.env.NADOC_POINTER_E2E_ROOT
process.env.NADOC_WORKSPACE = scratch
process.once('exit', () => rmSync(scratch, { recursive: true, force: true }))
console.log(`Pointer isolated workspace: ${scratch}`)
export default defineConfig({
  ...base, workers: 1, timeout: 120000, globalTimeout: 180000,
  testMatch: 'dietz_pointer.spec.js', reporter: [['list']],
  outputDir: '../.development-artifacts/pointer-reconstruction-20261123/playwright-output',
  webServer: base.webServer.map((server, i) => i ? server : {
    ...server, command: `${server.command} --lifespan off`,
    env: { ...server.env, NADOC_WORKSPACE: scratch,
      NADOC_MD_PLAYBACK_CACHE_DIR: path.join(scratch, 'md-cache') },
  }),
})
