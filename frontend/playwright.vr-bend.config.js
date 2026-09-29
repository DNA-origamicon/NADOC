import { defineConfig } from '@playwright/test'
import smoke from './playwright.smoke.config.js'

// The isolated controller tour needs API routes, not startup cloud/scheduler
// probes or job recovery. Keep those unrelated services out of timed VR input.
export default defineConfig({
  ...smoke,
  webServer: smoke.webServer.map((server, index) => index === 0
    ? { ...server, command: server.command + ' --lifespan off' }
    : server),
})
