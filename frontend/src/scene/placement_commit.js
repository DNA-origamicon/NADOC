/** Commit explicit placement owners; never resolve an organizational selection. */
export async function commitPlacementTransforms(pending, {
  organized, command, patch, log = true, isCurrent = () => true,
}) {
  const entries = [...pending.entries()]
  const result = { count: 0, clusterIds: [], geometryApplied: false, error: null }
  if (!entries.length) return result
  const accept = accepted => {
    for (const [id, value] of accepted) {
      // A later local input must survive the response for an earlier input.
      if (pending.get(id) === value) pending.delete(id)
      result.clusterIds.push(id)
    }
    result.count = result.clusterIds.length
  }
  try {
    if (!isCurrent()) throw new Error('The design changed during the move. Reset the preview before applying.')
    if (organized) {
      if (typeof command !== 'function') throw new Error('The placement editor is unavailable.')
      const response = await command('placements-update', { placements: entries.map(([id, fields]) => ({
        placement_id: id, fields,
      })) })
      if (!response) throw new Error('The move was not accepted. Pending movement has been retained.')
      accept(entries)
      result.geometryApplied = true
    } else {
      if (typeof patch !== 'function') throw new Error('The placement editor is unavailable.')
      for (const entry of entries) {
        const response = await patch(entry[0], { ...entry[1], commit: true, log })
        if (!response) throw new Error('A placement was not accepted. Unapplied movement has been retained.')
        accept([entry])
      }
    }
  } catch (error) {
    result.error = error instanceof Error ? error : new Error(String(error))
  }
  return result
}
