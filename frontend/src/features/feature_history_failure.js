function featureLabel(entry, index) {
  const kind = entry.feature_type === 'deformation'
    ? (entry.op_snapshot?.type ? entry.op_snapshot.type[0].toUpperCase() + entry.op_snapshot.type.slice(1) : 'Deformation')
    : (entry.label || entry.op_kind || entry.feature_type)
  return `F${index + 1} ${kind}`
}

/** Name the earliest downstream feature that cannot regenerate (contract C4). */
export function attributeFailure(error, design, editedFeatureId = null) {
  const id = error?.detail?.feature_id ?? error?.detail?.assessment?.issues?.[0]?.feature_id
  if (!id || id === editedFeatureId || !Array.isArray(design?.feature_log)) return error
  const index = design.feature_log.findIndex(entry => entry.id === id || entry.children?.some(child => child.id === id))
  if (index < 0) return error
  const row = design.feature_log[index], child = row.children?.find(item => item.id === id)
  const label = featureLabel(row, index) + (child ? ` / ${child.label || child.op_subtype || child.id}` : '')
  const attributed = new Error(`${label} cannot regenerate after this edit: ${error.message}`)
  return Object.assign(attributed, { status: error.status, code: error.code, detail: error.detail })
}
