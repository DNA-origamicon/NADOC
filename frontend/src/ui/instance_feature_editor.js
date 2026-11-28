import { editFeature, featureEditFields } from './edit_feature_popover.js'
import { historyDialogHost } from './primitives/history_dialog_host.js'
import { showFeatureInputChange } from './primitives/feature_reorder_dialog.js'
import { getDocId } from '../shared/doc_id.js'

export function instanceFeatureFields(entry) {
  if (entry?.feature_type !== 'snapshot' || entry.params?._proof_version !== 1) return []
  const fields = entry.op_kind === 'overhang-sequence'
    ? [{ key: 'label', label: 'Label', type: 'text', allowBlank: true },
      { key: 'sequence', label: 'Sequence', type: 'text', allowBlank: true }]
    : featureEditFields(entry.op_kind)
  return fields.filter(field => Object.hasOwn(entry.params, field.key))
}

export async function editInstanceHistoryFeature(options) {
  const { source, rowIndex } = options
  const host = historyDialogHost({ ...options, getDocumentId: options.getDocumentId ?? getDocId })
  if (!host.current() || (source.feature_log_cursor ?? -1) !== -1 || source.feature_log_sub_cursor != null)
    throw new Error('Return to current selected-part history before editing.')
  const entry = source.feature_log[rowIndex], schema = instanceFeatureFields(entry)
  if (!schema.length) throw new Error('This feature has no supported input fields.')
  const inputs = await editFeature({ title: `Edit F${rowIndex + 1}`, opKind: entry.op_kind,
    currentParams: entry.params, schema, isCurrent: host.current })
  if (inputs && host.current()) return showFeatureInputChange({ ...options, inputs })
}
