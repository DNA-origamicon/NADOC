/**
 * Representation-neutral placement records for crossover-insert nucleotides.
 *
 * A placement describes a residue frame; renderers decide whether to put one CG
 * bead/slab or a full atom template on it. Keep mesh construction out of this module.
 */
import * as THREE from 'three'

const _point = new THREE.Vector3()
const _tangent = new THREE.Vector3()
const _chord = new THREE.Vector3()
const _axis = new THREE.Vector3()
const _bow = new THREE.Vector3()
const _basis = new THREE.Matrix4()
const _frame = new THREE.Matrix4()
const _frameRotation = new THREE.Matrix4().makeRotationZ(-0.646577)
const _local = new THREE.Vector3()
const BOW_FRACTION = 0.3

// Junction-local poses recovered from the two manually positioned 1xT residues in
// workspace/2hb_1xT.nadoc. They cover the two chemical traversal orientations through
// a crossover. Keep these values in exact parity with atomistic_helpers.py; expressing
// them in the residue frame makes them transferable to every helix pair/orientation.
const ONE_BASE_DEFAULT_LOCAL_POSES = Object.freeze({
  direct: Object.freeze({
    translation: Object.freeze([-0.11838409398784218, -0.22868023153856676, -0.035012651628871135]),
    rotation: Object.freeze([-0.10871135764025318, 0.05191393506416845, -0.3845073158890162, 0.9152272439640281]),
  }),
  reversed: Object.freeze({
    translation: Object.freeze([-0.021056163944091474, -0.2061734603038539, -0.07055908771081991]),
    rotation: Object.freeze([-0.0653133319390967, -0.08778461219542308, -0.20145497692027542, 0.9733673113510458]),
  }),
})

// Heavy-atom base-ring centroids in the FORWARD 1ZEW templates stamped for crossover
// inserts by backend/core/atomistic.py. These are projection sites, not additional
// placement rules: the canonical residue frame below maps both atom templates and Full
// slabs into world space.
const BASE_CENTROID = Object.freeze({
  A: new THREE.Vector3(0.53703, 0.29007, -0.02953),
  T: new THREE.Vector3(0.45561111111111113, 0.23046666666666665, -0.04678888888888889),
  G: new THREE.Vector3(0.5714, 0.3973, 0.004427272727272728),
  C: new THREE.Vector3(0.4134, 0.2024625, -0.0428125),
})

export function quadraticPoint(a, c, b, t, out = new THREE.Vector3()) {
  const u = 1 - t
  return out.set(
    u * u * a.x + 2 * u * t * c.x + t * t * b.x,
    u * u * a.y + 2 * u * t * c.y + t * t * b.y,
    u * u * a.z + 2 * u * t * c.z + t * t * b.z,
  )
}

export function quadraticTangent(a, c, b, t, out = new THREE.Vector3()) {
  const u = 1 - t
  return out.set(
    2 * u * (c.x - a.x) + 2 * t * (b.x - c.x),
    2 * u * (c.y - a.y) + 2 * t * (b.y - c.y),
    2 * u * (c.z - a.z) + 2 * t * (b.z - c.z),
  ).normalize()
}

/** Canonical control point and bow direction for a default crossover run. */
export function crossoverControlPoint(pointA, pointB, nucA, nucB,
  out = new THREE.Vector3(), outBow = null) {
  _chord.subVectors(pointB, pointA)
  const distance = _chord.length()
  if (distance < 1e-9) {
    out.copy(pointA); outBow?.set(0, 0, 1); return out
  }
  _chord.divideScalar(distance)
  _axis.set(...nucA.axis_tangent).add(_tangent.set(...nucB.axis_tangent))
  if (_axis.lengthSq() < 1e-18) _axis.set(0, 0, 1)
  else _axis.normalize()
  _bow.crossVectors(_chord, _axis)
  if (_bow.lengthSq() < 1e-12) _bow.copy(_axis)
  else _bow.normalize()
  outBow?.copy(_bow)
  return out.lerpVectors(pointA, pointB, 0.5).addScaledVector(_bow, distance * BOW_FRACTION)
}

/** Canonical Full-representation slab orientation derived from a placement frame. */
export function crossoverSlabQuaternion(tangent, helixAxis, out = new THREE.Quaternion()) {
  _bow.crossVectors(tangent, helixAxis)
  if (_bow.lengthSq() < 1e-12) return out.identity()
  _bow.normalize()
  _basis.makeBasis(_bow, tangent, helixAxis)
  return out.setFromRotationMatrix(_basis)
}

