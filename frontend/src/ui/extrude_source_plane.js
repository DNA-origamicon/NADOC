/** Canonical source plane; view/cluster transforms never rewrite lattice identity. */
export function resolveExtrudeSourcePlane(design, fallback = 'XY') {
  if (!['XY', 'XZ', 'YZ'].includes(fallback)) fallback = 'XY'
  const planes = new Set()
  let unknown = false
  for (const h of design?.helices ?? []) {
    let plane = /^h_(XY|XZ|YZ)_-?\d+_-?\d+(?:_|$)/.exec(h.id ?? '')?.[1]
    if (!plane) {
      const delta = ['x', 'y', 'z'].map(a => h.axis_end?.[a] - h.axis_start?.[a])
      const length = Math.hypot(...delta)
      if (Number.isFinite(length) && length > 1e-12) {
        const aligned = [0, 1, 2].filter(i => delta.every((v, j) => j === i || Math.abs(v) <= length * 1e-6))
        if (aligned.length === 1) plane = ['YZ', 'XZ', 'XY'][aligned[0]]
      }
    }
    if (plane) planes.add(plane)
    else unknown = true
  }
  if (planes.size === 1 && !unknown) return { plane: [...planes][0], reason: 'geometry' }
  return { plane: fallback, reason: planes.size > 1 ? 'mixed' : unknown ? 'unknown' : 'empty' }
}
