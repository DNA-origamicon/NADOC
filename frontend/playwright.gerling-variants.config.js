import path from 'node:path'
import config from './playwright.smoke.config.js'

const workspace = process.env.NADOC_WORKSPACE
if (!workspace || !path.isAbsolute(workspace)) throw new Error('Set an isolated Archive NADOC_WORKSPACE')

export default {
  ...config,
  webServer: config.webServer.map((server, i) => i === 0 ? {
    ...server,
    command: server.command + ' --lifespan off',
    env: { ...server.env, NADOC_WORKSPACE: workspace,
      NADOC_MD_PLAYBACK_CACHE_DIR: path.join(workspace, 'playwright_tests/__e2e__md-playback') },
  } : server),
}
