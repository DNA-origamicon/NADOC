/** Temporary solid-rod generator; records construction in the current loadout. */
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'

export function showGenerateDesign({ api, store }) {
  const body = el('div')
  const state = store.getState()
  const particles = state.currentDesign?.nanoparticles?.filter(p => p.kind === 'gold_nanosphere') ?? []
  const platform = particles.length > 2
  const enabled = !state.assemblyActive && !!state.currentDesign && [2, 3, 4].includes(particles.length)
  const rotationLabel = platform ? 'Platform rotation within fitted plane (degrees)' : 'Rotation around particle axis (degrees)'
  body.append(el('p', { text: enabled
    ? `Build a ${platform ? 'solid platform for the ' + particles.length : 'straight solid rod for the two'} gold nanoparticles, preserving their centers and the current lattice. Construction is added to the current loadout with individual editable history steps. Existing geometry is preserved.`
    : 'Open a part containing two, three, or four gold nanoparticles to use this generator.' }))
  if (platform) body.append(el('p', { text: 'Fit one plane to the particle centers and place all connections on the same side. Noncoplanar centers are accepted only if every duplex can reach and the DNA clears every gold core.' }))
  body.append(el('p', { text: 'Temporary geometric prototype. Stiffness, RMSF, and sequence thermodynamics are not predicted.' }))
  const roll = el('input', { attrs: { type: 'number', min: '-180', max: '180', step: '1', value: '0', 'aria-label': rotationLabel } })
  const length = el('input', { attrs: { type: 'number', min: '12', max: '60', step: '1', value: '18', 'aria-label': 'New duplex length (bp)' } })
  for (const [text, input] of [[rotationLabel, roll], ['New duplex length (bp)', length]]) {
    const label = el('label', { attrs: { style: 'display:flex;justify-content:space-between;gap:16px;margin:12px 0' }, children: [text, input] })
    input.disabled = !enabled
    body.append(label)
  }
  body.append(el('p', { text: `Compatible handles retain their sequence and length. Otherwise, create one direct-thiol handle per particle. Extend the ${platform ? 'platform' : 'rod'} beyond the attachment sites to use most of the scaffold.` }))
  const status = el('div', { attrs: { role: 'status', 'aria-live': 'polite', style: 'white-space:pre-line;margin-top:14px' } })
  body.append(status)
  let plan = null
  let busy = false
  const settings = () => ({ roll_deg: Number(roll.value), duplex_bp: Number(length.value), extend_rod: true })
  const valid = () => roll.value !== '' && length.value !== '' && roll.checkValidity() && length.checkValidity()
  const error = () => api.lastErrorMessage?.() || 'Generation failed. The current design is unchanged.'
  function setBusy(value) {
    busy = value
    calculate.disabled = value || !enabled
    generate.disabled = value || !plan
    roll.disabled = value || !enabled
    length.disabled = value || !enabled
  }
  async function calculatePlan() {
    plan = null
    if (!valid()) { status.textContent = 'Enter a rotation from −180 to 180° and an integer duplex length from 12 to 60 bp.'; generate.disabled = true; return }
    setBusy(true)
    status.textContent = 'Comparing routed 7249 and 8064 scaffold designs…'
    try {
      plan = await api.planGeneratedDesign(settings())
      if (!plan) { status.textContent = error(); return }
      const lines = plan.alternatives.map(c => c.feasible === false
        ? `${c.scaffold_size}: no supported cross-section fits.`
        : `${c.scaffold_size}: ${c.section}, ${c.helix_count} helices, ${c.length_nm.toFixed(1)} nm long; ${c.scaffold_used_nt} nt routed.`)
      status.textContent = [
        `${platform ? 'Maximum particle separation' : 'Particle separation'}: ${plan.center_distance_nm.toFixed(2)} nm · ${plan.lattice_type}`,
        ...(platform ? [`Maximum distance from fitted plane: ${(plan.plane_deviation_nm ?? 0).toFixed(2)} nm`] : []),
        ...lines, plan.reason,
        `${plan.selected.unused_scaffold_nt} scaffold bases remain unrouted and are not represented as a tail.`,
        plan.attachment_status,
      ].join('\n\n')
    } catch (e) { status.textContent = e.message; plan = null }
    finally { setBusy(false) }
  }
  const calculate = createButton({ label: 'Calculate design', disabled: !enabled, onClick: calculatePlan })
  const generate = createButton({ label: 'Generate in current loadout', variant: 'primary', disabled: true, onClick: async () => {
    if (!plan || busy) return
    setBusy(true)
    status.textContent = 'Routing staples, building duplexes, and checking fixed-center attachment geometry…'
    try {
      const result = await api.generateDesign(settings(), plan.revision, plan.doc_id)
      plan = null
      if (result) {
        const items = result.generation.connections
        status.textContent = `Added ${items.length} connections to the current loadout (${items.filter(c => c.reused).length} reused handles). ${platform ? 'All' : 'Both'} particle centers are unchanged. Edit, scrub, or revert the individual construction steps in the feature log.`
      } else status.textContent = error()
    } catch (e) { status.textContent = e.message; plan = null }
    finally { setBusy(false) }
  } })
  for (const input of [roll, length]) input.addEventListener('input', () => {
    plan = null
    generate.disabled = true
    status.textContent = 'Settings changed. Calculate again before generating.'
  })
  const modal = createModal({ title: 'Generate design', size: 'md', body,
    actions: [calculate, generate], onClose: () => !busy })
  modal.open()
  if (enabled) void calculatePlan()
  return modal
}
