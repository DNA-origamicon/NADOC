import { editFeature, featureEditFields } from './edit_feature_popover.js'
import { historyDialogHost } from './primitives/history_dialog_host.js'
import { showFeatureInputChange } from './primitives/feature_reorder_dialog.js'
import { getDocId } from '../shared/doc_id.js'

const number = (key, label) => ({ key, label, type: 'number' })
const name = { key: 'name', label: 'Name', type: 'text' }
const fields = {
  'assembly-instance-overhang-extrude': [{ ...number('length_bp', 'Length (bp)'), integer: true, min: 1 }],
  'assembly-instance-overhang-patch': [
    { key: 'label', label: 'Label', type: 'text', allowBlank: true },
    { key: 'sequence', label: 'Sequence', type: 'text', allowBlank: true },
  ],
  'assembly-create-gear': [number('ratio', 'Ratio')],
  'assembly-patch-gear': [number('ratio', 'Ratio')],
  'assembly-add-joint': [number('current_value', 'Joint value')],
  'assembly-patch-joint': [number('current_value', 'Joint value'), number('min_limit', 'Minimum limit'), number('max_limit', 'Maximum limit')],
  'assembly-add-instance': [name],
  'assembly-patch-instance': [name],
  'assembly-create-group': [name],
  'assembly-patch-group': [name],
}

export function assemblyFeatureFields(entry) {
  if (entry?.params?.command_version !== 1 || !entry.params.inputs) return []
  return (fields[entry.op_kind] ?? featureEditFields(entry.op_kind))
    .filter(field => entry.params.inputs[field.key] != null || (field.allowBlank && Object.hasOwn(entry.params.inputs, field.key)
      && (entry.op_kind !== 'assembly-instance-overhang-patch' || entry.params.input_fields_set?.includes(field.key))))
}

/** Ordinary recorded-input editing, followed by shared cancellable regeneration. */
export async function editAssemblyHistoryFeature(options) {
  const { source, rowIndex } = options
  const entry = source.feature_log[rowIndex]
  const schema = assemblyFeatureFields(entry)
  if (!schema.length) throw new Error('This feature has no supported input fields.')
  const host = historyDialogHost({ ...options, assembly: true, getDocumentId: options.getDocumentId ?? getDocId })
  if (!host.current() || (source.feature_log_cursor ?? -1) !== -1 || source.feature_log_sub_cursor != null)
    throw new Error('Return to current assembly history before editing a feature.')
  const inputs = await editFeature({ title: `Edit F${rowIndex + 1}`, opKind: entry.op_kind,
    currentParams: entry.params.inputs, schema, isCurrent: host.current })
  if (inputs && host.current()) return showFeatureInputChange({ ...options, assembly: true, inputs })
}
