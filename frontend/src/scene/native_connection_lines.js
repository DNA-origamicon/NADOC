/** Shared native connection buffers; extracted unchanged from unfold_view. */
import * as THREE from 'three'

export const ARC_SEGS = 20

/** Exact native quadratic sampling; callers own control points and updates. */
export function writeNativeConnectionArc(buf, base, from, control, to) {
  for (let j = 0; j <= ARC_SEGS; j++) {
    const u  = j / ARC_SEGS
    const u2 = 1 - u
    const w0 = u2 * u2, w1 = 2 * u2 * u, w2 = u * u
    const bi = (base + j) * 3
    buf[bi]     = w0 * from.x + w1 * control.x + w2 * to.x
    buf[bi + 1] = w0 * from.y + w1 * control.y + w2 * to.y
    buf[bi + 2] = w0 * from.z + w1 * control.z + w2 * to.z
  }
}

export function buildNativeConnectionLines(arcs, arcType = 'unknown', colorFor = arc => arc.color, alphaFor = () => 1) {
  if (!arcs.length) return null
  const N         = arcs.length
  const vertCount = N * (ARC_SEGS + 1)
  const positions = new Float32Array(vertCount * 3)
  // RGBA, not RGB. A 4-component colour attribute makes three define
  // USE_COLOR_ALPHA, so `diffuseColor *= vColor` fades per VERTEX — the only
  // per-arc alpha channel available here, since all arcs of a strand type share
  // one merged LineSegments and therefore one material. Per-cluster opacity
  // rides this.
  const colors    = new Float32Array(vertCount * 4)
  // LineSegments uses pairs: each of the ARC_SEGS segments has 2 index entries.
  const idxCount  = N * ARC_SEGS * 2
  const idx       = vertCount > 65535
    ? new Uint32Array(idxCount)
    : new Uint16Array(idxCount)
  const tc = new THREE.Color()
  for (let a = 0; a < N; a++) {
    const base = a * (ARC_SEGS + 1)
    arcs[a].vertIdx = base   // mutate the _arcMeta entry in place
    for (let s = 0; s < ARC_SEGS; s++) {
      idx[(a * ARC_SEGS + s) * 2]     = base + s
      idx[(a * ARC_SEGS + s) * 2 + 1] = base + s + 1
    }
    tc.setHex(colorFor(arcs[a]))
    const alpha = alphaFor(arcs[a])
    for (let v = 0; v <= ARC_SEGS; v++) {
      const ci = (base + v) * 4
      colors[ci] = tc.r; colors[ci + 1] = tc.g; colors[ci + 2] = tc.b; colors[ci + 3] = alpha
    }
  }
  const geo  = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('color',    new THREE.BufferAttribute(colors,    4))
  geo.setIndex(new THREE.BufferAttribute(idx, 1))
  const mat  = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 })
  const line = new THREE.LineSegments(geo, mat)
  line.frustumCulled = false
  // DEBUG IDs — searchable via scene.traverse() or window.__nadocDebugXovers()
  line.name     = `xoverArcMerged_${arcType}`
  line.userData = {
    debugType:   'xoverArcMerged',
    arcType,
    arcCount:    N,
    arcXoverIds: arcs.map(a => a.crossover_id).filter(Boolean),
  }
  return { geo, line, positions, colors }
}
