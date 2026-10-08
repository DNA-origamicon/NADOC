/** Temporary solid-origami generator; records construction in the current loadout. */
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { createInput, createSelect } from './primitives/input.js'
import { el } from './primitives/dom.js'

export function showGenerateDesign({ api, store }) {
  const state = store.getState()
  const particles = state.currentDesign?.nanoparticles?.filter(p => p.kind === 'gold_nanosphere') ?? []
  const platform = particles.length > 2
  const enabled = !state.assemblyActive && !!state.currentDesign && [2, 3, 4].includes(particles.length)
  const body = el('div', { attrs: { style: 'display:grid;gap:var(--space-3,12px)' } })
  const summary = el('div', { text: enabled ? `${particles.length} gold nanoparticles · ${state.currentDesign.lattice_type ?? ''}` : 'Open a part with 2–4 gold nanoparticles.', attrs: {
    title: 'Preserve particle centers and existing geometry. Add individual editable construction steps to the current loadout. Prefer greater weakest-axis bending rigidity within scaffold, bend, and clearance limits. Rigidity is a geometric proxy; stiffness, RMSF, and sequence thermodynamics are not simulated.',
  } })
  body.append(summary)
  function field(label, control, tooltip, ariaLabel = label) {
    control.setAttribute('aria-label', ariaLabel)
    control.title = tooltip
    const row = el('div', { children: [el('label', { className: 'input-group', attrs: { title: tooltip, style: 'width:100%;justify-content:space-between' }, children: [el('span', { className: 'input-group__label', text: label }), control] })] })
    body.append(row)
    return row
  }
  const shape = createSelect({ disabled: !enabled, options: [
    { value: 'auto', label: platform ? 'Platform' : 'Straight rod' },
    ...(platform ? [{ value: 'curved-rod', label: 'Curved rod' }] : []),
  ] })
  field('Design shape', shape, 'Platforms prefer alignment with nanoparticle perimeter edges. Curved rods follow a planar path through the attachment sites. Complete lattice cross-sections are compared for greater rigidity.')
  const curved = () => shape.value === 'curved-rod'
  const pathing = createSelect({ options: ['Colocalized', 'Interior', 'Exterior'].map(label => ({ value: label.toLowerCase(), label })) })
  const pathRow = field('Pathing', pathing, 'Colocalized: beneath the projected particle positions. Interior: beside the particles toward the center of their arrangement. Exterior: beside the particles away from that center. Interior/exterior paths run near the equators in the fitted plane; attachments accommodate reachable height differences.')
  const rotationLabel = platform ? 'Platform rotation within fitted plane (degrees)' : 'Rotation around particle axis (degrees)'
  const roll = createInput({ type: 'number', min: -180, max: 180, step: 1, value: '0', disabled: !enabled })
  const rollRow = field('Rotation (°)', roll, platform ? 'Rotate within the fitted plane. Zero prefers alignment with at least one perimeter edge for three particles, or two for four when feasible.' : 'Rotate the rod around the line between particle centers.', rotationLabel)
  const length = createInput({ type: 'number', min: 12, max: 60, step: 1, value: '18', disabled: !enabled })
  field('New duplex length (bp)', length, 'Reuse compatible handles at their existing sequence and length. Otherwise create one direct-thiol handle and complementary overhang per particle with this duplex length.')
  const order = createInput({ placeholder: 'Automatic' })
  let orderEdited = false
  const particleKey = particles.map((p, i) => {
    const v = p.pose?.values
    return `${i + 1}: ${p.name || p.label || 'Gold'}${v ? ` (${[v[3], v[7], v[11]].map(x => x.toFixed(1)).join(', ')} nm)` : ''}`
  }).join('\n')
  const orderRow = field('Particle visit order', order, `The automatic order is shown after calculation. Edit to fix the order, using each particle number once, separated by commas; clear to choose automatically again.\n${particleKey}`)
  pathRow.hidden = orderRow.hidden = true
  const status = el('div', { attrs: { role: 'status', 'aria-live': 'polite', style: 'white-space:pre-line' } })
  const progress = el('progress', { attrs: { max: '1', value: '0', 'aria-label': 'Design generation progress', title: 'Progress through construction stages; stage durations vary.', style: 'width:100%;accent-color:var(--color-accent)' } })
  const stage = el('div')
  const detail = el('div', { attrs: { style: 'color:var(--color-text-muted)' } })
  const steps = el('div', { attrs: { style: 'max-height:100px;overflow:auto;white-space:pre-line;color:var(--color-text-muted)' } })
  const progressPanel = el('div', { attrs: { hidden: '', 'aria-live': 'polite' }, children: [progress, stage, detail, steps] })
  function showProgress(value) {
    progressPanel.hidden = false
    progress.value = value.fraction ?? 0
    stage.textContent = value.stage
    detail.textContent = value.detail ?? ''
    if (value.steps) steps.textContent = value.steps.map(s => `✓ ${s}`).join('\n')
  }
  body.append(status, progressPanel)
  let plan = null
  let busy = false
  function settings(useReviewedOrder = false) {
    const values = { roll_deg: curved() ? 0 : Number(roll.value), duplex_bp: Number(length.value), extend_rod: true }
    if (curved()) {
      values.shape = 'curved-rod'
      values.pathing = pathing.value
      if (order.value.trim() && (orderEdited || useReviewedOrder)) {
        const indices = order.value.split(',').map(v => Number(v.trim()) - 1)
        if (indices.length !== particles.length || new Set(indices).size !== particles.length || indices.some(i => !Number.isInteger(i) || i < 0 || i >= particles.length)) {
          throw new Error(`Enter each particle number from 1 to ${particles.length} exactly once, separated by commas.`)
        }
        values.particle_order = indices.map(i => particles[i].id)
      }
    }
    return values
  }
  const error = () => api.lastErrorMessage?.() || 'Generation failed. Check the feature log before retrying.'
  function setBusy(value) {
    busy = value
    calculate.disabled = value || !enabled
    generate.disabled = value || !plan
    for (const input of [shape, pathing, length, order]) input.disabled = value || !enabled
    roll.disabled = value || !enabled || curved()
  }
  function invalidate() {
    plan = null
    generate.disabled = true
    status.textContent = 'Settings changed. Calculate again.'
    status.title = ''
  }
  async function calculatePlan() {
    plan = null
    if ((!curved() && (roll.value === '' || !roll.checkValidity())) || length.value === '' || !length.checkValidity()) {
      status.textContent = 'Enter a rotation from −180 to 180° and an integer duplex length from 12 to 60 bp.'
      generate.disabled = true
      return
    }
    setBusy(true)
    progressPanel.hidden = true
    status.textContent = 'Comparing designs…'
    try {
      plan = await api.planGeneratedDesign(settings())
      if (!plan) { status.textContent = error(); return }
      if (curved() && plan.path_particle_ids) order.value = plan.path_particle_ids.map(id => particles.findIndex(p => p.id === id) + 1).join(', ')
      status.textContent = plan.alternatives.map(c => c.feasible === false
        ? `${c.scaffold_size}: unavailable`
        : `${c.scaffold_size}: ${c.section} · ${c.length_nm.toFixed(1)} nm${c.scaffold_size === plan.selected.scaffold_size ? ' · selected' : ''}`).join('\n')
      status.title = [plan.reason,
        ...(curved() && plan.path_length_nm != null ? [`Planar path: ${plan.path_length_nm.toFixed(1)} nm · visit order: ${order.value}`] : []),
        `Maximum particle separation: ${plan.center_distance_nm.toFixed(2)} nm`,
        ...(plan.perimeter_alignment ? [`Perimeter alignment: ${plan.perimeter_alignment.aligned_edges} edges within ${plan.perimeter_alignment.tolerance_deg}°.`] : []),
        `${plan.selected.unused_scaffold_nt} scaffold bases remain unrouted. Extend beyond attachment sites to use most of the scaffold.`,
        plan.attachment_status,
      ].filter(Boolean).join('\n')
    } catch (e) { status.textContent = e.message; plan = null }
    finally { setBusy(false) }
  }
  const calculate = createButton({ label: 'Calculate design', disabled: !enabled, title: 'Compare complete cross-sections and paths within the 7249/8064 scaffold budgets.', onClick: calculatePlan })
  const generate = createButton({ label: 'Generate in current loadout', variant: 'primary', disabled: true, title: 'Build the reviewed design as individual feature-log steps. Fixed-center attachment reach and gold-core clearance must pass before any changes are committed.', onClick: async () => {
    if (!plan || busy) return
    setBusy(true)
    status.textContent = ''
    steps.textContent = ''
    showProgress({ stage: 'Starting generation…', fraction: 0 })
    try {
      const result = await api.generateDesign(settings(true), plan.revision, plan.doc_id, showProgress)
      plan = null
      if (result) {
        const items = result.generation.connections
        status.textContent = `Added ${items.length} connections. Particle centers preserved.`
        status.title = `${items.filter(c => c.reused).length} reused handles. Edit, scrub, or revert individual construction steps in the current loadout.`
      } else { status.textContent = error(); stage.textContent = 'Generation failed' }
    } catch (e) { status.textContent = e.message; stage.textContent = 'Generation failed'; plan = null }
    finally { setBusy(false) }
  } })
  shape.addEventListener('change', () => {
    pathRow.hidden = orderRow.hidden = !curved()
    rollRow.hidden = curved()
    invalidate()
    setBusy(false)
  })
  pathing.addEventListener('change', invalidate)
  order.addEventListener('input', () => { orderEdited = !!order.value.trim() })
  for (const input of [roll, length, order]) input.addEventListener('input', invalidate)
  const modal = createModal({ title: 'Generate design', size: 'md', body, actions: [calculate, generate], onClose: () => !busy })
  modal.open()
  if (enabled) void calculatePlan()
  return modal
}
