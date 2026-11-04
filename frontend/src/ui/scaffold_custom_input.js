import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

export const normalizeScaffoldSequence = text => String(text ?? '').replace(/\s/g, '').toUpperCase()

export function scaffoldSequenceError(text) {
  const sequence = normalizeScaffoldSequence(text)
  if (!sequence) return 'Paste a custom sequence containing A, T, G, and C bases.'
  const invalid = [...new Set(sequence.replace(/[ATGC]/g, ''))]
  return invalid.length ? `Only A, T, G, and C bases are allowed. Invalid characters: ${invalid.slice(0, 12).map(c => JSON.stringify(c)).join(', ')}${invalid.length > 12 ? '…' : ''}.` : null
}

export function scaffoldSequenceChoice(root) {
  const scaffoldName = root.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
  const customRaw = scaffoldName === 'custom' ? normalizeScaffoldSequence(root.querySelector('#asc-custom-seq')?.value) : ''
  return { scaffoldName, customRaw }
}

const popups = new WeakMap()
export function showScaffoldSequenceError(root, message) {
  if (popups.get(root)?.isOpen()) return
  const body = document.createElement('p')
  body.textContent = message
  const popup = createModal({ title: 'Invalid scaffold sequence', body, className: 'scaffold-sequence-error',
    actions: [createButton({ label: 'OK', variant: 'primary', onClick: () => popup.close() })],
    onClose: () => { popups.delete(root); root.querySelector('#asc-custom-seq')?.focus() } })
  // The standalone Origami Editor uses a legacy overlay at z-index 9000.
  popup.overlay.style.zIndex = '10001'
  popup.root.addEventListener('keydown', event => {
    event.stopPropagation()
    if (event.key === 'Escape') { event.preventDefault(); popup.close() }
  })
  popups.set(root, popup)
  popup.open()
  popup.actions.querySelector('button')?.focus()
}

export function updateScaffoldCustomInput(root) {
  const { scaffoldName, customRaw } = scaffoldSequenceChoice(root)
  const custom = scaffoldName === 'custom'
  const textarea = root.querySelector('#asc-custom-seq')
  if (textarea) textarea.disabled = !custom
  const panel = root.querySelector('#asc-custom-panel')
  if (panel) panel.hidden = !custom
  const count = root.querySelector('#asc-custom-char-count')
  if (count) count.textContent = `${customRaw.length} nt`
  const error = root.querySelector('#asc-custom-error')
  const message = custom && customRaw ? scaffoldSequenceError(customRaw) : null
  if (error) { error.textContent = message ?? ''; error.style.display = message ? 'inline' : 'none' }
}

export function wireScaffoldCustomInput(root, onChange) {
  const update = () => { updateScaffoldCustomInput(root); onChange() }
  root.querySelectorAll('input[name="asc-scaffold"]').forEach(radio => radio.addEventListener('change', update))
  root.querySelector('#asc-custom-seq')?.addEventListener('input', event => {
    update()
    const { scaffoldName, customRaw } = scaffoldSequenceChoice(root)
    const error = scaffoldName === 'custom' ? scaffoldSequenceError(customRaw) : null
    if (error && event.inputType === 'insertFromPaste') showScaffoldSequenceError(root, error)
  })
  updateScaffoldCustomInput(root)
}

export function validateScaffoldSequenceChoice(root) {
  const choice = scaffoldSequenceChoice(root)
  if (choice.scaffoldName === 'custom') {
    const error = scaffoldSequenceError(choice.customRaw)
    if (error) { showScaffoldSequenceError(root, error); return null }
  }
  return choice
}
