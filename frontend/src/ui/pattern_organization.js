import { el } from './primitives/dom.js'
import { toolSection } from './tool_sections.js'

/** Metadata only: placements determine copied geometry; groups never do. */
export function patternOrganizationChoices(design, placementIds) {
  if (!design?.group_organization) return null
  const groups = design.group_organization.groups ?? [], selected = new Set(placementIds)
  const reference = new Set(), authored = new Set()
  // Match Design.reference_helix_ids: mixed active/reference helices remain active.
  for (const strand of design.strands ?? []) for (const domain of strand.domains ?? []) {
    (strand.is_reference ? reference : authored).add(domain.helix_id)
  }
  for (const id of authored) reference.delete(id)
  const copied = new Set((design.cluster_transforms ?? []).filter(p => selected.has(p.id))
    .flatMap(p => p.helix_ids ?? []).filter(id => !reference.has(id)))
  const strands = new Map((design.strands ?? []).map(s => [s.id, s]))
  const required = new Set()
  for (const op of design.deformations ?? []) {
    if (!(op.affected_helix_ids ?? []).some(id => copied.has(id))) continue
    for (const target of op.targets ?? []) if (target.kind === 'part_group') required.add(target.id)
  }
  const choices = groups.filter(group => required.has(group.id) || (group.domain_ids?.length
    ? group.domain_ids.some(ref => copied.has(strands.get(ref.strand_id)?.domains?.[ref.domain_index]?.helix_id))
    : (group.helix_ids ?? []).some(id => copied.has(id))))
  const known = new Set(groups.map(g => g.id))
  return { groups: choices, defaultIds: choices.map(g => g.id), requiredIds: [...required],
    missingIds: [...required].filter(id => !known.has(id)) }
}

/** Recomputed only when the placement selection changes, never on animation. */
export function createPatternOrganizationControls(design, placementIds, onChange) {
  if (!design?.group_organization) return null
  const list = el('div', { className: 'tool-scroll-list' })
  const message = el('p', { className: 'tool-help' })
  const element = toolSection('Copy named groups', [el('p', { className: 'tool-help',
    text: 'Copies keep the selected groups’ members within the copied placements. Original groups stay unchanged. Groups used by copied deformations are required.' }), list, message])
  const decisions = new Map()
  let choices
  function update(ids) {
    choices = patternOrganizationChoices(design, ids)
    const required = new Set(choices.requiredIds)
    list.replaceChildren(...choices.groups.map(group => {
      const input = el('input', { attrs: { type: 'checkbox', 'aria-label': `Copy group ${group.name || group.id}` } })
      input.checked = required.has(group.id) || decisions.get(group.id) !== false
      input.disabled = required.has(group.id)
      if (input.disabled) input.title = 'Required by a copied deformation'
      input.addEventListener('change', () => { decisions.set(group.id, input.checked); onChange() })
      return el('label', { className: 'cp-snap', children: [input, group.name || group.id] })
    }))
    message.textContent = choices.missingIds.length ? `Missing required named groups: ${choices.missingIds.join(', ')}. Repair the deformation references before copying.` : choices.groups.length ? '' : 'No named groups intersect these placements.'
    message.hidden = !message.textContent
  }
  update(placementIds)
  return { element, update,
    valid: () => choices.missingIds.length === 0,
    params: () => ({ _organization_copy: { version: 1, group_ids: choices.groups
      .filter(g => choices.requiredIds.includes(g.id) || decisions.get(g.id) !== false).map(g => g.id) } }),
    restoreDisabled() {
      for (const [i, input] of [...list.querySelectorAll('input')].entries()) input.disabled = choices.requiredIds.includes(choices.groups[i].id)
    },
  }
}
