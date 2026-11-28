import { featureLabels } from '../../features/feature_labels.js'
import { createModal } from './modal.js'
import { createButton } from './button.js'
import { createSelect } from './input.js'
import { el } from './dom.js'
import { historyDialogHost } from './history_dialog_host.js'
import { getDocId } from '../../shared/doc_id.js'

/** Move a captured row through the existing private evaluation/commit lifecycle. */
export function showFeatureReorder(options) { return showHistoryChange(options) }
export function showFeatureSuppression(options) { return showHistoryChange({ ...options, suppression: true }) }
export function showFeatureInputChange(options) { return showHistoryChange(options) }
export function showFeatureDeletion(options) { return showHistoryChange({ ...options, deletion: true }) }

function showHistoryChange({ store, api, source, rowIndex, suppression = false, deletion = false, inputs, assembly = false,
  instanceId, assemblySource, isTargetCurrent, getDocumentId = getDocId }) {
  const suppressed = !source.feature_log[rowIndex].suppressed
  const editing = inputs !== undefined
  const action = deletion ? 'Delete' : editing ? 'Apply edit' : suppression ? (suppressed ? 'Suppress' : 'Unsuppress') : 'Move'
  const { context, transport, current, requiresTail } = historyDialogHost({ store, api, source, assembly, instanceId, assemblySource, isTargetCurrent, getDocumentId })
  const loadout = source.loadouts?.find(item => item.id === context.loadoutId)
  if (!current() || loadout?.protected || ((!suppression || requiresTail) && ((source.feature_log_cursor ?? -1) !== -1
      || source.feature_log_sub_cursor != null))) throw new Error('Return to editable current history before changing a feature.')
  const labels = featureLabels(source.feature_log)
  const select = createSelect({
    options: labels.map((label, index) => ({ label, value: String(index) })),
    value: String(rowIndex),
  })
  select.setAttribute('aria-label', 'New feature position')
  select.style.width = '100%'
  select.style.minWidth = '0'
  const status = el('p', { attrs: { role: 'status' } })
  const body = el('div', { children: [el('p', { text: deletion
    ? 'Delete this feature and regenerate all later features. Unresolved dependencies refuse the change. Undo restores the original history.' : editing
    ? 'Apply the edited inputs and regenerate all later features. Unresolved dependencies refuse the change without modifying the assembly.' : suppression
    ? 'The saved feature definition is retained. Apply regenerates the complete history and returns to its end; unresolved dependencies refuse the change.'
    : 'Choose the final position. The model will regenerate in this order; moves with unresolved dependencies are refused.' }), ...(suppression || editing || deletion ? [] : [select]), status] })
  let closed = false, busy = false, committing = false, adopting = false, jobId = null, unsubscribe
  const discard = id => { if (id) Promise.resolve(transport.cancel(id, { context })).catch(() => {}) }
  const cancel = createButton({ label: 'Cancel', onClick: () => modal.close() })
  const apply = createButton({ label: action, variant: 'primary', onClick: async () => {
    if (busy || closed || !current()) return
    busy = true; apply.disabled = true; select.disabled = true
    status.textContent = 'Checking dependencies and regenerating…'
    try {
      const started = await transport.start({ operation: deletion ? 'delete' : editing ? 'edit' : suppression ? 'suppress' : 'reorder', index: rowIndex,
        ...(deletion ? {} : editing ? { inputs } : suppression ? { suppressed } : { destination: Number(select.value) }), expected_revision: context.revision }, { context })
      jobId = started.job_id
      if (closed || !current()) { discard(jobId); return }
      let response
      do {
        response = await transport.poll(jobId, { context })
        if (closed || !current()) { discard(jobId); return }
        if (response.stale) throw new Error('The document changed. Reopen the history dialog.')
        if (['running', 'stopping'].includes(response.status)) await new Promise(resolve => setTimeout(resolve, 200))
      } while (['running', 'stopping'].includes(response.status))
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
      apply.disabled = !deletion && !editing && !suppression && Number(select.value) === rowIndex; select.disabled = false
    }
  } })
  apply.disabled = !deletion && !editing && !suppression
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
