import { editFeature } from './edit_feature_popover.js'
import { createFeatureHistoryFeedback } from '../features/feature_history_feedback.js'

export const CONNECTION_HISTORY_EDITOR_ENABLED = true
const DIRECT = ['root-to-root', 'end-to-root']
const LINKERS = ['root-to-root', 'root-to-end', 'end-to-root', 'end-to-end']
  .flatMap(attach => ['ss', 'ds'].map(material => `${attach}-${material}dna-linker`))
const INDIRECT = ['root-to-root-indirect', 'end-to-end-indirect']
const FIELDS = [
  { key: 'name', label: 'Name', type: 'text', allowBlank: true },
  { key: 'connection_type', label: 'Connection type', type: 'select' },
  { key: 'overhang_a_seq', label: 'Overhang A sequence', type: 'text', allowBlank: true },
  { key: 'overhang_b_seq', label: 'Overhang B sequence', type: 'text', allowBlank: true },
  { key: 'bridge_length', label: 'Bridge length (bp)', type: 'number', integer: true, min: 0 },
  { key: 'bridge_seq', label: 'Bridge sequence', type: 'text', allowBlank: true },
]

export function connectionFeatureFields(entry) {
  if (entry?.feature_type !== 'snapshot' || entry.op_kind !== 'overhang-bulk' || entry.params?._proof_version !== 1) return []
  const params = entry.params, action = params.action
  if (!['connection-version-create', 'connection-version-connect-direct', 'connection-version-connect-linker', 'connection-version-patch'].includes(action)) return []
  if (params._generated_scope || params._generator) return []
  const marker = action === 'connection-version-connect-direct' ? 'direct_composition_version'
    : action === 'connection-version-connect-linker' ? 'connection_composition_version' : 'connection_version_contract'
  const versions = marker === 'connection_composition_version' ? [1, 2, 3, 4] : [1, 2]
  if (!versions.includes(params[marker])) return []
  const values = action === 'connection-version-patch' ? params.patch : params
  const types = action === 'connection-version-connect-direct' ? DIRECT
    : action === 'connection-version-connect-linker' ? [...LINKERS, ...INDIRECT] : [...DIRECT, ...LINKERS, ...INDIRECT]
  return FIELDS.filter(field => Object.hasOwn(values ?? {}, field.key)
    && !(action === 'connection-version-connect-direct' && field.key.startsWith('bridge_')))
    .map(field => field.key === 'connection_type' ? { ...field, options: types } : field)
}

export function createConnectionEditAction({ api, store }) {
  return async (entry, index) => {
    const context = api.captureFeatureEditContext(), feedback = createFeatureHistoryFeedback(store)
    const patch = entry.params.action === 'connection-version-patch'
    try {
      return await editFeature({ title: 'Edit Connection', opKind: 'connection',
        currentParams: patch ? entry.params.patch : entry.params, schema: connectionFeatureFields(entry),
        isCurrent: () => api.isFeatureEditContextCurrent(context),
        onSave: async values => {
          if (Object.hasOwn(values, 'name')) values.name ??= ''
          feedback.clear()
          try {
            return await api.editFeatureInputs(index, patch ? { patch: { ...entry.params.patch, ...values } } : values,
              context, entry.id)
          } catch (error) { feedback.update(error, context.source); throw error }
        },
      })
    } finally { feedback.dispose() }
  }
}
