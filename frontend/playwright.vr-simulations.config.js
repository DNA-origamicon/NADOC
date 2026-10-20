import config from './playwright.smoke.config.js'
export default {
 ...config,
 use: { ...config.use, headless: false }, globalTimeout: 0, timeout: 1_800_000,
 // Retain opt-in backend stage timings alongside the native/browser traces.
 webServer: config.webServer.map((server, index) => index === 0 && process.env.NADOC_VR_VIEW_PIPELINE === '1'
  ? { ...server, stdout: 'pipe' } : server),
}
