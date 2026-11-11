import { defineConfig } from '@playwright/test'
import path from 'node:path'
import base from './playwright.config.js'
if (!process.env.NADOC_WORKSPACE) throw new Error('NAMD submodel review requires an isolated workspace')
export default defineConfig({
  ...base,
  workers: 1,
  webServer: base.webServer.map((server, i) => i ? server : {
    ...server,
    command: server.command + ' --lifespan off',
    env: { ...server.env, NADOC_MD_PLAYBACK_CACHE_DIR: path.join(process.env.NADOC_WORKSPACE, 'playback-cache') },
  }),
})
