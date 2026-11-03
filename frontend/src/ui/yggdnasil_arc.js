import { CURVATURE_LIMITS } from '../design/yggdnasil_curvature.js'
/** Nominal planar-arc envelope in the bend plane; not a relaxed shape. */
export function arcEnvelope(entry, length, angleRad) {
  const mean = entry.points.reduce((s, p) => s + p.x, 0) / entry.helices
  const offsets = entry.points.map(p => (p.x - mean) * CURVATURE_LIMITS.helix_pitch_nm)
  const low = Math.min(...offsets) - 1, high = Math.max(...offsets) + 1
  const span = length * CURVATURE_LIMITS.rise_nm
  if (angleRad < 1e-9) return [[low, 0], [high, 0], [high, span], [low, span]]
  const radius = span / angleRad, steps = Math.max(12, Math.ceil(angleRad * 36))
  const side = r => Array.from({ length: steps + 1 }, (_, i) => {
    const a = angleRad * i / steps
    return [radius + (r - radius) * Math.cos(a), (radius - r) * Math.sin(a)]
  })
  return [...side(low), ...side(high).reverse()]
}
export function arcPreview(entry, length, angleRad) {
  const points = arcEnvelope(entry, length, angleRad)
  const xs = points.map(p => p[0]), ys = points.map(p => p[1])
  const minX = Math.min(...xs), minY = Math.min(...ys), width = Math.max(...xs) - minX, height = Math.max(...ys) - minY
  const padding = Math.max(1, Math.max(width, height) * 0.04)
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX-padding} ${minY-padding} ${width+2*padding} ${height+2*padding}" role="img" aria-label="Nominal uniform planar arc"><polygon points="${points.map(p => p.join(',')).join(' ')}" fill="#73c7a6"/></svg>`
}
