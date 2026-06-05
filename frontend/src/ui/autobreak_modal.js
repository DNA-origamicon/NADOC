// Autobreak modal — the routing dialog that lets the user pick a staple-breaking
// algorithm (basic nick planner / Aksel thermodynamic optimizer / advanced) and
// run Score / Preview / Run Autobreak. Extracted verbatim from main.js (carve-up #66).
import { showToast }                      from './toast.js'
import { showOpProgress, hideOpProgress } from './op_progress.js'
import { createModal }                    from './primitives/modal.js'
import { createButton }                   from './primitives/button.js'
import { formatScoreSummary, formatGraphSummary } from '../scene/aksel_format.js'

// Pure core: parse the four Aksel option inputs (raw string values, or undefined
// when the element is absent) → the clamped options object posted to the backend.
// Verbatim-equivalent to the original `_readAkselOptions` DOM reader: a missing or
// non-finite value falls back to its default (21 / 60 / 3 / 0).
export function readAkselOptions(raw = {}) {
  const minNt     = Number.parseInt(raw.minNt     ?? '21', 10)
  const maxNt     = Number.parseInt(raw.maxNt     ?? '60', 10)
  const kPaths    = Number.parseInt(raw.kPaths    ?? '3',  10)
  const pathIndex = Number.parseInt(raw.pathIndex ?? '0',  10)
  return {
    min_staple_nt: Number.isFinite(minNt)     ? minNt     : 21,
    max_staple_nt: Number.isFinite(maxNt)     ? maxNt     : 60,
    k_paths:       Number.isFinite(kPaths)    ? kPaths    : 3,
    path_index:    Number.isFinite(pathIndex) ? pathIndex : 0,
  }
}

export function initAutobreakModal({ store, api }) {
  let _abModalCtrl = null
  let _abBody      = null
  let _abReport    = null

  let _animTimer = null
  function _startIndeterminate() {
    const fill = document.getElementById('op-progress-fill')
    if (!fill) return
    let pct = 0
    _animTimer = setInterval(() => {
      pct = (pct + 7) % 90
      fill.style.width = pct + '%'
    }, 400)
  }
  function _stopIndeterminate() {
    if (_animTimer) { clearInterval(_animTimer); _animTimer = null }
    const fill = document.getElementById('op-progress-fill')
    if (fill) fill.style.width = '100%'
  }

  function _readOpts() {
    return readAkselOptions({
      minNt:     _abBody?.querySelector('#ab-min-nt')?.value,
      maxNt:     _abBody?.querySelector('#ab-max-nt')?.value,
      kPaths:    _abBody?.querySelector('#ab-k-paths')?.value,
      pathIndex: _abBody?.querySelector('#ab-path-index')?.value,
    })
  }

  function _setAkselReport(lines, severity = 'normal') {
    if (!_abReport) return
    _abReport.style.display = 'block'
    _abReport.style.color = severity === 'error'
      ? 'var(--color-danger, #ff6b6b)'
      : 'var(--color-text-muted)'
    _abReport.textContent = lines.filter(Boolean).join('\n')
  }

  async function _scoreAksel3d() {
    const opts = _readOpts()
    _setAkselReport(['Scoring current staples…'])
    const report = await api.scoreStaples(opts)
    if (!report) {
      _setAkselReport(['Score failed: ' + (store.getState().lastError?.message ?? 'unknown error')], 'error')
      return
    }
    _setAkselReport(['Current route', ...formatScoreSummary(report)])
  }

  async function _previewAksel3d() {
    const opts = _readOpts()
    _setAkselReport(['Building precursor graph…'])
    showOpProgress('Aksel preview', 'Scoring candidate breaks…')
    const report = await api.buildStaplePrecursorGraphs(opts)
    hideOpProgress()
    if (!report) {
      _setAkselReport(['Preview failed: ' + (store.getState().lastError?.message ?? 'unknown error')], 'error')
      return
    }
    _setAkselReport(['Precursor graph', ...formatGraphSummary(report)])
  }

  async function _runAutoBreak3d() {
    _abModalCtrl?.close()
    const algo = _abBody?.querySelector('input[name="ab-algo"]:checked')?.value || 'basic'
    const isAksel = algo === 'aksel' || algo === 'advanced'
    showOpProgress('Autobreak', isAksel ? 'Running Aksel optimizer…' : 'Running nick planner…')
    if (isAksel) _startIndeterminate()
    const result = isAksel
      ? await api.addAutoRouteAksel(_readOpts())
      : await api.addAutoBreak({ algorithm: algo })
    if (isAksel) _stopIndeterminate()
    hideOpProgress()
    if (!result) {
      showToast('Autobreak failed: ' + (store.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
    } else {
      const akselRoute = result.aksel_route
      const aksel = akselRoute?.aksel_break ?? result.aksel_break
      if (aksel) {
        const placed = akselRoute?.auto_crossover?.placed
        const prefix = placed == null ? 'Aksel autobreak' : `Aksel route (${placed} crossovers)`
        showToast(`${prefix} complete: ${aksel.new_staple_count ?? 0} staples, ${aksel.length_violation_count ?? 0} length violations.`)
      } else {
        showToast('Autobreak complete.')
      }
    }
  }

  function _buildOnce() {
    if (_abModalCtrl) return
    _abBody = document.getElementById('autobreak-modal-body')
    if (!_abBody) return
    _abBody.removeAttribute('hidden')
    _abReport = _abBody.querySelector('#ab-aksel-report')
    const cancelBtn = createButton({ label: 'Cancel', variant: 'default', onClick: () => _abModalCtrl.close() })
    const scoreBtn  = createButton({ label: 'Score', variant: 'default', onClick: _scoreAksel3d })
    const graphBtn  = createButton({ label: 'Preview', variant: 'default', onClick: _previewAksel3d })
    const runBtn    = createButton({ label: 'Run Autobreak', variant: 'primary', onClick: _runAutoBreak3d })
    _abModalCtrl = createModal({
      title: 'Autobreak — choose algorithm',
      size: 'md',
      body: _abBody,
      actions: [cancelBtn, scoreBtn, graphBtn, runBtn],
    })
  }

  function openModal() {
    if (!store.getState().currentDesign?.helices?.length) {
      showToast('No design loaded.', { severity: 'error' }); return
    }
    _buildOnce()
    _abModalCtrl?.open()
  }

  document.getElementById('menu-routing-autobreak')?.addEventListener('click', openModal)

  return { openModal }
}
