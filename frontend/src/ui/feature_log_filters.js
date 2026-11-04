import { createButton } from './primitives/button.js'
import './feature_log_filters.css'
import { docKey } from '../shared/doc_id.js'

/** Visibility preferences never alter the recipe or its seek indices. */
export function createFeatureLogFilters({ onChange }) {
  const values = { fineRouting: true, documentOps: false }
  const preferenceKey = docKey('nadoc:feature-log-filters')
  const readPreferences = () => {
    try {
      const saved = JSON.parse(localStorage.getItem(preferenceKey) ?? '{}')
      for (const key of Object.keys(values)) if (typeof saved?.[key] === 'boolean') values[key] = saved[key]
    } catch { /* Storage is optional. */ }
  }
  readPreferences()
  const inputs = new Map()
  const root = document.createElement('div')
  root.className = 'fl-filter'
  const button = createButton({ label: 'filter', size: 'sm', className: 'fl-log-action',
    onClick: () => setOpen(popup.hidden) })
  button.setAttribute('aria-expanded', 'false')
  const popup = document.createElement('div')
  popup.className = 'fl-filter-popup'
  popup.hidden = true
  popup.setAttribute('role', 'group')
  popup.setAttribute('aria-label', 'Feature log filters')
  function setOpen(open, focusButton = false) {
    popup.hidden = !open
    button.setAttribute('aria-expanded', String(open))
    if (open) popup.querySelector('input').focus()
    else if (focusButton) button.focus()
  }
  for (const [key, label, disabled] of [
    ['fineRouting', 'Fine routing', false],
    ['documentOps', 'Document ops', false],
    ['annotations', 'Annotations and visuals', true],
  ]) {
    const row = document.createElement('label')
    const input = document.createElement('input')
    input.type = 'checkbox'
    input.checked = values[key] ?? false
    input.disabled = disabled
    if (disabled) row.title = 'Not yet available'
    inputs.set(key, input)
    input.addEventListener('change', () => {
      values[key] = input.checked
      try { localStorage.setItem(preferenceKey, JSON.stringify(values)) } catch { /* Storage is optional. */ }
      onChange()
    })
    row.append(input, document.createTextNode(label))
    popup.append(row)
  }
  function outside(event) { if (!root.contains(event.target)) setOpen(false) }
  function keydown(event) {
    if (event.key === 'Escape' && !popup.hidden) { event.stopPropagation(); setOpen(false, true) }
  }
  function focusout(event) { if (!root.contains(event.relatedTarget)) setOpen(false) }
  function storage(event) {
    if (event.key !== preferenceKey) return
    readPreferences()
    for (const [key, input] of inputs) if (!input.disabled) input.checked = values[key]
    onChange()
  }
  window.addEventListener('storage', storage)
  document.addEventListener('pointerdown', outside)
  root.addEventListener('keydown', keydown)
  root.addEventListener('focusout', focusout)
  root.append(button, popup)
  return { root, values, dispose() { window.removeEventListener('storage', storage); document.removeEventListener('pointerdown', outside); root.remove() } }
}

/** A separate ordered journal: document actions are not geometry seek targets. */
export function renderDocumentOperations(host, design, visible) {
  host.replaceChildren()
  host.hidden = !visible
  if (!visible) return
  const heading = document.createElement('div')
  heading.className = 'fl-document-heading'
  heading.textContent = 'Document ops'
  host.append(heading)
  const names = new Map()
  const entries = design?.document_history ?? []
  for (const entry of entries) {
    const p = entry.params ?? {}
    const previousName = names.get(p.id) ?? 'loadout'
    let label
    switch (entry.kind) {
      case 'loadout-initialize': label = `Initialize loadout: ${p.name}`; break
      case 'loadout-create': label = `Create loadout: ${p.name}`; break
      case 'loadout-rename': label = `Rename loadout: ${previousName} → ${p.name}`; break
      case 'loadout-select': label = `Select loadout: ${previousName}`; break
      case 'loadout-delete': label = `Delete loadout: ${previousName}`; break
      case 'document-metadata': {
        const changes = p.changes ?? {}
        label = Object.entries(changes).map(([key, value]) => key === 'name'
          ? `Rename document: ${p.before?.name ?? ''} → ${value}`
          : `Update ${key}: ${Array.isArray(value) ? value.join(', ') : value}`).join('; ')
        break
      }
      default: continue
    }
    if (p.name) names.set(p.id, p.name)
    const row = document.createElement('div')
    row.className = 'fl-document-row'
    row.textContent = label
    host.append(row)
  }
  if (host.children.length === 1) {
    const empty = document.createElement('div')
    empty.textContent = 'No recorded document operations.'
    host.append(empty)
  }
}