/** Atom-template residue frame used for a crossover insert. */
export function crossoverExtraFrameQuaternion(chainTangent, bow, out = new THREE.Quaternion()) {
  const ez = _axis.copy(chainTangent).negate().normalize()
  const en = _chord.copy(bow).addScaledVector(ez, -bow.dot(ez))
  if (en.lengthSq() < 1e-12) {
    en.set(0, 0, 1)
    if (Math.abs(en.dot(ez)) > 0.9) en.set(1, 0, 0)
    en.addScaledVector(ez, -en.dot(ez))
  }
  en.normalize()
  const ey = _bow.crossVectors(ez, en).normalize()
  _frame.makeBasis(en, ey, ez).multiply(_frameRotation)
  return out.setFromRotationMatrix(_frame)
}

/** Full slab orientation whose long axis and center overlay the rendered base ring. */
export function crossoverExtraSlabQuaternion(frameQuaternion, out = new THREE.Quaternion()) {
  const en = _chord.set(1, 0, 0).applyQuaternion(frameQuaternion)
  const ey = _axis.set(0, 1, 0).applyQuaternion(frameQuaternion)
  const ez = _bow.set(0, 0, 1).applyQuaternion(frameQuaternion)
  _basis.makeBasis(ey, ez, en)
  return out.setFromRotationMatrix(_basis)
}

/** Measured default local pose for a one-base insert; longer runs remain unchanged. */
export function crossoverExtraBaseDefaultLocalPose(count, simReversed = false) {
  if (count !== 1) return null
  return ONE_BASE_DEFAULT_LOCAL_POSES[simReversed ? 'reversed' : 'direct']
}

/** Build one canonical placement per insert, in geometric A→B order. */
export function buildCrossoverExtraPlacements({ xoId, count, pointA, control, pointB,
  helixAxis, sequence = '', simReversed = false, savedTransforms = new Map() }) {
  const out = []
  const runBow = new THREE.Vector3().lerpVectors(pointA, pointB, 0.5)
    .sub(control).negate()
  if (runBow.lengthSq() < 1e-12) runBow.crossVectors(_chord.subVectors(pointB, pointA), helixAxis)
  if (runBow.lengthSq() < 1e-12) runBow.set(0, 0, 1)
  else runBow.normalize()
  for (let geometricIndex = 0; geometricIndex < count; geometricIndex++) {
    const t = (geometricIndex + 1) / (count + 1)
    const simK = simReversed ? count - 1 - geometricIndex : geometricIndex
    const geometricCenter = quadraticPoint(pointA, control, pointB, t, _point).clone()
    const geometricTangent = quadraticTangent(pointA, control, pointB, t, _tangent).clone()
    const geometricChainTangent = simReversed
      ? geometricTangent.clone().negate() : geometricTangent.clone()
    const sourceFrameQuaternion = crossoverExtraFrameQuaternion(
      geometricChainTangent, runBow,
    ).clone()
    const defaultPose = crossoverExtraBaseDefaultLocalPose(count, simReversed)
    const defaultLocalTranslation = defaultPose
      ? new THREE.Vector3(...defaultPose.translation) : new THREE.Vector3()
    const defaultLocalQuaternion = defaultPose
      ? new THREE.Quaternion(...defaultPose.rotation) : new THREE.Quaternion()
    const sourceCenter = defaultLocalTranslation.applyQuaternion(sourceFrameQuaternion)
      .add(geometricCenter)
    const frameQuaternion = sourceFrameQuaternion.clone().multiply(defaultLocalQuaternion)
    const defaultWorldQuaternion = sourceFrameQuaternion.clone()
      .multiply(defaultLocalQuaternion)
      .multiply(sourceFrameQuaternion.clone().invert())
    const sourceTangent = geometricTangent.clone().applyQuaternion(defaultWorldQuaternion)
    const chainTangent = geometricChainTangent.clone().applyQuaternion(defaultWorldQuaternion)
    const baseLetter = (sequence[simK] ?? 'T').toUpperCase()
    const localBaseCenter = BASE_CENTROID[baseLetter] ?? BASE_CENTROID.T
    const sourceBaseCenter = _local.copy(localBaseCenter).applyQuaternion(frameQuaternion)
      .add(sourceCenter).clone()
    const pose = savedTransforms.get(simK) ?? null
    const center = sourceCenter.clone()
    const tangent = sourceTangent.clone()
    const baseCenter = sourceBaseCenter.clone()
    if (pose) {
      center.applyMatrix4(pose)
      tangent.transformDirection(pose)
      baseCenter.applyMatrix4(pose)
    }
    out.push({
      xoId, geometricIndex, simK, t, geometricCenter, geometricTangent,
      geometricChainTangent, sourceFrameQuaternion, defaultPose,
      sourceCenter, sourceTangent, chainTangent, bow: runBow.clone(),
      sourceBaseCenter, baseCenter, frameQuaternion,
      center, tangent, helixAxis: helixAxis.clone(), pose,
    })
  }
  return out
}
