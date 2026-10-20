// Smoke-only cache isolation; production plugins and feature gates are unchanged.
import path from 'node:path'
import ordinary from '../vite.config.js'

export default () => {
  const root = process.env.NADOC_SMOKE_E2E_ROOT
  if (!root || !path.isAbsolute(root)) throw new Error('Use the isolated --smoke launcher')
  return { ...ordinary, cacheDir: path.join(root, 'vite-cache') }
}
