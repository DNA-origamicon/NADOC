/** Explicit checkpoint action shared by the two presentation sidebars. */
export function createPresentationCheckpointButton({ document = globalThis.document, save, available = () => true }) {
  const root = document.createElement('div')
  const button = document.createElement('button')
  button.type = 'button'
  button.textContent = 'Save to feature log'
  button.dataset.action = 'save-presentation-state'
  const status = document.createElement('span')
  status.setAttribute('role', 'status')
  root.style.cssText = 'display:flex;align-items:center;gap:8px;margin:6px 0'
  root.append(button, status)
  let pending = false
  const refresh = () => { button.disabled = pending || !available() }
  button.addEventListener('click', async () => {
    if (pending || !available()) return
    pending = true; refresh(); status.textContent = 'Saving…'
    try {
      await save()
      status.textContent = 'Saved'
    } catch (error) { status.textContent = error.message || 'Could not save state' }
    finally { pending = false; refresh() }
  })
  refresh()
  return { root, refresh }
}
