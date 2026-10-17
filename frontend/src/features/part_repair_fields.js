import { cloneRepairInput, repairActions } from './part_repair_model.js'

/** Only reviewed backend descriptors become controls; no arbitrary parameter JSON editor. */
export function parseRepairField(field, raw) {
  if (raw === null && field.nullable) return null
  const number = value => {
    if (typeof value === 'string' && !value.trim()) throw new Error(`${field.label} needs a number`)
    const result = Number(value)
    if (!Number.isFinite(result) || (field.input_type === 'integer' && !Number.isSafeInteger(result))) throw new Error(`${field.label} needs a finite ${field.input_type}`)
    if (field.minimum != null && result < field.minimum) throw new Error(`${field.label} must be at least ${field.minimum}`)
    if (field.exclusive_minimum != null && result <= field.exclusive_minimum) throw new Error(`${field.label} must exceed ${field.exclusive_minimum}`)
    if (field.maximum != null && result > field.maximum) throw new Error(`${field.label} must be at most ${field.maximum}`)
    return result
  }
  if (field.input_type === 'number' || field.input_type === 'integer') return number(raw)
  if (field.input_type === 'number_list') {
    if (!Array.isArray(raw) || !Number.isSafeInteger(field.length) || field.length > 64 || raw.length !== field.length) throw new Error(`${field.label} needs ${field.length} numbers`)
    return raw.map(number)
  }
  if (field.input_type === 'boolean' && typeof raw === 'boolean') return raw
  if (field.input_type === 'string' && typeof raw === 'string') {
    if (raw.length < (field.min_length ?? 0) || raw.length > (field.max_length ?? 1024)) throw new Error(`${field.label} has an invalid length`)
    return raw
  }
  if (field.input_type === 'reference' && typeof raw === 'string' && raw.length > 0 && raw.length <= 256) return raw
  if (field.input_type === 'source' && raw && typeof raw === 'object') return cloneRepairInput(raw)
  throw new Error('This input requires a reviewed editor')
}

export function actionFromRepairField(catalog, field, raw) {
  if (catalog?.version !== 1 || catalog.assessment !== 'inputs_only' || !catalog.definition_supported
      || !catalog.fields.includes(field)) throw new Error('Reload the supported feature inputs before editing')
  return cloneRepairInput({ action: 'set_input', feature_id: catalog.feature_id, child_id: catalog.child_id ?? null,
    parameter_path: field.parameter_path, expected_old: field.expected_old,
    ...(field.expected_old_json == null ? {} : { expected_old_json: field.expected_old_json }),
    value: parseRepairField(field, raw) })
}

export function updateRepairActions(actions, action) {
  const same = old => old.action === 'set_input' && old.feature_id === action.feature_id
    && (old.child_id ?? null) === (action.child_id ?? null) && JSON.stringify(old.parameter_path) === JSON.stringify(action.parameter_path)
  const index = actions.findIndex(same), result = [...actions]
  if (index < 0) result.push(action)
  else result[index] = action
  return repairActions(result)
}

export async function replacementRepairSource(field, file, digest = bytes => crypto.subtle.digest('SHA-256', bytes)) {
  const binding = field.source_binding
  const limit = Math.min(binding?.max_size_bytes ?? 0, 350000)
  if (!binding?.replacement_supported) throw new Error('This pinned source only supports restoration of its original bytes')
  if (!Number.isSafeInteger(file?.size) || file.size < 1 || file.size > limit) throw new Error(`Source file must contain 1–${limit} bytes`)
  const bytes = await file.arrayBuffer()
  if (bytes.byteLength !== file.size) throw new Error('Source file changed while reading')
  const hash = [...new Uint8Array(await digest(bytes))].map(value => value.toString(16).padStart(2, '0')).join('')
  if (hash.length !== 64) throw new Error('Could not compute the source SHA-256')
  return { ...cloneRepairInput(binding.source), sha256: hash, size_bytes: file.size }
}
