/** Whole-scaffold target selection, shared by 3D and cadnano dialogs. */
import { showConfirm } from './primitives/confirm.js'
import { canonicalSelection } from '../scene/selection_model.js'
import { countScaffoldNt } from '../scene/scaffold_assign.js'

export function selectedSequenceTarget(state, explicitStrandId = null) {
  if (explicitStrandId != null) return `strand:${explicitStrandId}`
  const design = state.currentDesign ?? state.design
  const ref = canonicalSelection(state).primary
  const id = ref?.kind === 'strand' ? ref.id : ref?.kind === 'domain' ? ref.strandId : null
  if (id && design?.strands?.some(s => s.id === id && s.strand_type === 'scaffold' && !s.is_reference)) return `strand:${id}`
  if (ref?.kind === 'cluster') return `cluster:${ref.id}`
  if (!ref && state.activeClusterId) return `cluster:${state.activeClusterId}`
  return 'default'
}

export function scaffoldScope(design, value) {
  const scaffolds = (design.strands ?? []).filter(s => s.strand_type === 'scaffold' && !s.is_reference)
  if (value === 'default') return { strands: scaffolds.slice(0, 1), options: { strandId: null } }
  const id = value.slice(value.indexOf(':') + 1)
  if (value.startsWith('strand:')) {
    const strand = scaffolds.find(s => s.id === id)
    if (!strand) throw new Error('Selected scaffold is unavailable.')
    return { strands: [strand], options: { strandId: id } }
  }
  const cluster = design.cluster_transforms?.find(c => c.id === id)
  if (!cluster) throw new Error('Selected cluster is unavailable.')
  const coverage = new Map((cluster.helix_ids ?? []).map(h => [h, 'whole']))
  const ranges = new Map()
  for (const ref of cluster.domain_ids ?? []) {
    const d = design.strands?.find(s => s.id === ref.strand_id)?.domains?.[ref.domain_index]
    if (!d) continue
    if (!ranges.has(d.helix_id)) ranges.set(d.helix_id, [])
    ranges.get(d.helix_id).push([Math.min(d.start_bp, d.end_bp), Math.max(d.start_bp, d.end_bp)])
  }
  for (const [h, r] of ranges) coverage.set(h, r)
  const strands = scaffolds.filter(s => {
    let touches = false, contained = s.domains.length > 0
    for (const d of s.domains) {
      const claim = coverage.get(d.helix_id) ?? []
      if (claim === 'whole') { touches = true; continue }
      const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
      touches ||= claim.some(([a, b]) => a <= hi && lo <= b)
      let cursor = lo
      for (const [a, b] of [...claim].sort((a, b) => a[0] - b[0])) {
        if (a > cursor) break
        cursor = Math.max(cursor, b + 1)
      }
      contained &&= cursor > hi
    }
    if (touches && !contained) throw new Error('A scaffold crosses this cluster boundary. Choose that whole scaffold strand explicitly.')
    return contained
  })
  if (!strands.length) throw new Error('Selected cluster contains no editable scaffold strands.')
  return { strands, options: { strandId: null, clusterId: id } }
}

export function mountScaffoldSequenceTarget({ body, design, state, explicitStrandId, onChange }) {
  body.querySelector('[data-scaffold-target]')?.remove()
  const wrapper = document.createElement('div')
  wrapper.dataset.scaffoldTarget = ''
  const label = document.createElement('label')
  label.textContent = 'Assign to '
  const select = document.createElement('select')
  select.className = 'select'
  select.setAttribute('aria-label', 'Scaffold sequence target')
  const choices = [['default', 'Default — first editable scaffold'],
    ...(design.cluster_transforms ?? []).map(c => [`cluster:${c.id}`, `Cluster: ${c.name || c.id}`]),
    ...(design.strands ?? []).filter(s => s.strand_type === 'scaffold' && !s.is_reference)
      .map(s => [`strand:${s.id}`, `Scaffold: ${s.name || s.id} (${countScaffoldNt(design, s.id)} nt)`])]
  for (const [value, text] of choices) select.add(new Option(text, value))
  const wanted = selectedSequenceTarget(state, explicitStrandId)
  if (!choices.some(([v]) => v === wanted)) select.add(new Option('Selected target unavailable', wanted))
  select.value = wanted
  const note = document.createElement('p')
  note.className = 'tool-help'
  label.append(select); wrapper.append(label, note); body.prepend(wrapper)
  const read = () => scaffoldScope(design, select.value)
  const update = () => {
    try {
      const { strands } = read()
      const lengths = strands.map(s => countScaffoldNt(design, s.id))
      note.textContent = select.value.startsWith('cluster:')
        ? `${strands.length} scaffold strand(s). The sequence restarts at each strand’s existing 5′ end. Scaffolds are not connected or rerouted.`
        : 'Assign the whole scaffold from its existing 5′ end.'
      body.querySelector('#asc-length-line').textContent = lengths.length > 1
        ? `Scaffolds: ${lengths.length}; lengths: ${lengths.join(', ')} nt. Short-sequence warnings below refer to the longest strand.`
        : `Scaffold length: ${lengths[0] ?? 0} nt`
      onChange(Math.max(0, ...lengths))
    } catch (error) { note.textContent = error.message; onChange(0) }
  }
  select.addEventListener('change', update)
  update()
  return { read }
}

export async function confirmScaffoldScope(scope) {
  if (scope.strands.length <= 1) return true
  return showConfirm({ title: 'Assign Scaffold Sequence',
    message: 'Multiple scaffolds detected, assign sequence to all?',
    confirmLabel: 'Yes', cancelLabel: 'No',
  })
}

export async function confirmedScaffoldOptions(target, toast) {
  try {
    const scope = target.read()
    return await confirmScaffoldScope(scope) ? scope.options : null
  } catch (error) { toast(error.message, { severity: 'error' }); return null }
}
