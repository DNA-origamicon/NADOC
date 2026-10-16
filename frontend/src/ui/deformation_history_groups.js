/** Private named-group controls; placement owners and canonical selection are untouched. */
import { el } from './primitives/dom.js'

export function createHistoryGroupControls({ container, session, primitiveLabels, onChange }) {
  const targets = session.operation.targets
  if (!Array.isArray(targets) || !targets.some(target => target.kind === 'part_group')) return null
  const groups = session.design.group_organization?.groups ?? []
  const names = new Map(groups.map(group => [group.id, group.name || 'Group']))
  const editable = session.capabilities?.change_targets === true && targets.every(target => target.kind === 'part_group')
  let active = true, touched = false, selected = targets.map(target => target.id)
  container.hidden = false
  container.replaceChildren(el('div', { className: 'mr-section-label', text: editable ? 'Named groups' : 'Current selection (fixed)' }))
  const message = el('p', { className: 'dim', attrs: { 'aria-live': 'polite', hidden: true }, text: 'Select at least one named group.' })
  if (editable) {
    for (const group of groups) {
      const checkbox = el('input', { attrs: { type: 'checkbox', value: group.id } })
      checkbox.checked = selected.includes(group.id)
      checkbox.addEventListener('change', () => {
        if (!active) return
        touched = true
        selected = [...container.querySelectorAll('input:checked')].map(input => input.value)
        message.hidden = selected.length > 0
        onChange()
      })
      const count = group.domain_ids?.length ? `${group.domain_ids.length} domains` : `${group.helix_ids.length} helices`
      const label = el('label', { className: 'mr-selection-item' })
      label.append(checkbox, document.createTextNode(` ${names.get(group.id)} (${count})`)); container.append(label)
    }
    container.append(message)
  } else {
    for (const target of targets) {
      const labels = target.kind === 'part_group' ? [names.get(target.id) ?? target.id] : primitiveLabels([target])
      for (const label of labels) container.append(el('div', { className: 'mr-selection-item', text: label }))
    }
  }
  return {
    valid: () => !editable || selected.length > 0,
    patch: () => editable && touched ? { targets: selected.map(id => ({ kind: 'part_group', id })) } : {},
    dispose() { active = false },
  }
}
