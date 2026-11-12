import { defineConfig } from '@playwright/test'
import { mkdtempSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import base from './playwright.config.js'

// Read-only example loading; no startup job precomputation or user workspace access.
process.env.NADOC_COMPILE_E2E_ROOT ??= mkdtempSync(path.join(os.tmpdir(), 'nadoc-compile-e2e-'))
const scratch = process.env.NADOC_COMPILE_E2E_ROOT
process.env.NADOC_WORKSPACE = scratch
// Playwright may recreate output parents after global teardown.
process.once('exit', () => rmSync(scratch, { recursive: true, force: true }))
export default defineConfig({
  ...base, workers: 1, globalTimeout: 240000,
  testMatch: ['compiled_presentation.spec.js', 'animation_trajectory_background.spec.js', 'keyframe_capture.spec.js'],
  globalTeardown: './e2e/compiled_presentation_teardown.js',
  outputDir: path.join(scratch, 'artifacts'),
  webServer: base.webServer.map((server, i) => i ? server : {
    ...server, command: `${server.command} --lifespan off`,
    env: { ...server.env, NADOC_WORKSPACE: scratch, NADOC_MD_PLAYBACK_CACHE_DIR: path.join(scratch, 'md-cache') },
  }),
})
