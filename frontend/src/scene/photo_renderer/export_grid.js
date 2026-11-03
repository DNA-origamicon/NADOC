import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'

/** WebGL GridHelper lines are always one physical pixel wide. Temporarily use
 * screen-space triangle lines so exports preserve their apparent preview width.
 * Keep the original grid intact, including its hard-surface placement.
 */
export function prepareExportGrids(scene, pixelScale) {
  const grids = []
  scene.traverseVisible(obj => { if (obj.type === 'GridHelper') grids.push(obj) })
  const replacements = []
  for (const grid of grids) {
    const source = grid.material
    const geometry = new LineSegmentsGeometry()
    geometry.setPositions(grid.geometry.attributes.position.array)
    if (grid.geometry.attributes.color) geometry.setColors(grid.geometry.attributes.color.array)
    const material = new LineMaterial({
      color: source.color, vertexColors: source.vertexColors,
      linewidth: (source.linewidth ?? 1) * pixelScale,
      transparent: source.transparent, opacity: source.opacity,
      depthTest: source.depthTest, depthWrite: source.depthWrite,
      toneMapped: source.toneMapped,
    })
    material.visible = source.visible
    const proxy = new LineSegments2(geometry, material)
    proxy.name = 'photoExportGrid'
    proxy.userData.noAO = true
    proxy.matrixAutoUpdate = false
    if (grid.matrixAutoUpdate) grid.updateMatrix()
    proxy.matrix.copy(grid.matrix)
    proxy.layers.mask = grid.layers.mask
    proxy.renderOrder = grid.renderOrder
    grid.parent.add(proxy)
    grid.visible = false
    replacements.push({ grid, proxy })
  }
  return () => {
    for (const { grid, proxy } of replacements) {
      grid.visible = true
      proxy.removeFromParent()
      proxy.geometry.dispose()
      proxy.material.dispose()
    }
  }
}
