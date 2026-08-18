import { BDNA_RISE_PER_BP } from '../constants.js'

export const DEFORMATION_PLANE_HALF_EXTENT_NM = 8.0
const AXIS_SAMPLE_STEP_BP = 7

function _vec3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)
    ? value : null
}

function _normalize(value) {
  const length = Math.hypot(...value)
  return Number.isFinite(length) && length > 1e-9
    ? value.map(component => component / length) : null
}

function _sampleSegment(samples, localBp, lengthBp) {
  const index = Math.max(0, Math.min(
    Math.floor(localBp / AXIS_SAMPLE_STEP_BP), samples.length - 2,
  ))
  const lowBp = index * AXIS_SAMPLE_STEP_BP
  const highBp = index + 1 < samples.length - 1
    ? (index + 1) * AXIS_SAMPLE_STEP_BP : lengthBp - 1
  const span = highBp - lowBp
  const t = span > 0 ? Math.max(0, Math.min(1, (localBp - lowBp) / span)) : 0
  return { index, t }
}

function _axisPointAndTangent(helix, globalBp) {
  const start = _vec3(helix?.start)
  const end = _vec3(helix?.end)
  const bpStart = helix?.bpStart ?? 0
  const lengthBp = helix?.lengthBp
  if (!start || !end || !Number.isSafeInteger(bpStart) ||
      !Number.isSafeInteger(lengthBp) || lengthBp < 1) return null
  const localBp = globalBp - bpStart
  const samples = Array.isArray(helix?.samples) && helix.samples.length > 2 &&
    helix.samples.every(sample => _vec3(sample)) ? helix.samples : null
  if (samples) {
    const { index, t } = _sampleSegment(samples, localBp, lengthBp)
    const first = samples[index]
    const second = samples[index + 1]
    const tangent = _normalize(second.map((value, axis) => value - first[axis]))
    if (!tangent) return null
    return {
      point: first.map((value, axis) => value + (second[axis] - value) * t),
      tangent,
    }
  }
  const tangent = _normalize(end.map((value, axis) => value - start[axis]))
  if (!tangent) return null
  return {
    point: start.map((value, axis) =>
      value + tangent[axis] * localBp * BDNA_RISE_PER_BP),
    tangent,
  }
}

/** Desktop-authoritative bundle plane frame at one global bp.
 *
 * This intentionally mirrors the deformation editor's existing semantics:
 * average all helices in the current tool scope, interpolate its 7-bp curved
 * samples (including the short final segment), and extrapolate straight axes by
 * global bp for staggered ends. Invalid/degenerate inputs fail closed.
 */
export function deformationPlaneFrame(globalBp, helices = []) {
  if (!Number.isSafeInteger(globalBp) || !Array.isArray(helices) || !helices.length) {
    return null
  }
  const rows = helices.map(helix => _axisPointAndTangent(helix, globalBp))
  if (rows.some(row => !row)) return null
  const center = [0, 0, 0]
  const tangentSum = [0, 0, 0]
  for (const row of rows) {
    for (let axis = 0; axis < 3; axis++) {
      center[axis] += row.point[axis]
      tangentSum[axis] += row.tangent[axis]
    }
  }
  for (let axis = 0; axis < 3; axis++) center[axis] /= rows.length
  const normal = _normalize(tangentSum)
  if (!normal || !center.every(Number.isFinite)) return null
  return {
    center,
    normal,
    halfExtentNm: DEFORMATION_PLANE_HALF_EXTENT_NM,
  }
}
