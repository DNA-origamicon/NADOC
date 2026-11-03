import { editFeature } from './edit_feature_popover.js'
import { createFeatureHistoryFeedback } from '../features/feature_history_feedback.js'

const number = (key, label, bounds = {}) => ({ key, label, type: 'number', ...bounds })
const text = (key, label) => ({ key, label, type: 'text' })
const choice = (key, label, options) => ({ key, label, type: 'select', options })
const vectorFields = (key, label, axes) => axes.map(axis => number(`${key}_${axis}`, `${label} ${axis.toUpperCase()}`))

export function assetFeatureFields(entry) {
  const p = entry?.params
  if (entry?.feature_type !== 'snapshot' || p?._proof_version !== 1 || p._generator) return []
  if (p._generated_scope?.version === 2 && p.np_fitting_version === 2
      && entry.op_kind === 'nanoparticle-attach-overhang') return [
    choice('fixed_center', 'Keep nanoparticle center fixed', ['true', 'false']),
  ]
  if (p._generated_scope?.version === 2 && p.thiol_version === 2
      && entry.op_kind === 'nanoparticle-conjugate') return [
    text('sequence', 'Handle sequence'), number('spacer_nm', 'Surface spacer (nm)', { min: 0, max: 100 }),
  ]
  if (p._generated_scope) return []
  if (p.np_fitting_version === 1) {
    if (entry.op_kind === 'nanoparticle-attach-overhang') return [text('strand_id', 'Handle strand'), text('overhang_id', 'Target overhang'), choice('fixed_center', 'Keep nanoparticle center fixed', ['true', 'false'])]
    if (entry.op_kind === 'nanoparticle-patch') return [...vectorFields('pivot', 'Pivot (nm)', ['x', 'y', 'z']),
      ...vectorFields('translation', 'Translation (nm)', ['x', 'y', 'z']), ...vectorFields('rotation', 'Rotation quaternion', ['x', 'y', 'z', 'w'])]
    // Collective relaxation has no tunable numerical parameters. Its exact
    // anchor selection is retained; Rebuild invokes the same pinned solver.
    if (entry.op_kind === 'nanoparticle-connection-relax') return []
  }
  if (entry.op_kind === 'nanoparticle-biotin-dna' && p.biotin_version === 1 && p.action === 'create') return [
    text('sequence', 'DNA sequence'), number('dna_per_strep', 'DNA per tetramer', { integer: true, min: 1, max: 4 }),
    choice('pocket', 'Pocket', ['auto', 'A', 'B', 'C', 'D']), number('linker_nm', 'Linker reach (nm)', { min: 1, max: 10 }),
  ]
  if (entry.op_kind === 'nanoparticle-patch' && p.coating_version === 1 && p.action === 'set') return [
    choice('mode', 'Coating mode', ['adsorption', 'biotin_tether']),
    number('footprint_nm2', 'Footprint (nm²)', { min: 25, max: 100 }),
    number('spacer_nm', 'Surface spacer (nm)', { min: 0, max: 20 }),
    number('seed', 'Placement seed', { integer: true, min: 0, max: 2147483647 }),
    number('count_override', 'Tetramer count (0 uses coverage)', { integer: true, min: 0, max: 64 }),
    ...(p.diameter_nm != null ? [number('diameter_nm', 'Diameter (nm)', { min: 1, max: 1000 })] : []),
  ]
  return []
}

export function isNativeAssetFeature(entry) {
  return assetFeatureFields(entry).length > 0 || (entry?.feature_type === 'snapshot'
    && entry.op_kind === 'nanoparticle-connection-relax' && entry.params?._proof_version === 1 && entry.params?.np_fitting_version === 1
    && !entry.params._generated_scope && !entry.params._generator)
}

export function assetEditorValues(entry) {
  const p = entry.params
  if (p.coating_version === 1 && p.action === 'set') return { ...p, count_override: p.count_override ?? 0 }
  if (p.np_fitting_version === 1 && entry.op_kind === 'nanoparticle-patch') return Object.fromEntries(
    ['pivot', 'translation', 'rotation'].flatMap(key => p.gizmo_move[key].map((value, i) => [`${key}_${'xyzw'[i]}`, value])))
  return { ...p, ...(Object.hasOwn(p, 'fixed_center') ? { fixed_center: String(p.fixed_center) } : {}) }
}

export function assetEditorPatch(entry, values) {
  if (entry.params.coating_version === 1 && entry.params.action === 'set') return {
    ...values, count_override: values.count_override === 0 ? null : values.count_override,
  }
  if (entry.params.np_fitting_version === 1 && entry.op_kind === 'nanoparticle-patch') return { gizmo_move: {
    ...entry.params.gizmo_move, ...Object.fromEntries(['pivot', 'translation', 'rotation'].map(key =>
      [key, (key === 'rotation' ? [...'xyzw'] : [...'xyz']).map(axis => values[`${key}_${axis}`])])),
  } }
  if (entry.op_kind === 'nanoparticle-attach-overhang') return { ...values, fixed_center: values.fixed_center === 'true' }
  if (entry.op_kind === 'nanoparticle-biotin-dna') {
    const sequence = values.sequence.trim().toUpperCase()
    if (!/^[ACGT]{2,32}$/.test(sequence)) throw new Error('Use a sequence of 2–32 A/C/G/T bases.')
    return { ...values, sequence }
  }
  return values
}

export function createAssetEditAction({ api, store }) {
  return async (entry, index) => {
    let context
    try { context = await api.assetOperationAPI.beginEdit() }
    catch (error) { store.setState({ lastError: { status: error.status ?? 409, message: error.message } }); return null }
    const feedback = createFeatureHistoryFeedback(store)
    const schema = assetFeatureFields(entry)
    // Reference choices name actual objects while retaining exact IDs, including
    // a saved reference that a downstream feature subsequently removed.
    for (const field of schema) if (field.key === 'strand_id' || field.key === 'overhang_id') {
      const kind = field.key === 'strand_id' ? 'strands' : 'overhangs'
      field.type = 'select'; field.options = [...new Set([entry.params[field.key], ...(context.source[kind] ?? []).map(item => item.id)])]
    }
    try {
      return await editFeature({ title: `Edit ${entry.label}`, opKind: entry.op_kind, schema,
        currentParams: assetEditorValues(entry), isCurrent: () => api.assetOperationAPI.isCurrent(context),
        onSave: async values => {
          feedback.clear()
          try { return await api.assetOperationAPI.edit(index, assetEditorPatch(entry, values), context, entry.id, `Rebuild ${entry.label}`) }
          catch (error) { feedback.update(error, context.source); throw error }
        },
      })
    } finally { feedback.dispose(); api.assetOperationAPI.endEdit(context) }
  }
}
