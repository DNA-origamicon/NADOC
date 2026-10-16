/** A temporary viewport layer excludes every canonical sibling, including later rebuilds. */
export const DEFORMATION_PREVIEW_LAYER = 31

export function createDeformationPreviewCamera({ scene, camera }) {
  if (camera?.layers?.mask !== 1) throw new Error('Return to the normal 3D view before editing this feature')
  const lights = []
  scene.traverse(node => {
    if (node.layers.isEnabled(DEFORMATION_PREVIEW_LAYER)) throw new Error('The private preview layer is already in use')
    if (node.isLight) lights.push({ node, prior: node.layers.mask })
  })
  const prior = camera.layers.mask
  camera.layers.set(DEFORMATION_PREVIEW_LAYER)
  const selected = camera.layers.mask
  for (const item of lights) {
    item.node.layers.enable(DEFORMATION_PREVIEW_LAYER); item.selected = item.node.layers.mask
  }
  let disposed = false
  return {
    include(root) {
      if (disposed) throw new Error('The preview viewport has closed')
      root.traverse(node => node.layers.set(DEFORMATION_PREVIEW_LAYER))
    },
    dispose() {
      if (disposed) return
      disposed = true
      // Other view transitions can take ownership while cancellation is pending.
      if (camera.layers.mask === selected) camera.layers.mask = prior
      for (const { node, prior, selected } of lights) if (node.layers.mask === selected) node.layers.mask = prior
    },
  }
}
