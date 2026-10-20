// Explicit test config only. Ordinary vite.config.js never imports this module.
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ordinary from '../vite.config.js'
import { preparedSharePlugin } from '../prepared_share_server.js'

const sweepEditor = fileURLToPath(new URL('../src/app/sweep_history_editor.js', import.meta.url))
const editor = fileURLToPath(new URL('../src/app/feature_editor.js', import.meta.url))
export function historyGatePlugin() {
  return {
    name: 's03-history-test-gates', enforce: 'pre',
    transform(source, id) {
      const target = id.split('?')[0]
      if (target !== editor && target !== sweepEditor) return null
      const result = source
      if (target === editor) {
        // Bend/Twist gates are enabled in production (October 18, 2026); refuse
        // drift rather than silently exercising the legacy editor.
        for (const name of ['ISOLATED_DEFORMATION_HISTORY_ENABLED', 'ISOLATED_DEFORMATION_CREATION_ENABLED']) {
          if (result.split(`export const ${name} = true`).length !== 2) throw new Error(`Missing unique enabled gate: ${name}`)
        }
        return null
      }
      if (result.split('export const SWEEP_HISTORY_EDITOR_ENABLED = true').length !== 2)
        throw new Error('Missing unique enabled gate: SWEEP_HISTORY_EDITOR_ENABLED')
      return null
    },
  }
}

export default () => {
  const root = process.env.NADOC_HISTORY_E2E_ROOT
  if (!root || !path.isAbsolute(root)) throw new Error('Use scripts/run_deformation_history_e2e.py')
  return { ...ordinary, cacheDir: path.join(root, 'vite-cache'),
    // Keep the real no-host protocol (background links return pending), without
    // reading ordinary credentials or allowing this test to launch a share host.
    plugins: [historyGatePlugin(), preparedSharePlugin({
      autoStart: false, publicUrl: '', controlFile: path.join(root, 'share-control.json'),
      launch: async () => { throw new Error('Sharing host launch disabled in history harness') },
    })] }
}
