// Autoscaffold picker — the routing dialog that lets the user pick a scaffold
// routing strategy (seamed / seamless / matched / advanced-*) and run it.
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
  matched: {
    title: 'Matched Ends',
    message: 'Routing scaffold with matched ends for end-to-end polymerization…',
    apiMethod: 'autoScaffoldMatched',
    failLabel: 'Matched-ends scaffold failed',
  },
  'advanced-seamed': {
    title: 'Advanced Seam Routing',
    message: 'Routing scaffold with experimental seam planner…',
    apiMethod: 'autoScaffoldAdvancedSeamed',
    failLabel: 'Advanced seam routing failed',
  },
  'advanced-seamless': {
    title: 'Advanced Seamless Routing',
    message: 'Routing scaffold with experimental seamless planner…',
    apiMethod: 'autoScaffoldAdvancedSeamless',
    failLabel: 'Advanced seamless routing failed',
  },
  seamed: {
    title: 'Autoscaffold (Seamed)',
    message: 'Routing scaffold strand with seam crossovers…',
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
