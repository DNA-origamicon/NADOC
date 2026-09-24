/**
 * Hairpin/Dimer Checker — the Tools → Sequencing toggle ('0') and the automatic
 * check that follows every overhang-sequence generation.
 *
 * Toggle ON: check the whole design, then stay live — after each design edit
 * the overhangs / linker strands whose check is missing or stale are re-checked
 * (debounced). The report is published to the `hairpinDimerReport` store key,
 * which drives every ⚠ (spreadsheet, Plates & tubes, Overhang Connections, the
 * 3D view, the cadnano path view). Toggle OFF: the key is null, so no ⚠ shows.
 *
 * Overhang generation is always checked (the original requirement): a flagged
 * result toasts, and while the toggle is off the toast points to it.
 *
 * The on/off state persists in localStorage (shared by the 3D and cadnano
 * pages) and is mirrored to other tabs over the BroadcastChannel.
 *
 * @param {object}   deps
 * @param {object}   deps.store                       getState/setState/subscribe
 * @param {string}  [deps.designKey='currentDesign']  store key holding the Design
 * @param {Function} deps.checkHairpinDimer           (body, opts) → report | null
 * @param {Function} [deps.onOverhangSequencesGenerated] (fn(ids)) → unsubscribe
 * @param {Function} deps.showToast
 * @param {Function} [deps.showProgress] / [deps.hideProgress]
 * @param {object}   [deps.broadcast]                 nadocBroadcast
 * @param {string}   [deps.menuButtonId]
 * @param {number}   [deps.recheckDelayMs=400]
 */
import {
  HAIRPIN_DIMER_SEVERE_C,
  HAIRPIN_DIMER_THRESHOLD_C,
  buildHairpinDimerIndex,
  formatHairpinDimerConditions,
  formatHairpinDimerLine,
  hairpinDimerCheckLevel,
  hairpinDimerLevel,
  hairpinDimerRecheckTargets,
  mergeHairpinDimerReport,
} from './hairpin_dimer_report.js'

export const HAIRPIN_DIMER_REPORT_KEY = 'hairpinDimerReport'
export const HAIRPIN_DIMER_ACTIVE_LS_KEY = 'nadoc.hairpinDimer.active'
const TOGGLE_MSG = 'hairpin-dimer-toggle'
const WARN_TOAST_MS = 8000
const TOGGLE_HINT = ' — turn on Tools › Sequencing › Hairpin/Dimer Checker [0] to mark it.'

function _readActive() {
  try { return localStorage.getItem(HAIRPIN_DIMER_ACTIVE_LS_KEY) === '1' } catch { return false }
}
function _writeActive(on) {
  try { localStorage.setItem(HAIRPIN_DIMER_ACTIVE_LS_KEY, on ? '1' : '0') } catch { /* private mode */ }
}

