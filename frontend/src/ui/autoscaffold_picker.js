// Autoscaffold picker — the routing dialog that lets the user pick a scaffold
// routing strategy (seamed / seamless) and run it. There is no separate "matched"
// mode: seamed routing tries matched ends first and falls back on its own
// (backend/core/seamed_router.py:1275-1289), which is what AUTOSCAFFOLD_MODES.seamed
// means by "matched ends when feasible".
// Extracted verbatim from main.js (carve-up #65).
import { showToast }                    from './toast.js'
import { showOpProgress, hideOpProgress } from './op_progress.js'

// Pure core: map the picked radio value → progress copy + api method + fail label.
// Verbatim-equivalent to the original if/else chain; unknown mode → seamed (the
// original `else` branch).
export const AUTOSCAFFOLD_MODES = {
  seamless: {
    title: 'Seamless Scaffold',
    message: 'Routing seamless scaffold strand…',
    apiMethod: 'autoScaffoldSeamless',
    failLabel: 'Seamless scaffold failed',
  },
  seamed: {
    title: 'Autoscaffold (Seamed)',
    message: 'Routing scaffold with seam crossovers (matched ends when feasible)…',
    apiMethod: 'autoScaffoldSeamed',
    failLabel: 'Seamed autoscaffold failed',
  },
}

export function autoscaffoldModeConfig(mode) {
  return AUTOSCAFFOLD_MODES[mode] || AUTOSCAFFOLD_MODES.seamed
}

export function initAutoscaffoldPicker({ store, api, setRoutingCheck }) {
  const modal     = document.getElementById('autoscaffold-modal')
  const btnRun    = document.getElementById('as-run')
  const btnCancel = document.getElementById('as-cancel')

  async function runAutoscaffold() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
    const mode = modal.querySelector('input[name="as-mode"]:checked')?.value || 'seamed'
    modal.classList.remove('visible')
    const cfg = autoscaffoldModeConfig(mode)
    showOpProgress(cfg.title, cfg.message)
    const ok = await api[cfg.apiMethod]()
    hideOpProgress()
    if (!ok) {
      showToast(cfg.failLabel + ': ' + (store.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
    } else {
      setRoutingCheck('scaffoldEnds', true)
    }
  }

  document.getElementById('menu-routing-scaffold-ends')?.addEventListener('click', () => {
    if (!store.getState().currentDesign) { showToast('No design loaded.', { severity: 'error' }); return }
    modal.classList.add('visible')
  })
  btnRun?.addEventListener('click', runAutoscaffold)
  btnCancel?.addEventListener('click', () => modal.classList.remove('visible'))
  modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible') })

  return { runAutoscaffold }
}
