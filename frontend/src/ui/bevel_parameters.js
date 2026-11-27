import { BDNA_RISE_PER_BP } from '../constants.js'

export function isNativeBevelFeature(entry) {
  return entry?.feature_type === 'snapshot' && entry.op_kind === 'bevel'
    && [1, 2].includes(entry.params?._proof_version) && typeof entry.params.operation_id === 'string'
    && entry.params.operation_id.length > 0
}

/** Bevel uses lattice half-turn steps, independently of typed bp precision. */
export function bevelPositionStep(lattice) {
  if (lattice === 'SQUARE') return 8
  if (lattice === 'HONEYCOMB') return 7
  throw new Error('Bevel requires a square or honeycomb lattice.')
}

export function bevelParameters({ positionBp, angleDeg, directionDeg, trimEnd = 'end' }) {
  if (!Number.isSafeInteger(positionBp)) throw new Error('Plane position must be an integer bp.')
  if (!Number.isFinite(angleDeg) || angleDeg < 0 || angleDeg >= 90) {
    throw new Error('Bevel angle must be at least 0° and less than 90°.')
  }
  if (!Number.isFinite(directionDeg)) throw new Error('Bevel direction must be finite.')
  if (!['start', 'end'].includes(trimEnd)) throw new Error('Choose the end to trim.')
  return { positionBp, angleDeg, trimEnd, directionDeg: ((directionDeg % 360) + 360) % 360 }
}

export function bevelPositionNm(bp) { return bp * BDNA_RISE_PER_BP }

export function bevelPositionBp(nm) {
  if (!Number.isFinite(nm)) throw new Error('Plane position must be finite.')
  const bp = Math.round(nm / BDNA_RISE_PER_BP)
  if (!Number.isSafeInteger(bp)) throw new Error('Plane position is outside the supported range.')
  return bp
}
