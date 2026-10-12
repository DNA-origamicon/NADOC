export const SIMULATION_CARDS = { cando: 'cando-display-card', snupi: 'snupi-display-card', mrdna: 'mrdna-jobs-display-body', oxdna: 'oxdna-jobs-viz-body', namd: 'md-jobs-viz-body', exp: 'exp-jobs-panel' }
export const clean = text => String(text ?? '').replace(/\s+/g, ' ').trim()
export const isTrajectory = el => /traj|trajectory/i.test(`${el.id} ${el.name} ${el.value}`)
export function simulationJobSummary(job, fallback = '') {
  if (job?.status === 'running' && Number.isFinite(job.progress_fraction)) return `${Math.round(Math.max(0, Math.min(1, job.progress_fraction)) * 100)}%`
  if (job?.status !== 'completed') return job?.status || fallback
  const production = (job.segments || job.stages || []).filter(s => /production/i.test(`${s.kind || ''} ${s.stage || ''} ${s.name || ''}`))
  const durations = production.map(s => s.completed_ns ?? (s.status === 'done' ? s.target_ns : null))
  if (durations.length && durations.every(n => Number.isFinite(n) && n >= 0)) return `${Number(durations.reduce((a,b) => a+b, 0).toFixed(3))} ns`
  return production.length ? 'PRODUCTION COMPLETE' : 'DONE'
}
const modeNames = new Set(['cando-display-mode', 'snupi-display-mode', 'mrdna-display-mode', 'oxdna-viz', 'md-viz', 'mode'])
export function visible(el, root) {
  for (let at = el; at && at !== root?.parentElement; at = at.parentElement) if (at.hidden || at.style?.display === 'none') return false
  return true
}
const label = el => {
  const wrapper = el.labels?.[0]?.cloneNode(true)
  wrapper?.querySelectorAll('input,select,button').forEach(child => child.remove())
  return clean(wrapper?.textContent || el.getAttribute('aria-label') || el.title || el.textContent || el.id)
}
/** Visualization card only: never expose launch, delete or simulation setup actions. */
export function simulationControls(doc, engine, { trajectoryMode = '' } = {}) {
  const root = doc.getElementById(SIMULATION_CARDS[engine]), result = []
  let group = ''
  const activeGroup = trajectoryMode || root?.querySelector('input[type=radio]:checked')?.value || ''
  const elements = engine === 'exp' ? [doc.getElementById('exp-viz')].filter(Boolean) : [...(root?.querySelectorAll('input,select,button') ?? [])]
  for (const [index, el] of elements.entries()) {
    if (el.type === 'hidden' || /traj-(interval|interpolate|slider|scrubber|speed)/.test(el.id)) continue
    const mode = el.type === 'radio' && modeNames.has(el.name) || el.id === 'exp-viz'
    if (mode) group = el.value || 'prediction'
    if (!mode && isTrajectory(el) && !['checkbox', 'radio', 'number', 'select-one'].includes(el.type)) continue // dedicated range/load/playback inspector
    const inTrajectoryOptions = !!trajectoryMode && isTrajectory(el)
    if (!mode && !visible(el, root) && !inTrajectoryOptions) continue
    const base = { id: `v:${index}`, label: label(el), detail: clean(el.title), enabled: !el.disabled && (visible(el, root) || inTrajectoryOptions), active: !!el.checked, element: el,
      group: el.closest('#md-jobs-solvent-opts') ? activeGroup : el.closest('#md-ion-paths-options') ? activeGroup : group,
      kind: mode ? 'mode' : el.tagName === 'SELECT' ? 'choice' : ['number', 'range'].includes(el.type) ? 'number' : 'toggle',
      value: ['number','range'].includes(el.type) ? Number(el.value) || 0 : 0,
      minimum: el.min === '' || el.min == null ? -1e9 : Number(el.min), maximum: el.max === '' || el.max == null ? 1e9 : Number(el.max), step: Number(el.step) || 1 }
    if (el.tagName === 'SELECT') {
      for (const [i, option] of [...el.options].entries()) result.push({ ...base, id: `${base.id}:${i}`, label: `${base.label.split(':')[0]}: ${clean(option.textContent)}`, active: option.selected, enabled: base.enabled && !option.disabled, choice: option.value })
    } else if (mode || ['radio', 'checkbox', 'button', 'submit', 'number', 'range'].includes(el.type) || el.tagName === 'BUTTON') result.push(base)
  }
  return result
}
/** Mirror every visible desktop progress indicator; unknown totals stay indeterminate. */
export function simulationProgress(doc, engine) {
  const root = doc.getElementById(SIMULATION_CARDS[engine]); if (!root) return []
  const rows = []
  for (const el of doc.querySelectorAll('#simulate-jobs-toggle [data-panel-loading],.engine-selector-btn[data-engine="' + engine + '"] [data-panel-loading]')) {
    if (visible(el)) rows.push({ label: el.getAttribute('aria-label') || 'Reading simulation data', fraction: -1, busy: true })
  }
  for (const el of root.querySelectorAll('[role="progressbar"],progress,[id$="progress"],[id$="load-progress"],[id$="status"]')) {
    if (!visible(el, root)) continue
    const text = clean(el.querySelector('[id$="label"]')?.textContent || el.getAttribute('aria-label') || el.textContent)
    let percent = Number(el.getAttribute('aria-valuenow'))
    if (el.tagName === 'PROGRESS') percent = el.hasAttribute('value') ? 100 * el.value / el.max : -1
    else if (!el.hasAttribute('aria-valuenow')) {
      const fill = el.querySelector('[id$="fill"],[style*="width:"]')
      percent = fill?.style.width?.endsWith('%') ? parseFloat(fill.style.width) : -1
    }
    const busy = /\b(?:loading|preparing|downloading|building|parsing|aligning|analysing|analyzing|reading|transferring|computing|clustering|buffering)\b/i.test(text) || el.dataset.loading === 'true'
    if (busy || el.matches('[role="progressbar"],progress')) rows.push({ label: text || 'Preparing visualization', fraction: percent < 0 ? -1 : Math.min(1, percent / 100), busy })
  }
  for (const el of doc.querySelectorAll(".toast--visible")) {
    const text = clean(el.querySelector(".toast-message")?.textContent || el.textContent)
    if (/loading|preparing|building|reconstructing/i.test(text)) rows.push({ label: text, fraction: -1, busy: true })
  }
  return rows.slice(-8)
}
