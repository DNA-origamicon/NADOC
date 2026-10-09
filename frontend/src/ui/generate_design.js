/** Temporary solid-origami generator; records construction in the current loadout. */
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { createInput, createSelect } from './primitives/input.js'
import { el } from './primitives/dom.js'

export function showGenerateDesign({ api, store, connectivityPlan = null }) {
  const state = store.getState()
  const particles = state.currentDesign?.nanoparticles?.filter(p => p.kind === 'gold_nanosphere') ?? []
  const platform = particles.length > 2
  const enabled = !state.assemblyActive && !!state.currentDesign && (connectivityPlan ? particles.length >= 2 && particles.length <= 8 : [2, 3, 4].includes(particles.length))
  const body = el('div', { attrs: { style: 'display:grid;grid-template-columns:minmax(0,1fr);gap:var(--space-3,12px)' } })
  const summary = el('div', { text: enabled ? `${particles.length} gold nanoparticles · ${state.currentDesign.lattice_type ?? ''}` : 'Open a part with 2–4 gold nanoparticles.', attrs: {
    title: 'Preserve particle centers and existing geometry. Add individual editable construction steps to the current loadout. Choose geometric sizing or mechanical reinforcement for curved rods within scaffold, bend, and clearance limits. Mechanical predictions are uncalibrated. Every generated design receives a CanDo connectivity and flexibility check before it is added. Optional simulation jobs provide additional validation.',
  } })
  body.append(summary)
  function field(label, control, tooltip, ariaLabel = label) {
    control.setAttribute('aria-label', ariaLabel)
    control.title = tooltip
    control.style.minWidth = '0'
    control.style.maxWidth = '55%'
    const row = el('div', { children: [el('label', { className: 'input-group', attrs: { title: tooltip, style: 'width:100%;justify-content:space-between' }, children: [el('span', { className: 'input-group__label', text: label }), control] })] })
    body.append(row)
    return row
  }
  const shape = createSelect({ disabled: !enabled, options: [
    { value: 'auto', label: platform ? 'Platform' : 'Straight rod' },
    ...(platform ? [{ value: 'curved-rod', label: 'Curved rod' }] : []),
    ...(platform ? [{ value: 'branched', label: 'Branched (experimental)' }] : []),
  ] })
  field('Design shape', shape, 'Platforms prefer alignment with nanoparticle perimeter edges. Curved rods follow a planar path through the attachment sites, using an editable sweep when more bends than particles are needed. Complete lattice cross-sections are compared for greater rigidity.')
  if (connectivityPlan) {
    shape.replaceChildren(new Option('Reviewed connectivity tree', 'branched'))
    summary.textContent += ` · ${connectivityPlan.uniform_hb}HB arms · ${2 * connectivityPlan.uniform_hb}HB junctions. Blunt-end duplex space is reserved; overhangs and NP graft sites remain unassigned.`
  }
  const curved = () => shape.value === 'curved-rod'
  const branched = () => shape.value === 'branched'
  const branchGeometry = createSelect({ options: [
    { value: 'curved', label: 'Curved branches' },
    { value: 'lattice', label: 'Straight lattice branches' },
  ] })
  const branchGeometryRow = field('Branch geometry', branchGeometry, 'Curved: independently size lattice cross-sections and crosslinked junctions within the selected scaffold budget. Straight: the previous lattice trunk-and-crossbar search.')
  branchGeometryRow.hidden = true
  const branchScaffold = createSelect({ options: [{ value: 'auto', label: 'Automatic · compare both' }, { value: '8064', label: 'p8064 · 8064 bases' }, { value: '7249', label: 'M13mp18 · 7249 bases' }] })
  const branchScaffoldRow = field('Branch scaffold', branchScaffold, 'Size branches and junctions for this scaffold. Actual routed bases include curvature insertions/deletions. Any unused bases are reported.')
  branchScaffoldRow.hidden = true
  const branchSizing = createSelect({ options: [{ value: 'optimized', label: 'Optimize cross-sections' }, { value: 'fixed', label: 'Original 6HB forks' }] })
  const branchSizingRow = field('Branch sizing', branchSizing, 'Compare independent lattice cross-sections using a weak-axis bending estimate; routing, attachment fit and CanDo still must validate. Original mode retains the previous 6HB → 12HB forks.')
  branchSizingRow.hidden = true
  const branchNote = el('div', { attrs: { hidden: '' } })
  function updateBranchNote() {
    branchNote.textContent = branchGeometry.value === 'curved'
      ? 'Size curved arms, stems and junctions for rigidity within the scaffold budget. Requires room for gentle turns; split points stay crosslinked. This is a bounded sizing search, not a global rigidity optimum.'
      : 'Planar lattice trunks with crosslinked straight branches. Searches I- and T-like layouts within scaffold budget.'
  }
  updateBranchNote()
  body.append(branchNote)
  const mechanics = createSelect({ options: [
    { value: 'legacy', label: 'Original geometric sizing' },
    { value: 'beam', label: '1 · Fast beam: uniform reinforcement' },
    { value: 'variable', label: '2 · Fast beam: variable reinforcement' },
    { value: 'robust', label: '3 · Variable + uncertainty scenarios' },
    { value: 'fem-linear', label: '4 · Uncertainty + linear FEM validation' },
    { value: 'fem-nonlinear', label: '5 · Uncertainty + nonlinear FEM validation' },
    { value: 'oxdna', label: '6 · Uncertainty + oxDNA pilot validation' },
  ] })
  const mechanicsRow = field('Mechanical optimization', mechanics, 'Curved rods: allocate scaffold to reduce predicted pair-distance and aligned 3D motion. Each level is independently selectable. FEM and oxDNA start snapshot jobs after generation; view progress/results in Simulations. These validation jobs do not automatically optimize again. oxDNA uses local GPU relaxation, equilibration and 5 million production steps at 0.5 M salt. Experimental calibration is pending matching literature data.')
  mechanicsRow.hidden = true
  const pathing = createSelect({ options: ['Colocalized', 'Interior', 'Exterior'].map(label => ({ value: label.toLowerCase(), label })) })
  const pathRow = field('Pathing', pathing, 'Colocalized: beneath the projected particle positions. Interior: beside the particles toward the center of their arrangement. Exterior: beside the particles away from that center. Interior/exterior paths run near the equators in the fitted plane; attachments accommodate reachable height differences.')
  const rotationLabel = platform ? 'Platform rotation within fitted plane (degrees)' : 'Rotation around particle axis (degrees)'
  const roll = createInput({ type: 'number', min: -180, max: 180, step: 1, value: '0', disabled: !enabled })
  const rollRow = field('Rotation (°)', roll, platform ? 'Rotate within the fitted plane. Zero prefers alignment with at least one perimeter edge for three particles, or two for four when feasible.' : 'Rotate the rod around the line between particle centers.', rotationLabel)
  const length = createInput({ type: 'number', min: 12, max: 60, step: 1, value: '18', disabled: !enabled })
  field('New duplex length (bp)', length, 'Reuse compatible handles at their existing sequence and length. Create missing direct-thiol handles and complementary overhangs with this duplex length. New graft sites are fitted; existing graft sites are preserved.')
  const connections = createSelect({ disabled: !enabled, options: [1, 2, 3].map(n => ({ value: String(n), label: String(n) })) })
  field('Connections per nanoparticle', connections, 'Add 1–3 independent overhang connections to every nanoparticle. All requested connections must fit without moving particle centers; otherwise generation leaves the design unchanged.')
  body.append(el('div', { text: 'Automatic CanDo check: duplex connectivity, shape and flexibility before adding the design.', attrs: { title: 'An elastic structural screen; it does not predict folding, strand dissociation or gold/linker dynamics.' } }))
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
    if (connections.value !== '1') values.connections_per_particle = Number(connections.value)
    if (branched()) { values.shape = 'branched'; values.branch_geometry = branchGeometry.value; values.extend_rod = false; if (branchGeometry.value === 'curved') { values.branch_sizing = branchSizing.value; values.branch_scaffold_size = branchScaffold.value === 'auto' ? 'auto' : Number(branchScaffold.value) } }
    if (curved()) {
      values.shape = 'curved-rod'
      if (mechanics.value !== 'legacy') values.mechanics = mechanics.value
      values.pathing = pathing.value
      if (order.value.trim() && (orderEdited || useReviewedOrder)) {
        const indices = order.value.split(',').map(v => Number(v.trim()) - 1)
        if (indices.length !== particles.length || new Set(indices).size !== particles.length || indices.some(i => !Number.isInteger(i) || i < 0 || i >= particles.length)) {
          throw new Error(`Enter each particle number from 1 to ${particles.length} exactly once, separated by commas.`)
        }
        values.particle_order = indices.map(i => particles[i].id)
      }
    }
    if (connectivityPlan) { values.connectivity_plan = connectivityPlan; values.shape = 'branched'; values.branch_sizing = 'fixed'; values.branch_scaffold_size = 'auto' }
    return values
  }
  const error = () => api.lastErrorMessage?.() || 'Generation failed. Check the feature log before retrying.'
  function setBusy(value) {
    busy = value
    calculate.disabled = value || !enabled
    generate.disabled = value || !plan
    for (const input of [shape, branchGeometry, branchScaffold, branchSizing, pathing, length, order, mechanics, connections]) input.disabled = value || !enabled
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
    status.textContent = branched() && branchGeometry.value === 'curved' && branchSizing.value === 'optimized'
      ? 'Comparing branch cross-sections, staple junctions and CanDo flexibility… This may take a few minutes.'
      : 'Comparing designs…'
    try {
      plan = await api.planGeneratedDesign(settings())
      if (!plan) { status.textContent = error(); return }
      if (curved() && plan.path_particle_ids) order.value = plan.path_particle_ids.map(id => particles.findIndex(p => p.id === id) + 1).join(', ')
      status.textContent = plan.alternatives.map(c => c.feasible === false
        ? `${c.scaffold_size}: unavailable`
        : `${c.scaffold_size}: ${c.section} · ${c.length_nm.toFixed(1)} nm${c.scaffold_size === plan.selected.scaffold_size && c.section === plan.selected.section && c.scaffold_used_nt === plan.selected.scaffold_used_nt ? ' · selected' : ''}`).join('\n')
      if (curved() && plan.selected.path_feature) status.textContent += `\nPath feature: ${plan.selected.path_feature === 'sweep' ? 'Sweep' : 'Bends'}`
      if (branched()) status.textContent += `\n${plan.selected.scaffold_used_nt} / ${plan.selected.scaffold_size} scaffold bases · ${plan.selected.unused_scaffold_nt ?? (plan.selected.scaffold_size - plan.selected.scaffold_used_nt)} unused.\n${plan.qualification || 'Experimental lattice branches; attachment fitting and CanDo validation run during generation.'}`
      if (branched() && plan.selected.sizing_validation) status.textContent += `\nSizing CanDo: ${plan.selected.sizing_validation.max_rmsf_nm.toFixed(2)} nm maximum core RMSF before attachments · ${plan.search.structural_candidates} candidates screened.`
      if (plan.mechanics) {
        const m = plan.mechanics
        status.textContent += `\nPredicted motion objective: ${(100 * m.improvement_fraction).toFixed(1)}% lower than the unreinforced core.\n${plan.selected.scaffold_used_nt} / ${plan.selected.scaffold_size} scaffold bases · ${m.candidates_evaluated} candidates compared.\nModel estimate; not experimentally calibrated.`
        if (!m.layers.length) status.textContent += '\nNo feasible reinforcement improvement was found in this search.'
        status.textContent += `\nPredicted aligned motion: ${m.predicted.aligned_rms_nm.toFixed(2)} nm RMS · worst pair distance: ${m.predicted.worst_pair_std_nm.toFixed(2)} nm SD.`
        if (['fem-linear', 'fem-nonlinear', 'oxdna'].includes(mechanics.value)) status.textContent += '\nValidation will start after generation; results appear in Simulations.'
      }
      status.title = [plan.reason,
        ...(curved() && plan.path_length_nm != null ? [`Planar path: ${plan.path_length_nm.toFixed(1)} nm · visit order: ${order.value}`] : []),
        `Maximum particle separation: ${plan.center_distance_nm.toFixed(2)} nm`,
        ...(plan.perimeter_alignment ? [`Perimeter alignment: ${plan.perimeter_alignment.aligned_edges} edges within ${plan.perimeter_alignment.tolerance_deg}°.`] : []),
        `${plan.selected.unused_scaffold_nt} scaffold bases remain unrouted. ${plan.mechanics || branched() ? 'Unused bases are not padded into end extensions.' : 'Extend beyond attachment sites to use most of the scaffold.'}`,
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
        status.textContent = result.generation.attachment_mode === 'blunt-end-assumed'
          ? `Added routed origami with ${result.generation.blunt_end_ports.length} blunt-end attachment faces. Particle centers preserved. Overhangs and NP binding remain unassigned.`
          : `Added ${items.length} connections. Particle centers preserved.`
        const selected = result.generation.selected
        if (branched() && selected) status.textContent += `\n${selected.scaffold_name}: ${selected.scaffold_used_nt} / ${selected.scaffold_size} scaffold bases · ${selected.section}.`
        const check = result.generation.structural_validation
        if (check) {
          status.textContent += `\nCanDo structural check: ${check.status}. Maximum core RMSF: ${check.max_rmsf_nm.toFixed(2)} nm.`
          if (check.warnings?.length) status.textContent += `\n${check.warnings.join('\n')}`
        }
        if (result.generation.validation_job) {
          const j = result.generation.validation_job
          status.textContent += `\n${j.engine} job ${j.job_id}: ${j.status}. See Simulations.\n${j.error || j.qualification}`
        }
        status.title = `${items.filter(c => c.reused).length} reused handles. Edit, scrub, or revert individual construction steps in the current loadout.`
      } else { status.textContent = error(); stage.textContent = 'Generation failed' }
    } catch (e) { status.textContent = e.message; stage.textContent = 'Generation failed'; plan = null }
    finally { setBusy(false) }
  } })
  shape.addEventListener('change', () => {
    branchNote.hidden = !branched()
    branchGeometryRow.hidden = !branched()
    branchSizingRow.hidden = !branched() || branchGeometry.value !== 'curved'
    branchScaffoldRow.hidden = branchSizingRow.hidden || branchSizing.value === 'fixed'
    pathRow.hidden = orderRow.hidden = mechanicsRow.hidden = !curved()
    rollRow.hidden = curved()
    invalidate()
    setBusy(false)
  })
  pathing.addEventListener('change', invalidate)
  mechanics.addEventListener('change', invalidate)
  connections.addEventListener('change', invalidate)
  branchGeometry.addEventListener('change', () => { updateBranchNote(); branchSizingRow.hidden = !branched() || branchGeometry.value !== 'curved'; branchScaffoldRow.hidden = branchSizingRow.hidden || branchSizing.value === 'fixed'; invalidate() })
  branchScaffold.addEventListener('change', invalidate)
  branchSizing.addEventListener('change', () => { branchScaffoldRow.hidden = branchSizingRow.hidden || branchSizing.value === 'fixed'; invalidate() })
  order.addEventListener('input', () => { orderEdited = !!order.value.trim() })
  for (const input of [roll, length, order]) input.addEventListener('input', invalidate)
  const modal = createModal({ title: 'Generate design', size: 'md', body, actions: [calculate, generate], onClose: () => !busy })
  if (connectivityPlan) {
    rollRow.hidden = true
    length.closest('.input-group').querySelector('.input-group__label').textContent = 'Assumed blunt-end duplex (bp)'
    connections.closest('.input-group').parentElement.hidden = true
  }
  modal.open()
  if (enabled) void calculatePlan()
  return modal
}
