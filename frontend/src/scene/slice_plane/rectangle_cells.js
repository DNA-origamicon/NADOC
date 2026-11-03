import { boundsInRect, projectBox } from '../rectangle_selection.js'

// Use the same projected geometry extents and directional rules as scene selection.
export function rectangleCells(cells, camera, viewport, start, end) {
  const rect = {
    x1: Math.min(start.x, end.x) - viewport.left,
    y1: Math.min(start.y, end.y) - viewport.top,
    x2: Math.max(start.x, end.x) - viewport.left,
    y2: Math.max(start.y, end.y) - viewport.top,
  }
  return cells.filter(({ fill, state }) => {
    if (state === 'occupied') return false
    fill.updateWorldMatrix(true, false)
    if (!fill.geometry.boundingBox) fill.geometry.computeBoundingBox()
    return boundsInRect(projectBox(fill.geometry.boundingBox, fill.matrixWorld, camera, viewport),
      rect, end.x < start.x)
  })
}
