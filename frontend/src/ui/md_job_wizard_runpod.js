/**
 * Job Wizard step 1 — renting a GPU on RunPod.
 *
 * The RunPod counterpart of `md_job_wizard_resources.js`, and deliberately the same shape: a
 * block under the target card that arrives ALREADY SIZED for the run being designed, and
 * re-sizes itself when the run changes on a later tab.
 *
 * Until now this card said "RunPod setup lives in the Clusters card for now" and blocked Next.
 * Everything RunPod-facing lived in the old Clusters card, which is the wrong place twice
 * over: the decision that costs money (which card, how long, how much) is made here, and the
 * numbers that inform it depend on protocol settings two tabs away.
 *
 * WHY THE NUMBERS ARE LOAD-BEARING: a pod bills from creation, not from first useful step. So
 * this block shows, before anything is rented — what the whole plan costs on each available
 * card, how long it takes, what it writes and whether that fits, what the upload costs before
 * NAMD starts, and whether any pod is billing right now.
 *
 * ONE round trip serves all of it (`POST /runpod/job-preview`): ranked cards, storage,
 * balance, live pods AND the pre-flight. That is why this does not mount `initRunpodStatus` —
 * that factory owns its own `/runpod/preflight` call, which would fetch the same live stock a
 * second time and give the gate two sources of truth. Its PURE renderers are reused instead.
 *
 * Pure shaping (the estimate table, the budget verdict, the gate) lives in
 * `md_job_wizard_runpod_model.js`; the row markup in `runpod_gpu_options.js`. This factory
 * owns DOM and fetch only.
 */

import { el } from './primitives/dom.js'
import { initRunpodSetup, volumeOptions } from './runpod_setup.js'
import { renderPreflightRows, runpodBlockReason, runpodChipState } from './runpod_status.js'
import { jobOptionsHeader, renderJobOptionRows } from './runpod_gpu_options.js'
import {
  DEFAULT_BUDGET_USD, budgetHours, budgetState, estimateRows, formatHours, formatUsd,
  runpodEstimateKey, runpodReadiness, selectedRow, storageRows,
} from './md_job_wizard_runpod_model.js'

const _esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

const _INPUT_CSS =
  'background:#0d1117;border:1px solid #30363d;color:#c9d1d9;'
  + 'border-radius:3px;padding:3px 5px;font-size:11px'

/**
 * @param {object}   deps
 * @param {Element}  deps.mount           where the block renders (inside the RunPod card)
 * @param {Function} deps.getJobPreview   body => Promise<preview>  (POST /runpod/job-preview)
 * @param {Function} deps.getVolumes      () => Promise<{volumes}>  (GET /runpod/volumes)
 * @param {Function} deps.setVolume       id => Promise<any>        (POST /runpod/volume)
 * @param {Function} deps.getPlanShape    () => shape — `runpodPlanShape(plan)`; the run being
 *   designed, re-read on every refresh so the estimate follows the later tabs.
 * @param {Function} [deps.onChange]      fired when anything that affects the payload or the
 *   Next gate moves
 * @param {Function} [deps.readOnly]      () => boolean — viewing a job that already exists
 * @param {Function} [deps.getRecorded]   () => {gpuKey, budgetUsd, volumeId, podId}
 * @param {Function} [deps.setup]         injectable `initRunpodSetup` (tests)
 */
