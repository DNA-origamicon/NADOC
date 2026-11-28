import { historyDialogHost } from './primitives/history_dialog_host.js'
import { showFeatureInputChange } from './primitives/feature_reorder_dialog.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { createAssemblyInputForm } from './assembly_input_form.js'
import { getDocId } from '../shared/doc_id.js'

const partCommands = new Set(['assembly-instance-history-change', 'assembly-instance-overhang-extrude',
  'assembly-instance-overhang-patch', 'assembly-transform-instance-cluster', 'assembly-replace-instance-source'])
const excluded = new Set(['source', 'silent', 'expected_revision', 'expected_assembly_id', 'mode',
  'allow_part_joints', 'joint_states', 'cluster_transform_overrides'])

/** Menu eligibility only; the backend supplies the authoritative typed form. */
export function assemblyFeatureFields(entry) {
  if (partCommands.has(entry?.op_kind) || entry?.params?.command_version !== 1 || !entry.params.inputs) return []
  const keys = Object.keys(entry.params.inputs).filter(key => !excluded.has(key))
  if (Object.keys(entry.params).some(key => ['source_instance_id', 'source_group_id', 'joint_id', 'group_id', 'relation_id', 'binding_id', 'connection_id', 'duplex_id', 'belt_id', 'rider_id'].includes(key))
      || (entry.params.instance_id && !['assembly-add-instance', 'assembly-polymerize-periodic'].includes(entry.op_kind))) keys.push('_targets')
  return keys.map(key => ({ key }))
}

/** Captured input form -> cancellable independent regeneration -> one undo step. */
export async function editAssemblyHistoryFeature(options) {
  const { source, rowIndex } = options
  const entry = source.feature_log[rowIndex]
  if (!assemblyFeatureFields(entry).length) throw new Error('This feature has no editable assembly-owned inputs.')
  const host = historyDialogHost({ ...options, assembly: true, getDocumentId: options.getDocumentId ?? getDocId })
  if (!host.current() || (source.feature_log_cursor ?? -1) !== -1 || source.feature_log_sub_cursor != null)
    throw new Error('Return to current assembly history before editing a feature.')
  const abort = new AbortController()
  let cancelled = false, loaded = false, captured
  const loading = createModal({ title: `Loading F${rowIndex + 1} inputs`, size: 'sm',
    body: 'Loading recorded inputs and historical choices…',
    actions: [createButton({ label: 'Cancel', onClick: () => loading.close() })],
    onClose: () => { if (!loaded) { cancelled = true; abort.abort() } } })
  loading.open()
  const stopLoading = options.store.subscribe(() => { if (!host.current()) loading.close() })
  try { captured = await host.transport.inputs(rowIndex, { context: host.context, signal: abort.signal }) }
  catch (error) { if (!cancelled) throw error }
  finally { loaded = true; stopLoading(); loading.close() }
  if (cancelled) return null
  if (!host.current() || captured.assembly_id !== source.id || captured.revision !== host.context.revision || captured.feature_id !== entry.id)
    throw new Error('The assembly changed. Reopen this editor.')
  const inputs = await new Promise(resolve => {
    let finished = false, unsubscribe
    const finish = value => { if (finished) return; finished = true; unsubscribe?.(); window.removeEventListener('nadoc:document-reset', close); resolve(value) }
    const form = createAssemblyInputForm(captured)
    const error = document.createElement('p'); error.setAttribute('role', 'alert')
    const help = document.createElement('p'); help.textContent = 'Keep an input as recorded, or change it here. Choices reflect the assembly before this feature. Applying an edit rebuilds later features.'
    const body = document.createElement('div'); body.append(help, form.element, error)
    const save = createButton({ label: 'Save', variant: 'primary', onClick: () => {
      if (!host.current()) { error.textContent = 'The assembly changed. Reopen this editor.'; return }
      try { const patch = form.read(); finish(patch); modal.close() } catch (failure) { error.textContent = failure.message }
    } })
    const modal = createModal({ title: `Edit F${rowIndex + 1}`, size: 'md', body,
      actions: [createButton({ label: 'Cancel', onClick: () => modal.close() }), save], onClose: () => finish(null) })
    function close() { modal.close() }
    modal.open()
    window.addEventListener('nadoc:document-reset', close)
    unsubscribe = options.store.subscribe(() => { if (!host.current()) close() })
  })
  if (inputs && host.current()) return showFeatureInputChange({ ...options, assembly: true, inputs })
}
