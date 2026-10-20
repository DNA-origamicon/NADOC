import { createModal } from './modal.js'
import { createButton } from './button.js'
import { el } from './dom.js'
import { getDocId } from '../../shared/doc_id.js'

/** Move a captured row through the existing private evaluation/commit lifecycle. */
export function showFeatureReorder(options) { return showHistoryChange(options) }
export function showFeatureSuppression(options) { return showHistoryChange({ ...options, suppression: true }) }

function showHistoryChange({ store, api, source, rowIndex, suppression = false, getDocumentId = getDocId }) {
  const suppressed = !source.feature_log[rowIndex].suppressed
  const action = suppression ? (suppressed ? 'Suppress' : 'Unsuppress') : 'Move'
  const transport = api.partRepairAPI
  const context = { docId: getDocumentId(), designId: source.id,
    loadoutId: source.active_loadout_id ?? null, revision: api.currentRevisionWatermark() }
  const current = () => store.getState().currentDesign === source && !store.getState().assemblyActive
    && getDocumentId() === context.docId && api.currentRevisionWatermark() === context.revision
    && !store.getState().featureSeekPending
  const loadout = source.loadouts?.find(item => item.id === context.loadoutId)
  if (!current() || loadout?.protected || (source.feature_log_cursor ?? -1) !== -1
      || source.feature_log_sub_cursor != null) throw new Error('Return to editable current history before changing a feature.')
  const select = el('select', { attrs: { 'aria-label': 'New feature position' } })
  source.feature_log.forEach((entry, index) => select.append(el('option', {
    text: `F${index + 1}: ${entry.label || entry.feature_type}`, attrs: { value: String(index) },
  })))
  select.value = String(rowIndex)
  const status = el('p', { attrs: { role: 'status' } })
  const body = el('div', { children: [el('p', { text: suppression
    ? 'The saved feature definition is retained. The model will regenerate; unresolved dependencies refuse the change.'
    : 'Choose the final position. The model will regenerate in this order; moves with unresolved dependencies are refused.' }), ...(suppression ? [] : [select]), status] })
  let closed = false, busy = false, committing = false, adopting = false, jobId = null, unsubscribe
  const discard = id => { if (id) Promise.resolve(transport.cancel(id, { context })).catch(() => {}) }
  const cancel = createButton({ label: 'Cancel', onClick: () => modal.close() })
  const apply = createButton({ label: action, variant: 'primary', onClick: async () => {
    if (busy || closed || !current()) return
    busy = true; apply.disabled = true; select.disabled = true
    status.textContent = 'Checking dependencies and regenerating…'
    try {
      const started = await transport.start({ operation: suppression ? 'suppress' : 'reorder', index: rowIndex,
        ...(suppression ? { suppressed } : { destination: Number(select.value) }), expected_revision: context.revision }, { context })
      jobId = started.job_id
      if (closed || !current()) { discard(jobId); return }
      let response
      do {
        response = await transport.poll(jobId, { context })
        if (closed || !current()) { discard(jobId); return }
        if (response.stale) throw new Error('The part changed. Reopen the history dialog.')
        if (response.status === 'running') await new Promise(resolve => setTimeout(resolve, 200))
      } while (response.status === 'running')
      if (response.result?.status !== 'ready') {
        const issue = response.result?.issues?.[0]
        throw new Error(issue?.detail?.detail ?? issue?.detail?.message ?? issue?.detail ?? 'This history change cannot regenerate.')
      }
      committing = true; cancel.disabled = true
      status.textContent = 'Applying history change…'
      const receipt = await transport.commit(jobId, { context })
      const result = await transport.refreshCommitted(receipt, { context })
      if (!current() || closed) return
      adopting = true
      transport.apply(result, context)
      committing = false
      modal.close()
    } catch (error) {
      discard(jobId)
      if (!closed) status.textContent = error.message
    } finally {
      committing = false; busy = false; cancel.disabled = false
      apply.disabled = !suppression && Number(select.value) === rowIndex; select.disabled = false
    }
  } })
  apply.disabled = !suppression
  select.addEventListener('change', () => { apply.disabled = busy || Number(select.value) === rowIndex })
  const modal = createModal({ title: `${action} F${rowIndex + 1}`, size: 'sm', body, actions: [cancel, apply],
    onClose: () => {
      if (committing && current()) return false
      closed = true; unsubscribe?.(); discard(jobId)
    } })
  modal.root.setAttribute('aria-label', `${action} F${rowIndex + 1}`)
  modal.open()
  unsubscribe = store.subscribe(() => { if (!adopting && !current()) modal.close() })
  return modal
}
