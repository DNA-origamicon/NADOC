/** Scoped display/raycast ownership for an isolated history tool. */
export function markGizmoLayer(root, layer) {
  if (Number.isInteger(layer)) root?.traverse(node => node.layers.set(layer))
}

export function bindPrivateGizmoLayer(controls, layer) {
  if (!Number.isInteger(layer)) return () => {}
  markGizmoLayer(controls.getHelper(), layer)
  // Three shares this raycaster between TransformControls instances.
  const layers = controls.getRaycaster().layers, previous = layers.mask
  layers.set(layer)
  const owned = layers.mask
  return () => { if (layers.mask === owned) layers.mask = previous }
}
