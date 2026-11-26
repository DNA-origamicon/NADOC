/** Scene-owned optical overlays must settle before offline capture, independent of RAF. */
const registrations = new WeakMap()
export function registerEMExport(scene, prepare) {
  if (!registrations.has(scene)) registrations.set(scene, new Set())
  const entries = registrations.get(scene)
  entries.add(prepare)
  return () => entries.delete(prepare)
}
export async function settleEMExport(scene) {
  for (const prepare of registrations.get(scene) ?? []) await prepare()
}

export function hasVisibleEM(scene) {
  let visible = false
  scene?.traverseVisible?.(obj => { if (obj.isPoints && obj.userData.emSamples && obj.geometry.attributes.position?.count) visible = true })
  return visible
}

/** Preserve apparent dot/glow size across tiled high-resolution exports. */
export function prepareEMExportSize(scene, scale) {
  const saved = new Map()
  scene.traverseVisible(obj => {
    if (!obj.isPoints || !obj.userData.emSamples || saved.has(obj.material)) return
    saved.set(obj.material, obj.material.size)
    obj.material.size *= scale
  })
  return () => { for (const [material, size] of saved) material.size = size }
}
