import { Matrix3 } from 'three'

/** Reuse a single display buffer; never alter saved coordinates. */
export function lerpCoordinates(from, to, t, out) {
  if (!from || !to || from.length !== to.length) return null
  if (!out || out.length !== from.length) out = new Float32Array(from.length)
  for (let i = 0; i < out.length; i++) out[i] = from[i] + (to[i] - from[i]) * t
  return out
}

/** Uniform Catmull–Rom: saved positions are knots; adjacent segments share tangents.
 * Missing neighbours use reflected endpoints, giving a straight two-frame fallback. */
export function cubicCoordinates(before, from, to, after, t, out) {
  if (!from || !to || from.length !== to.length) return null
  if (!out || out.length !== from.length) out = new Float32Array(from.length)
  const haveBefore = before?.length === from.length, haveAfter = after?.length === from.length
  const t2 = t * t, t3 = t2 * t
  const a = 2 * t3 - 3 * t2 + 1, b = t3 - 2 * t2 + t
  const c = -2 * t3 + 3 * t2, d = t3 - t2
  for (let i = 0; i < out.length; i++) {
    const delta = to[i] - from[i]
    const start = haveBefore ? (to[i] - before[i]) * .5 : delta
    const end = haveAfter ? (after[i] - from[i]) * .5 : delta
    out[i] = a * from[i] + b * start + c * to[i] + d * end
  }
  return out
}

/** Never borrow spline neighbours across a stage boundary or the loop restart. */
export function interpolationNeighbors(from, to, count, markers = []) {
  const boundary = i => markers.some(m => Number(m.frame) === i)
  return {
    before: from > 0 && !boundary(from) ? from - 1 : null,
    after: to + 1 < count && !boundary(to + 1) ? to + 1 : null,
  }
}

// Cell corners use bit 0/1/2 for the three lattice axes, in aligned display space.
function cell(box) {
  if (!box || box.length !== 24) return null
  const origin = Array.from(box.subarray ? box.subarray(0, 3) : box.slice(0, 3))
  const basis = [1, 2, 4].flatMap(k => [0, 1, 2].map(j => box[k * 3 + j] - origin[j]))
  const matrix = new Matrix3().fromArray(basis)
  if (Math.abs(matrix.determinant()) < 1e-12) return null
  return { origin, basis, inverse: matrix.invert().elements }
}

/** Prepare once per pair. Minimum-image motion stays in the moving periodic cell. */
export function periodicPositionInterpolator(from, to, boxFrom, boxTo, { before, after, boxBefore, boxAfter } = {}) {
  if (!from || !to || from.length !== to.length) return () => from
  const a = cell(boxFrom), b = cell(boxTo)
  let out = null
  if (!a || !b) return t => (out = cubicCoordinates(before, from, to, after, t, out))
  const previousCell = before?.length === from.length ? cell(boxBefore) : null
  const nextCell = after?.length === from.length ? cell(boxAfter) : null
  const fractional = new Float64Array(from.length), end = new Float64Array(from.length)
  const previous = previousCell ? new Float64Array(from.length) : null
  const next = nextCell ? new Float64Array(from.length) : null
  const component = (positions, frame, i, j) => frame.inverse[j] * (positions[i] - frame.origin[0])
    + frame.inverse[j + 3] * (positions[i + 1] - frame.origin[1])
    + frame.inverse[j + 6] * (positions[i + 2] - frame.origin[2])
  for (let i = 0; i < from.length; i += 3) {
    const x = from[i] - a.origin[0], y = from[i + 1] - a.origin[1], z = from[i + 2] - a.origin[2]
    const u = to[i] - b.origin[0], v = to[i + 1] - b.origin[1], w = to[i + 2] - b.origin[2]
    for (let j = 0; j < 3; j++) {
      const fa = a.inverse[j] * x + a.inverse[j + 3] * y + a.inverse[j + 6] * z
      const fb = b.inverse[j] * u + b.inverse[j + 3] * v + b.inverse[j + 6] * w
      fractional[i + j] = fa
      const unwrapped = fb - Math.round(fb - fa)
      end[i + j] = unwrapped
      if (previous) {
        const fp = component(before, previousCell, i, j)
        previous[i + j] = fp - Math.round(fp - fa)
      }
      if (next) {
        const fn = component(after, nextCell, i, j)
        next[i + j] = unwrapped + fn - fb - Math.round(fn - fb)
      }
    }
  }
  out = new Float32Array(from.length)
  const basis = new Float64Array(9), origin = new Float64Array(3)
  const smooth = new Float64Array(from.length)
  return t => {
    cubicCoordinates(previous, fractional, end, next, t, smooth)
    for (let j = 0; j < 9; j++) basis[j] = a.basis[j] + (b.basis[j] - a.basis[j]) * t
    for (let j = 0; j < 3; j++) origin[j] = a.origin[j] + (b.origin[j] - a.origin[j]) * t
    for (let i = 0; i < out.length; i += 3) {
      let x = smooth[i], y = smooth[i + 1], z = smooth[i + 2]
      x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z)
      for (let j = 0; j < 3; j++) out[i + j] = origin[j] + basis[j] * x + basis[j + 3] * y + basis[j + 6] * z
    }
    return out
  }
}
