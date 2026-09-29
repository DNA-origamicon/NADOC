import config from './playwright.smoke.config.js'
export default { ...config, use: { ...config.use, headless: false }, globalTimeout: 0, timeout: 1_800_000 }
