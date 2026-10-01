export const DRAW_HOLD_MS = 2000
export const DRAW_LIFETIME_MS = 2500

/** Screen coordinates are measured in viewport heights, centered on the camera. */
export function drawingPoints(points) {
  if (!Array.isArray(points) || points.length < 1 || points.length > 32 || points.some(p =>
    !Array.isArray(p) || p.length !== 2 || p.some(n => !Number.isFinite(n) || Math.abs(n) > 8))) throw new Error('Invalid drawing points')
  return points.map(p => [...p])
}
export function sameDrawingView(a, b) {
  if (!a || !b) return false
  const radius = Math.hypot(...a.position.map((v, i) => v - a.target[i]))
  return ['position', 'target', 'up'].every(key => a[key]?.length === 3 && b[key]?.length === 3 &&
    a[key].every((v, i) => Math.abs(v - b[key][i]) <= (key === 'up' ? 1e-6 : Math.max(1e-7, radius * 1e-6)))) && Math.abs(a.fov - b.fov) < 1e-5
}
export function drawingOpacity(age) { return Math.max(0, Math.min(1, (DRAW_LIFETIME_MS - age) / (DRAW_LIFETIME_MS - DRAW_HOLD_MS))) }