export function initHairpinDimerChecker({
  store,
  designKey = 'currentDesign',
  checkHairpinDimer,
  onOverhangSequencesGenerated = null,
  showToast,
  showProgress = () => {},
  hideProgress = () => {},
  broadcast = null,
  menuButtonId = 'menu-seq-hairpin-dimer',
  recheckDelayMs = 400,
}) {
  let _active = _readActive()
  let _report = null            // every check received (published only while active)
  let _running = false
  let _recheckTimer = null
  let _inFlight = 0             // partial checks (generation hook / live re-check) awaiting a response
  const _menuBtn = () => document.getElementById(menuButtonId)
  const _getDesign = () => store.getState()[designKey] ?? null
  const _nameOf = id => {
    const o = (_getDesign()?.overhangs ?? []).find(x => x.id === id)
    return o?.label || o?.name || id
  }

  function _publish() {
    const next = _active ? _report : null
    if (store.getState()[HAIRPIN_DIMER_REPORT_KEY] !== next) store.setState({ [HAIRPIN_DIMER_REPORT_KEY]: next })
  }

  /** Merge a response; return its flagged checks that still match the design. */
  function _merge(incoming) {
    _report = mergeHairpinDimerReport(_report, incoming)
    _publish()
    return buildHairpinDimerIndex(incoming, _getDesign()).flagged
  }

  function _summary(report, flagged) {
    const t = report.threshold_c ?? HAIRPIN_DIMER_THRESHOLD_C
    const { checked = 0, unsequenced = 0 } = report.summary ?? {}
    const cond = ` (${formatHairpinDimerConditions(report.conditions)})`
    const skipped = unsequenced ? ` ${unsequenced} unsequenced skipped.` : ''
    if (!report.checks?.length) return 'Hairpin/dimer checker on: no overhangs or linker strands to check.'
    if (!flagged.length) {
      return `Hairpin/dimer checker on: no hairpin or self-dimer Tm > ${t} °C in ${checked} `
        + `sequence${checked === 1 ? '' : 's'}${cond}.${skipped}`
    }
    const n = new Set(flagged.map(x => x.strand_id)).size
    const sv = report.severe_threshold_c ?? HAIRPIN_DIMER_SEVERE_C
    const nCrit = new Set(flagged.filter(x => hairpinDimerCheckLevel(x, sv) === 'critical').map(x => x.strand_id)).size
    const crit = nCrit ? `, ${nCrit} above ${sv} °C (red ⚠)` : ''
    return `Hairpin/dimer checker on: ${n} strand${n === 1 ? '' : 's'} with hairpin or self-dimer `
      + `Tm > ${t} °C${crit}${cond} — marked ⚠ in the 3D view, cadnano editor, spreadsheet, Plates & tubes `
      + `and Overhang Connections; click one for the structure.${skipped}`
  }

  /** Full-design check. `announce` shows progress + the summary toast. */
  async function runAll({ announce = true } = {}) {
    if (_running) return null
    if (!_getDesign()) {
      if (announce) showToast('No design loaded.', { severity: 'error' })
      return null
    }
    _running = true
    if (announce) showProgress('Checking hairpins and self-dimers…')
    let report = null
    try {
      report = await checkHairpinDimer({}, { quiet: !announce })
    } finally {
      if (announce) hideProgress()
      _running = false
    }
    if (!report) {
      if (announce) showToast('Hairpin/dimer check failed.', { severity: 'error' })
      return null
    }
    const flagged = _merge(report)
    if (announce) {
      showToast(_summary(report, flagged), flagged.length
        ? { severity: 'warning', duration: WARN_TOAST_MS }
        : { severity: 'info', duration: 4000 })
    }
    return report
  }

  /** Turn the checker on/off (menu toggle, '0', or another tab). */
  async function setActive(on, { share = true, announce = true } = {}) {
    _active = !!on
    _writeActive(_active)
    _menuBtn()?.classList.toggle('is-on', _active)
    if (share) {
      try { broadcast?.emit(TOGGLE_MSG, { active: _active }) } catch { /* best-effort */ }
    }
    clearTimeout(_recheckTimer)
    _publish()
    if (_active) await runAll({ announce })
  }

  /** Re-check what the latest edits made stale (live mode). */
  async function _recheck() {
    _recheckTimer = null
    const design = _getDesign()
    if (!_active || !design) return
    if (!_report || _report.design_id !== design.id) { await runAll({ announce: false }); return }
    // Let an in-flight check land first — e.g. the generation hook already asked
    // for exactly the overhangs this edit touched.
    if (_inFlight) { _scheduleRecheck(); return }
    const { overhang_ids, strand_ids } = hairpinDimerRecheckTargets(_report, design)
    if (!overhang_ids.length && !strand_ids.length) return
    const body = {}
    if (overhang_ids.length) body.overhang_ids = overhang_ids
    if (strand_ids.length) body.strand_ids = strand_ids
    _inFlight++
    try {
      const report = await checkHairpinDimer(body, { quiet: true })
      if (report) _merge(report)
    } finally {
      _inFlight--
    }
  }

  function _scheduleRecheck() {
    clearTimeout(_recheckTimer)
    _recheckTimer = setTimeout(_recheck, recheckDelayMs)
  }

  /** Check only *overhangIds* (and the linkers bound to them) — generation hook. */
  async function checkOverhangs(overhangIds) {
    const ids = [...new Set(overhangIds ?? [])].filter(Boolean)
    if (!ids.length || !_getDesign()) return null
    _inFlight++
    let report = null
    try {
      report = await checkHairpinDimer({ overhang_ids: ids }, { quiet: true })
    } finally {
      _inFlight--
    }
    if (!report) return null
    const flagged = _merge(report)
    const hint = _active ? '' : TOGGLE_HINT
    // Red (error) toast when anything is above the critical Tm, amber otherwise.
    const severity = hairpinDimerLevel(flagged, report.severe_threshold_c) === 'critical' ? 'error' : 'warning'
    if (flagged.length === 1) {
      showToast(`⚠ ${formatHairpinDimerLine(flagged[0], { nameOf: _nameOf, threshold: report.threshold_c })}${hint}`,
        { severity, duration: WARN_TOAST_MS })
    } else if (flagged.length > 1) {
      const t = report.threshold_c ?? HAIRPIN_DIMER_THRESHOLD_C
      showToast(`⚠ ${flagged.length} generated sequences have hairpin or self-dimer Tm > ${t} °C${hint || ' — see the ⚠ icons.'}`,
        { severity, duration: WARN_TOAST_MS })
    }
    return report
  }

  _menuBtn()?.classList.toggle('is-on', _active)
  _menuBtn()?.addEventListener('click', () => { setActive(!_active) })
  const _unsubGenerated = onOverhangSequencesGenerated?.(ids => { checkOverhangs(ids) }) ?? null
  const _unsubStore = store.subscribe?.((s, p) => {
    if (_active && s[designKey] !== p[designKey]) _scheduleRecheck()
  }) ?? null
  const _unsubBroadcast = broadcast?.onMessage?.(data => {
    if (data?.type === TOGGLE_MSG && !!data.active !== _active) setActive(data.active, { share: false, announce: false })
  }) ?? null
  if (_active && _getDesign()) _scheduleRecheck()

  return {
    runAll,
    setActive,
    toggle: () => setActive(!_active),
    isActive: () => _active,
    checkOverhangs,
    destroy() {
      clearTimeout(_recheckTimer)
      _unsubGenerated?.()
      _unsubStore?.()
      _unsubBroadcast?.()
    },
  }
}
