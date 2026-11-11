/** Scene-scoped insets: exports share the live entries and their saved lenses. */
const overlays = new WeakMap()
export function registerZoomVolumes(scene, overlay) {
  overlays.set(scene, overlay)
  return () => { if (overlays.get(scene) === overlay) overlays.delete(scene) }
}
export async function settleZoomVolumes(scene) {
  if (await overlays.get(scene)?.settle() === false) throw new Error('Zoom volume is not ready for export')
}
export function drawZoomVolumes(scene, ctx, width, height, camera) { overlays.get(scene)?.draw(ctx, width, height, camera) }
