import { createRecipeFileRecoveryEndpoints } from '../api/part_recipe_file_endpoints.js'
import { createRecipeFileRecoveryController } from '../features/part_recipe_file_controller.js'
import { createModal, createButton, el } from './primitives/index.js'

/** Download the worker's exact text; no active document export or JSON rewrite. */
export function downloadRecoveredRecipe(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const anchor = el('a', { attrs: { href: url, download: filename } })
  try { document.body.appendChild(anchor); anchor.click() }
  finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 0) }
}

/** Local-file recovery is deliberately independent of the open part/workspace. */
export function initRecipeFileRecovery({ api, download = downloadRecoveredRecipe, hashFile, hashText } = {}) {
  const menu = document.getElementById('menu-file-recover-recipe')
  if (!menu) return null
  const controller = createRecipeFileRecoveryController({ api: api ?? createRecipeFileRecoveryEndpoints(), download, hashFile, hashText })
  let displayedReview = null, disposed = false
  const choices = new Map()
  const input = el('input', { attrs: { type: 'file', accept: '.nadoc', 'aria-label': 'Original NADOC file' },
    on: { change: () => controller.chooseFile(input.files?.[0] ?? null) } })
  const filename = el('p'), status = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const issues = el('ul'), exclusions = el('ul'), offers = el('div')
  offers.style.cssText = 'max-height:240px;overflow:auto'
  const ackLabel = 'I understand the excluded data is retained only in the original file'
  const acknowledgment = el('input', { attrs: { type: 'checkbox', 'aria-label': ackLabel },
    on: { change: () => controller.acknowledgeExclusions(acknowledgment.checked) } })
  const review = el('section', { children: [
    el('h3', { text: 'Review the recovery' }),
    el('p', { text: 'Choose the group repairs to apply. The recovered copy rebuilds from feature inputs; it does not compare against the original geometry.' }),
    offers, el('p', { text: 'Only recorded construction inputs are recovered. Saved display settings, simulation state and pending repair drafts are not copied; keep the original file.' }),
    el('p', { text: 'These fields are excluded from the recovered copy:' }), exclusions,
    el('label', { children: [acknowledgment, ` ${ackLabel}`] }),
  ] })
  function action(callback) {
    try { callback() } catch (error) { status.textContent = error.message }
  }
  const inspect = createButton({ label: 'Inspect file', onClick: () => { void controller.inspect() } })
  const evaluate = createButton({ label: 'Evaluate recovery', variant: 'primary', onClick: () => { void controller.evaluate() } })
  const save = createButton({ label: 'Download recovered copy', variant: 'primary', onClick: () => action(() => controller.download()) })
  const cancel = createButton({ label: 'Cancel', onClick: () => controller.cancel() })
  const modal = createModal({ title: 'Recover recipe from file', size: 'lg', body: [
    el('p', { text: 'Choose a local .nadoc file up to 1,500,000 bytes. Recovery creates a separate download. Your original file and open document remain unchanged.' }),
    el('p', { text: 'This recovery supports recipes that start from an empty part and need the offered group repairs. Assemblies and other broken file formats are outside this scope.' }),
    input, filename, review, status, issues,
  ], actions: [createButton({ label: 'Close', onClick: () => modal.close() }), cancel, inspect, evaluate, save],
  onClose: () => { controller.chooseFile(null); input.value = '' } })

  function render(state) {
    filename.textContent = state.file ? `${state.file.name} (${state.file.size.toLocaleString()} bytes)` : 'No file selected'
    review.hidden = !state.review
    if (displayedReview !== state.review) {
      displayedReview = state.review; choices.clear(); offers.replaceChildren(); exclusions.replaceChildren()
      for (const offer of state.review?.upgrades ?? []) {
        const checkbox = el('input', { attrs: { type: 'checkbox', 'aria-label': `${offer.label}: ${offer.action.feature_id}` },
          on: { change: () => {
            try { controller.selectUpgrade(offer, checkbox.checked) }
            catch (error) { render(controller.getState()); status.textContent = error.message }
          } } })
        choices.set(offer.action.feature_id, checkbox)
        offers.appendChild(el('div', { children: [el('label', { children: [checkbox, ` ${offer.label} — ${offer.action.feature_id}`] })] }))
      }
      for (const field of state.review?.recovery.excluded_fields ?? []) exclusions.appendChild(el('li', { text: field }))
      if (state.review && !exclusions.childElementCount) exclusions.appendChild(el('li', { text: 'No additional fields were present.' }))
    }
    const selected = new Set(state.actions.map(item => item.feature_id))
    for (const [id, checkbox] of choices) { checkbox.checked = selected.has(id); checkbox.disabled = !!state.busy }
    acknowledgment.checked = state.acknowledged; acknowledgment.disabled = !!state.busy
    inspect.disabled = !state.file || !!state.busy
    evaluate.disabled = !state.review || !state.actions.length || !state.acknowledged || !!state.busy
    save.disabled = !state.ready || !!state.busy; cancel.disabled = !state.busy
    status.textContent = state.error ?? (state.busy === 'inspect' ? 'Inspecting the original recipe…'
      : state.busy === 'recover' ? 'Regenerating and checking the recovered copy…'
        : state.ready ? 'The recovered copy passed regeneration and structural checks. Download it to review separately.'
          : state.review ? `${state.actions.length} of ${state.review.upgrades.length} repairs selected (maximum 64).` : '')
    issues.replaceChildren()
    for (const issue of state.issues.slice(0, 100)) {
      const text = [issue.code, issue.feature_id, issue.detail ?? issue.message].filter(value => typeof value === 'string').join(': ')
      issues.appendChild(el('li', { text: text.slice(0, 2048) }))
    }
    if (state.issues.length > 100) issues.appendChild(el('li', { text: `${state.issues.length - 100} further issues were reported.` }))
  }
  const unsubscribe = controller.subscribe(render)
  const open = () => { if (!disposed) { render(controller.getState()); modal.open() } }
  menu.addEventListener('click', open)
  return { controller, open, close: () => modal.close(), dispose() {
    if (disposed) return
    modal.close(); disposed = true; unsubscribe(); controller.dispose(); menu.removeEventListener('click', open)
  } }
}