export function initWizardRunpod({
  mount, getJobPreview, getVolumes, setVolume, getPlanShape = () => null,
  onChange = () => {}, readOnly = () => false, getRecorded = () => null,
  setup = initRunpodSetup,
} = {}) {
  const _ro = () => !!readOnly()
  let _preview = null
  let _busy = false
  let _error = ''
  let _key = ''
  let _gpuKey = null
  let _budget = DEFAULT_BUDGET_USD
  let _volumeId = null
  let _volumes = []
  let _setupMounted = false
  let _setupHost = null

  const _connected = () => !!_preview?.connected

  /**
   * Re-price the run. Cheap to call: no-ops unless something that moves an hour, a dollar or
   * a byte actually changed — the same guard the Alpine block uses, and for the same reason.
   * The atom estimate behind this builds the design's heavy-atom model on a cold cache.
   */
  async function refresh({ force = false } = {}) {
    if (_ro()) { paint(); return }
    const shape = getPlanShape()
    // The connection state is deliberately NOT in this key. It is only known AFTER the first
    // response, so folding it in makes the key computed before a fetch differ from the one
    // computed after it — and the card re-fetches on every single call. Connecting already
    // forces a refresh through `initRunpodSetup`'s `onConnected`, so nothing is missed.
    const key = runpodEstimateKey(shape)
    if (!force && key === _key && (_preview || _busy)) return
    _key = key
    _busy = true
    _error = ''
    paint()
    try {
      _preview = await getJobPreview?.({ ...(shape || {}), budget_usd: _budget })
      if (!_preview) _error = 'Could not price this run on RunPod.'
      else if (_preview.sized === false) _error = _preview.reason || 'Not sized.'
      else _adoptDefaults()
    } catch (err) {
      _preview = null
      _error = `Could not price this run: ${err?.message || err}`
    } finally {
      _busy = false
      paint()
      onChange()
    }
  }

  /** Preselect the backend's best-value card — but never overwrite a choice already made. */
  function _adoptDefaults() {
    const rows = _preview?.gpus || []
    if (!_gpuKey || !rows.some(r => r.key === _gpuKey)) _gpuKey = rows[0]?.key || null
    if (!_volumeId) _volumeId = _preview?.volume?.id || null
  }

  async function _loadVolumes() {
    if (_ro() || !_connected() || _volumes.length) return
    try {
      const r = await getVolumes?.()
      _volumes = r?.volumes || []
    } catch {
      _volumes = []
    }
    paint()
  }

  // ── rendering ────────────────────────────────────────────────────────────
  function _row(label, value, note) {
    return (
      '<div style="display:flex;justify-content:space-between;gap:12px;padding:1px 0">'
      + `<span style="color:#6e7681">${_esc(label)}</span>`
      + `<span style="color:#c9d1d9;text-align:right">${_esc(value)}`
      + (note ? `<br><span style="color:#6e7681;font-size:9px">${_esc(note)}</span>` : '')
      + '</span></div>'
    )
  }

  function _sectionTitle(text) {
    return `<div style="font-size:11px;color:#c9d1d9;font-weight:600;margin:12px 0 5px">`
      + `${_esc(text)}</div>`
  }

  function paint() {
    if (!mount) return
    if (_ro()) { _paintRecorded(); return }

    const budget = budgetState({
      budget: _preview?.budget, balance: _preview?.balance,
      livePods: _preview?.live_pods || [],
    })
    const row = selectedRow(_preview, _gpuKey)
    const shape = getPlanShape()

    mount.innerHTML =
      '<div id="wiz-runpod-setup" style="margin-bottom:8px"></div>'
      + _chipHtml()
      + _gpuHtml(budget)
      + _estimateHtml(row, shape)
      + _storageHtml()
      + _budgetHtml(budget, row)
    _setupHost = mount.querySelector('#wiz-runpod-setup')
    _ensureSetup()
    _wire()
  }

  function _chipHtml() {
    const pre = _preview?.preflight
    const chip = runpodChipState(pre)
    const colour = chip.state === 'connected' ? '#3fb950'
      : chip.state === 'warn' ? '#d29922' : '#f85149'
    return (
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
      + `<span style="font-size:11px;color:${colour}">● ${_esc(chip.label)}</span>`
      + '<button type="button" id="wiz-runpod-recheck" style="font-size:10px;padding:2px 6px;'
      + 'background:#161b22;border:1px solid #30363d;color:#8b949e;border-radius:3px;'
      + `cursor:pointer">${_busy ? 'checking…' : 'Re-check prices & stock'}</button></div>`
      + (pre && !pre.ok
        ? '<div style="font-size:10px;display:flex;flex-direction:column;gap:2px;'
          + `margin-bottom:6px">${renderPreflightRows(pre)}</div>`
        : '')
    )
  }

  function _gpuHtml(budget) {
    if (_busy && !_preview) {
      return _sectionTitle('Available GPUs')
        + '<div style="font-size:11px;color:#8b949e;padding:4px 0">'
        + 'Checking what is available and what this run would cost…</div>'
    }
    if (_error || !_preview?.gpus?.length) {
      return _sectionTitle('Available GPUs')
        + `<div style="font-size:11px;color:#d29922;padding:4px 0">${
          _esc(_error || 'No compatible GPU is available right now.')}</div>`
    }
    return _sectionTitle('Available GPUs')
      + '<div style="border:1px solid #30363d;border-radius:5px;overflow:hidden">'
      + jobOptionsHeader()
      + '<div style="max-height:190px;overflow-y:auto;display:flex;flex-direction:column;'
      + `gap:1px;font-size:10px;padding:2px">${
        renderJobOptionRows(_preview.gpus, _gpuKey, { budgetUsd: budget.cap })}</div></div>`
      + (_preview.note
        ? `<div style="font-size:9px;color:#6e7681;margin-top:5px">${_esc(_preview.note)}</div>`
        : '')
  }

  function _estimateHtml(row, shape) {
    if (!row) return ''
    const rows = estimateRows(row, shape).map(([k, v, n]) => _row(k, v, n)).join('')
    const sized = _preview?.n_atoms
      ? `${Number(_preview.n_atoms).toLocaleString()} atoms${
        _preview.n_atoms_source === 'estimated' ? ' (estimated — not solvated yet)' : ''}`
      : ''
    return _sectionTitle(`This run on a ${row.label}`)
      + `<div style="font-size:11px">${rows}${sized ? _row('System size', sized, '') : ''}</div>`
      + '<div style="font-size:10px;color:#6e7681;margin-top:6px;line-height:1.5">'
      + 'Estimated from a conservative per-architecture rate, then refined by a benchmark on '
      + 'the pod you actually get — the same card model can vary ~1.5× between pods.</div>'
  }

  function _storageHtml() {
    const st = _preview?.storage
    if (!st) return ''
    const opts = volumeOptions(_volumes)
      .map(o => `<option value="${_esc(o.value)}"${o.value === _volumeId ? ' selected' : ''}>`
        + `${_esc(o.label)}</option>`).join('')
    return _sectionTitle('Storage')
      + (opts
        ? '<div style="margin-bottom:6px"><div style="color:#8b949e;font-size:11px;'
          + 'margin-bottom:2px">Network volume</div>'
          + `<select id="wiz-runpod-volume" style="${_INPUT_CSS};width:100%">`
          + `<option value="">Choose a volume…</option>${opts}</select></div>`
        : '')
      + `<div style="font-size:11px">${
        storageRows(st).map(([k, v, n]) => _row(k, v, n)).join('')}</div>`
      + (st.warn
        ? '<div style="font-size:11px;color:#d29922;background:rgba(210,153,34,.1);'
          + 'border:1px solid rgba(210,153,34,.35);border-radius:4px;padding:6px 8px;'
          + `margin-top:6px">⚠ ${_esc(st.reason)}</div>`
        : '')
  }

  function _budgetHtml(budget, row) {
    const buys = budgetHours(_budget, row?.usd_per_hour)
    return _sectionTitle('Spending cap')
      + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
      + `<span style="color:#8b949e;font-size:11px">Stop this pod after</span>`
      + `<input id="wiz-runpod-budget" type="number" min="0" step="1" value="${_budget}"`
      + ` style="${_INPUT_CSS};width:80px">`
      + '<span style="color:#8b949e;font-size:11px">USD</span>'
      + (buys ? `<span style="color:#6e7681;font-size:10px">≈ ${formatHours(buys)}`
        + `${row ? ` on a ${_esc(row.label)}` : ''}</span>` : '')
      + '</div>'
      + (budget.message
        ? `<div style="font-size:11px;color:${budget.over ? '#f85149' : '#8b949e'}">`
          + `${_esc(budget.message)}</div>`
        : '')
      + `<div style="font-size:11px;color:${
        budget.balance.level === 'warn' ? '#d29922' : '#6e7681'};margin-top:3px">`
      + `${_esc(budget.balance.text)}</div>`
      + (budget.billingMessage
        ? '<div style="font-size:11px;color:#f85149;background:rgba(248,81,73,.1);'
          + 'border:1px solid rgba(248,81,73,.35);border-radius:4px;padding:6px 8px;'
          + `margin-top:6px">⚠ ${_esc(budget.billingMessage)} `
          + 'The Clusters card lists them and can terminate one.</div>'
        : '')
      + '<div style="font-size:10px;color:#6e7681;margin-top:6px;line-height:1.5">'
      + 'This caps ONE pod. A pod reclaimed mid-run is relaunched with the cap afresh, so a '
      + 'run that is interrupted several times can spend several times this.</div>'
  }

  /**
   * The locked block: what this job was set up to rent.
   *
   * Prices, stock and the balance all move constantly, so re-pricing here would show today's
   * market beside a decision made against one that is long gone — and would rent nothing
   * differently. Same reasoning as the Alpine block's recorded view.
   */
  function _paintRecorded() {
    const rec = getRecorded() || {}
    const rows = [
      ['GPU', rec.gpuKey || 'not recorded',
        rec.gpuKey ? '' : 'ranked at launch time instead'],
      ['Spending cap', rec.budgetUsd != null ? formatUsd(rec.budgetUsd) : 'backend default', ''],
      ['Network volume', rec.volumeId || 'the session’s volume', ''],
    ]
    if (rec.podId) rows.push(['Pod', rec.podId, ''])
    mount.innerHTML =
      _sectionTitle('Rented hardware for this job')
      + `<div style="font-size:11px">${
        rows.map(([k, v, n]) => _row(k, v, n)).join('')}</div>`
      + '<div style="font-size:10px;color:#6e7681;margin-top:8px;line-height:1.5">'
      + 'Prices, availability and your balance all change constantly. What this run was '
      + 'estimated to cost is not recalculated here.</div>'
  }

  /** Mount the setup modal lazily — it is the one piece that can change the session. */
  function _ensureSetup() {
    if (_ro() || _setupMounted || !_setupHost) return
    _setupMounted = true
    setup({ mount: _setupHost, onConnected: () => { _volumes = []; refresh({ force: true }) } })
  }

  function _wire() {
    mount.querySelector('#wiz-runpod-recheck')?.addEventListener('click',
      () => refresh({ force: true }))

    mount.querySelectorAll('.runpod-gpu-row').forEach(node => {
      const pick = () => {
        // Picking a card re-costs from rows we already have — never a new round trip.
        _gpuKey = node.dataset.key
        paint()
        onChange()
      }
      node.addEventListener('click', pick)
      node.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick() }
      })
    })

    const budgetInput = mount.querySelector('#wiz-runpod-budget')
    budgetInput?.addEventListener('input', () => {
      const v = Number(budgetInput.value)
      _budget = isFinite(v) && v >= 0 ? v : DEFAULT_BUDGET_USD
      // Re-gate locally against the estimate we already have. `over_budget` is computed
      // server-side too, but waiting for a round trip to learn that a number you just typed is
      // too small would make the field feel broken.
      if (_preview?.budget) {
        _preview.budget.budget_usd = _budget
        _preview.budget.over_budget =
          _preview.budget.estimated_usd != null && _preview.budget.estimated_usd > _budget
      }
      onChange()
    })
    budgetInput?.addEventListener('change', () => paint())

    const vol = mount.querySelector('#wiz-runpod-volume')
    vol?.addEventListener('change', async () => {
      _volumeId = vol.value || null
      // Write it through: the pre-flight's `volume` check reads the SESSION, so a pick that
      // only lived in this closure would leave the gate red with nothing to click.
      if (_volumeId) { try { await setVolume?.(_volumeId) } catch { /* shown by re-check */ } }
      await refresh({ force: true })
    })
  }

  function readiness() {
    if (_ro()) return { ready: true, reason: '' }
    return runpodReadiness({
      preflight: _preview?.preflight || null,
      volumeId: _volumeId,
      gpuKey: _gpuKey,
      preview: _preview,
      busy: _busy,
      blockReason: runpodBlockReason(_preview?.preflight),
      budget: budgetState({
        budget: _preview?.budget, balance: _preview?.balance,
        livePods: _preview?.live_pods || [],
      }),
    })
  }

  return {
    render: paint,
    refresh,
    /** Called when the RunPod card is first opened — the fetches must not run before that. */
    activate() { void refresh(); void _loadVolumes() },
    gpuKey: () => _gpuKey,
    budgetUsd: () => _budget,
    volumeId: () => _volumeId,
    preview: () => _preview,
    readiness,
    isReady: () => readiness().ready,
    reset() {
      _preview = null; _key = ''; _gpuKey = null; _volumeId = null
      _budget = DEFAULT_BUDGET_USD
      paint()
    },
  }
}
