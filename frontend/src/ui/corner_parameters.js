import { BDNA_RISE_PER_BP } from '../constants.js'

export function isNativeCornerFeature(entry) {
  return entry?.feature_type === 'snapshot' && entry.op_kind === 'corner'
    && [1, 2, 3].includes(entry.params?._proof_version) && typeof entry.params.operation_id === 'string'
    && entry.params.operation_id.length > 0
}

/** Corner uses lattice half-turn steps, independently of typed bp precision. */
export function cornerPositionStep(lattice) {
  if (lattice === 'SQUARE') return 8
  if (lattice === 'HONEYCOMB') return 7
  throw new Error('Corner requires a square or honeycomb lattice.')
}

export function cornerParameters({ positionBp, angleDeg, directionDeg }) {
  if (!Number.isSafeInteger(positionBp)) throw new Error('Plane position must be an integer bp.')
  if (!Number.isFinite(angleDeg) || angleDeg < 0 || angleDeg >= 180) {
    throw new Error('Corner angle must be at least 0° and less than 180°.')
  }
  if (!Number.isFinite(directionDeg)) throw new Error('Corner direction must be finite.')
  return { positionBp, angleDeg, directionDeg: ((directionDeg % 360) + 360) % 360 }
}

export function cornerPositionNm(bp) { return bp * BDNA_RISE_PER_BP }

export function cornerPositionBp(nm) {
  if (!Number.isFinite(nm)) throw new Error('Plane position must be finite.')
  const bp = Math.round(nm / BDNA_RISE_PER_BP)
  if (!Number.isSafeInteger(bp)) throw new Error('Plane position is outside the supported range.')
  return bp
}
