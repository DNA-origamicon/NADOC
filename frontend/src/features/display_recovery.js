/** Rebuild disposable display state without authoring or changing the recipe. */
export async function refreshPublishedDisplay({ store, api }) {
  const source = store.getState().currentDesign
  const preview = !!store.getState().translateRotateActive
  const key = n => JSON.stringify([n.helix_id, n.bp_index, n.direction, n.copy_k ?? 0])
  const positions = geometry => new Map((geometry ?? []).map(n => [key(n), JSON.stringify([
    n.backbone_position, n.base_position, n.slab_position, n.slab_quaternion,
  ])]))
  const before = positions(store.getState().currentGeometry)
  await api.cancelHistoryPreview()
  if (store.getState().currentDesign !== source) throw new Error('Document changed; retry display refresh.')
  if (!await api.getGeometry()) throw new Error('Could not refresh published geometry.')
  if (store.getState().currentDesign !== source) throw new Error('Document changed during display refresh.')
  const after = positions(store.getState().currentGeometry)
  const changed = [...after].filter(([id, value]) => before.get(id) !== value).length
    + [...before.keys()].filter(id => !after.has(id)).length
  return { previewCancelled: preview, correctedNucleotides: changed }
}
