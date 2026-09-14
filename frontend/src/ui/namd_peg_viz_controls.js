import { isPegJob } from './namd_peg_visualization.js'

const id = suffix => document.getElementById(`md-jobs-${suffix}`)
const modes = { off: 'viz-off', display: 'display-toggle', flex: 'flex-toggle', traj: 'traj-toggle' }

/** Thin panel handoff, including exit when selecting a DNA job in the same document. */
export function updatePegVisualization(job) {
  window.dispatchEvent(new CustomEvent('nadoc:peg-viz-availability', { detail: { job } }))
  return isPegJob(job)
}

/** Shared sidebar controls route PEG to the atom-index renderer, never the DNA parser. */
export function initPegVizControls({ onMode, onAction }) {
  let job = null, mode = 'off', view = null, restore = []
  const remember = (el, property, value) => {
    if (!el) return
    if (!restore.some(r => r.el === el && r.property === property)) restore.push({ el, property, value: el[property] })
    el[property] = value
  }
  function sync(next = view) {
    view = next
    if (!isPegJob(job)) return
    const hasFrames = !!view?.frames?.length, canFlex = hasFrames && view.stage !== 'minimize' && (view.raw_frames ?? view.frames.length) >= 2
    for (const [key, suffix] of Object.entries(modes)) {
      const el = id(suffix)
      if (!el) continue
      el.disabled = key === 'flex' ? !canFlex : key === 'traj' ? !hasFrames : false
      el.checked = key === mode
      remember(el.closest('label'), 'title', key === 'flex'
        ? 'Per-atom PEG RMSF in the fixed surface frame, for the selected dynamics stage. Relaxation sampling is not equilibrium.'
        : 'PEG atoms, PSF bonds, harmonic grafts and repulsive walls')
      if (el.closest('label')) {
        remember(el.closest('label').style, 'opacity', '1')
        remember(el.closest('label').style, 'cursor', el.disabled ? 'not-allowed' : 'pointer')
        remember(el.closest('label').style, 'color', el.disabled ? '#8b949e' : '#c9d1d9')
      }
    }
    for (const [suffix, reason] of [
      ['photoproduct', 'Not applicable: PEG has no thymine bases.'],
      ['occupancy', 'PEG occupancy requires validated production sampling. These qualification/relaxation jobs do not provide an equilibrium ensemble.'],
    ]) {
      const el = id(`${suffix}-toggle`)
      if (el) { el.disabled = true; el.checked = false; remember(el.closest('label'), 'title', reason) }
      remember(id(`${suffix}-status`), 'textContent', reason)
    }
    for (const suffix of ['occupancy-params', 'occupancy-legend', 'photoproduct-legend', 'flex-bar', 'flex-legend', 'traj-load-progress', 'traj-opts']) {
      if (id(suffix)) remember(id(suffix).style, 'display', 'none')
    }
    if (id('traj-controls')) remember(id('traj-controls').style, 'display', mode === 'traj' ? 'block' : 'none')
    if (id('traj-markers')) id('traj-markers').replaceChildren()
    const solvent = mode === 'display' || mode === 'traj' || mode === 'off'
    for (const suffix of ['water-toggle', 'box-toggle']) if (id(suffix)) id(suffix).disabled = !solvent
    remember(id('solvent-opts')?.style, 'opacity', '1')
    for (const suffix of ['water-toggle', 'box-toggle']) {
      const label = id(suffix)?.closest('label')
      remember(label?.style, 'opacity', solvent ? '1' : '.6')
      remember(label?.style, 'cursor', solvent ? 'pointer' : 'not-allowed')
      remember(label, 'title', 'PEG water oxygens / fixed periodic cell')
    }
    if (id('ions-toggle')) { id('ions-toggle').disabled = true; remember(id('ions-toggle'), 'title', 'No ions in this PEG/water qualification package.') }
    if (id('solvent-status')) id('solvent-status').textContent = solvent ? 'PEG water oxygens and periodic cell; no ions in this package.' : 'Solvent hidden for the time-mean RMSF structure.'
    if (id('water-opts')) remember(id('water-opts').style, 'display', solvent && id('water-toggle')?.checked ? 'block' : 'none')
    for (const suffix of ['display-status', 'flex-status', 'traj-status', 'occupancy-status', 'photoproduct-status', 'solvent-status']) {
      if (id(suffix)) {
        remember(id(suffix).style, 'color', '#c9d1d9')
        remember(id(suffix), 'textContent', id(suffix).textContent)
      }
    }
    if (id('display-indicator')) remember(id('display-indicator').style, 'display', 'none')
    if (id('display-status')) id('display-status').textContent = mode === 'display' ? 'PEG latest complete frame · refreshes every 5 s while running' : ''
    if (id('flex-status')) id('flex-status').textContent = mode === 'flex' ? 'Per-atom PEG RMSF · see the surface viewer scale' : canFlex ? '' : 'Requires two dynamics frames; minimization is excluded.'
    if (id('traj-status')) id('traj-status').textContent = hasFrames ? `${view.frames.length} sampled / ${view.raw_frames ?? view.frames.length} recorded frames · ${view.stage}` : 'Waiting for recorded PEG frames.'
  }
  const availability = event => {
    const next = event.detail.job
    if (!isPegJob(next)) {
      if (isPegJob(job)) {
        restore.forEach(r => { r.el[r.property] = r.value }); restore = []
        job = null; view = null; onAction('close')
      }
      return
    }
    if (next.job_id !== job?.job_id) view = null
    job = next; sync()
  }
  const capture = event => {
    if (!isPegJob(job)) return
    const target = event.target, suffix = target.id?.replace(/^md-jobs-/, '')
    const selected = Object.entries(modes).find(([, value]) => value === suffix)?.[0]
    const actions = ['traj-play', 'traj-prev', 'traj-next', 'traj-slider', 'water-toggle', 'water-shell', 'water-scope-shell', 'water-scope-box', 'box-toggle']
    if (!selected && !actions.includes(suffix)) return
    event.stopImmediatePropagation()
    if (selected && (event.type === 'change' || selected === 'off' && event.type === 'click')) {
      if (target.disabled) return
      mode = selected; onMode(mode); sync()
    } else if (actions.includes(suffix) && (suffix.startsWith('traj-') ? (suffix === 'traj-slider' ? event.type === 'input' : event.type === 'click') : event.type === 'change')) {
      onAction(suffix, target); sync()
    }
  }
  window.addEventListener('nadoc:peg-viz-availability', availability)
  for (const event of ['click', 'change', 'input']) document.addEventListener(event, capture, true)
  return {
    sync,
    setMode(next) { mode = next; sync() },
    solvent() { return { water: !!id('water-toggle')?.checked, box: !!id('box-toggle')?.checked,
      shell: id('water-scope-shell')?.checked ? Math.max(1, Math.min(30, Number(id('water-shell')?.value) || 5)) : null } },
    frame(index, label, playing, count) {
      const slider = id('traj-slider')
      for (const suffix of ['traj-slider', 'traj-play', 'traj-prev', 'traj-next']) {
        if (id(suffix)) id(suffix).disabled = mode !== 'traj' || count < (suffix === 'traj-slider' ? 1 : 2)
      }
      if (slider) { slider.max = Math.max(0, count-1); slider.value = index }
      if (id('traj-label')) id('traj-label').textContent = label
      if (id('traj-play')) id('traj-play').textContent = playing ? '❚❚' : '▶'
    },
    dispose() {
      restore.forEach(r => { r.el[r.property] = r.value })
      window.removeEventListener('nadoc:peg-viz-availability', availability)
      for (const event of ['click', 'change', 'input']) document.removeEventListener(event, capture, true)
    },
  }
}
