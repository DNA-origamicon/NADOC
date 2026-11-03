import { showPersistentToast } from './toast.js'

/** A feature must have executed at the displayed history position. */
export function canEditAtCursor(design, index, subIndex = null) {
  const cursor = design?.feature_log_cursor ?? -1
  const child = design?.feature_log_sub_cursor
  if (cursor === -1) return child == null
  if (cursor < index) return false
  if (cursor > index || child == null || child === -1) return true
  return subIndex != null && child >= subIndex
}

export function isLatestHistory(design) {
  return (design?.feature_log_cursor ?? -1) === -1 && design?.feature_log_sub_cursor == null
}

/** Restore the full recipe before entering existing guarded native editors.
 * Seeking preserves the suffix; it never reverts or authors a feature.
 */
export async function restoreHistoryForEdit(api, store, index, featureId, subIndex = null) {
  const source = store.getState().currentDesign
  if (!canEditAtCursor(source, index, subIndex) || source?.feature_log?.[index]?.id !== featureId) return false
  if (isLatestHistory(source)) return true
  try {
    const result = await api.seekFeatures(-1)
    const current = store.getState().currentDesign
    if (!result || current?.id !== source.id || current?.feature_log?.[index]?.id !== featureId
        || !isLatestHistory(current)) {
      showPersistentToast('Could not restore the complete history for editing. Select the feature again.')
      return false
    }
    return true
  } catch (error) {
    showPersistentToast(`Could not restore history for editing: ${error.message}`)
    return false
  }
}
