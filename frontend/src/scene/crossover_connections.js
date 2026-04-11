/**
 * Crossover connection renderer — 3D line segments between backbone beads,
 * plus arc-interpolated beads and slabs for crossovers with extra bases.
 *
 * Reads design.crossovers and draws a line between the backbone_position of
 * each half-crossover's nucleotide.  When a crossover has extra_bases (e.g.
 * "TT"), the straight line is replaced with a quadratic Bezier arc and
 * backbone beads + nucleotide slabs are interpolated along the arc.
 *
 * RULE: no geometry or topology reasoning here.  The crossover record is the
 * single source of truth.  Look up nucleotide positions by key, draw the line.
 * Any attempt to infer connection targets from strand topology will produce
 * wrong results — the lesson learned in the 2D editor applies equally here.
 */

import * as THREE from 'three'

// ── Constants ────────────────────────────────────────────────────────────────

const BOW_FRAC_3D  = 0.3   // bow magnitude as fraction of chord length

const BEAD_RADIUS    = 0.10  // nm — matches helix_renderer
const HELIX_RADIUS   = 1.0   // nm — matches helix_renderer / constants.py
const SLAB_DISTANCE  = 0.55  // nm — backbone-to-slab offset param
export const SLAB_LENGTH    = 0.30  // nm (X scale)
export const SLAB_WIDTH     = 0.06  // nm (Y scale)
export const SLAB_THICK     = 0.70  // nm (Z scale)
export const SLAB_OFFSET    = HELIX_RADIUS - SLAB_DISTANCE  // 0.45 nm — same as regular nucleotide slabs

// Slab Z-offset direction lookup — cadnano2 _stapH → +Z, _stapL → −Z.
const HC_PERIOD  = 21
const HC_PLUS_Z  = new Set([0, 7, 14])      // _stapH
const HC_MINUS_Z = new Set([6, 13, 20])     // _stapL
const SQ_PERIOD  = 32
const SQ_PLUS_Z  = new Set([0, 8, 16, 24])  // _stapH
const SQ_MINUS_Z = new Set([7, 15, 23, 31]) // _stapL

// Local geometry templates (duplicated from helix_renderer to avoid coupling).
const GEO_SPHERE   = new THREE.SphereGeometry(BEAD_RADIUS, 8, 6)
const GEO_UNIT_BOX = new THREE.BoxGeometry(1, 1, 1)

// Palette — matches helix_renderer.js / constants.py
const C_SCAFFOLD_BACKBONE = 0x29b6f6
const C_SCAFFOLD_SLAB     = 0x0277bd
const C_UNASSIGNED        = 0x445566

// Scratch vectors (reused every frame to avoid allocation).
const _v0   = new THREE.Vector3()
const _v1   = new THREE.Vector3()
const _v2   = new THREE.Vector3()
const _v3   = new THREE.Vector3()
const _mat  = new THREE.Matrix4()
const _scl  = new THREE.Vector3()
const _col  = new THREE.Color()
const _quat = new THREE.Quaternion()
const ID_QUAT = new THREE.Quaternion()

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Quadratic Bezier: P(t) = (1-t)^2*A + 2(1-t)t*C + t^2*B */
export function bezierAt(A, C, B, t, out) {
  const u = 1 - t
  out.x = u * u * A.x + 2 * u * t * C.x + t * t * B.x
  out.y = u * u * A.y + 2 * u * t * C.y + t * t * B.y
  out.z = u * u * A.z + 2 * u * t * C.z + t * t * B.z
  return out
}

/** Quadratic Bezier derivative: P'(t) = 2(1-t)(C-A) + 2t(B-C) */
export function bezierTangent(A, C, B, t, out) {
  const u = 1 - t
  out.x = 2 * u * (C.x - A.x) + 2 * t * (B.x - C.x)
  out.y = 2 * u * (C.y - A.y) + 2 * t * (B.y - C.y)
  out.z = 2 * u * (C.z - A.z) + 2 * t * (B.z - C.z)
  return out
}

/**
 * Compute the Bezier control point for a 3D crossover arc.
 * The arc bows perpendicular to both the chord and the average helix axis.
 *
 * @param {THREE.Vector3} outBowDir  If provided, receives the normalized bow
 *   direction (away from the Holliday junction).
 */
export function arcControlPoint(posA, posB, nucA, nucB, out, outBowDir) {
  // Chord direction
  _v0.subVectors(posB, posA)
  const dist = _v0.length()
  if (dist < 1e-9) { out.copy(posA); outBowDir?.set(0, 0, 1); return out }
  _v0.divideScalar(dist)  // normalized chord

  // Average helix axis
  _v1.set(nucA.axis_tangent[0], nucA.axis_tangent[1], nucA.axis_tangent[2])
  _v2.set(nucB.axis_tangent[0], nucB.axis_tangent[1], nucB.axis_tangent[2])
  _v1.add(_v2).normalize()

  // Bow direction = chord x avgAxis
  _v2.crossVectors(_v0, _v1)
  const bowLen = _v2.length()

  if (bowLen < 1e-6) {
    // Degenerate: chord parallel to axis — fall back to base_normal of nucA
    _v2.set(nucA.base_normal[0], nucA.base_normal[1], nucA.base_normal[2])
  } else {
    _v2.divideScalar(bowLen)
  }

  if (outBowDir) outBowDir.copy(_v2)

  // Control point = midpoint + bowVec * bowMag
  const bowMag = dist * BOW_FRAC_3D
  out.lerpVectors(posA, posB, 0.5).addScaledVector(_v2, bowMag)
  return out
}

/**
 * Compute slab quaternion for an extra base on a crossover arc.
 * - Face normal (thin dimension, Y) = arc tangent
 * - In-plane Z axis = helical axis direction
 * - In-plane X axis = cross(arcTangent, helixAxis)
 */
export function arcSlabQuaternion(arcTangent, helixAxis, out) {
  const inPlane = _v3.crossVectors(arcTangent, helixAxis)
  const inPlaneLen = inPlane.length()
  if (inPlaneLen < 1e-6) {
    // Degenerate — just use identity
    out.identity()
    return out
  }
  inPlane.divideScalar(inPlaneLen)
  const m = _mat.makeBasis(inPlane, arcTangent, helixAxis)
  out.setFromRotationMatrix(m)
  return out
}

/**
 * Resolve the strand color for a crossover nucleotide.
 * Simplified from helix_renderer's nucColor to avoid coupling.
 */
function xoverNucColor(nuc, stapleColorMap) {
  if (!nuc.strand_id) return C_UNASSIGNED
  if (nuc.strand_type === 'scaffold') return C_SCAFFOLD_BACKBONE
  return stapleColorMap?.get(nuc.strand_id) ?? C_UNASSIGNED
}
function xoverSlabColor(nuc, stapleColorMap) {
  if (!nuc.strand_id) return C_UNASSIGNED
  if (nuc.strand_type === 'scaffold') return C_SCAFFOLD_SLAB
  return stapleColorMap?.get(nuc.strand_id) ?? C_UNASSIGNED
}

// ── Main builder ─────────────────────────────────────────────────────────────

/**
 * Build extra-base bead + slab meshes for crossovers with extra bases.
 *
 * Line rendering (straight segments and arcs) is handled exclusively by
 * unfold_view.js — this module only produces the InstancedMesh objects for
 * extra-base backbone beads and nucleotide slabs along the arc path.
 *
 * @param {object} design      — the current design (must have .crossovers)
 * @param {Array}  geometry    — flat nucleotide array from /design/geometry
 * @param {Map}    [stapleColorMap] — strand_id → hex color (from helix_renderer)
 * @returns {{
 *   group: THREE.Group,
 *   arcData: Array<{nucA, nucB, beadStartIdx, beadCount, xoId}>,
 *   beadsMesh: THREE.InstancedMesh | null,
 *   slabsMesh: THREE.InstancedMesh | null,
 * } | null}
 */
export function buildCrossoverConnections(design, geometry, stapleColorMap) {
  const crossovers = design?.crossovers
  if (!crossovers?.length || !geometry?.length) return null

  // Nucleotide lookup: "helixId:bpIndex:direction" -> nuc object
  const nucMap = new Map()
  for (const nuc of geometry) {
    nucMap.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, nuc)
  }

  // Collect crossovers with extra bases — only these need bead/slab rendering.
  // Regular crossovers (no extra bases) are rendered by the unfold_view arc
  // system which handles selection, lerping, and highlighting automatically.
  const arcCrossovers = []
  for (const xo of crossovers) {
    const n = xo.extra_bases?.length ?? 0
    if (n === 0) continue

    const nucA = nucMap.get(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
    const nucB = nucMap.get(`${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`)
    if (!nucA || !nucB) {
      console.warn(
        `[XOVER 3D] unresolved crossover ${xo.id?.slice(0, 8)}`,
        `half_a=(${xo.half_a.helix_id.slice(0, 8)} bp=${xo.half_a.index} ${xo.half_a.strand})`,
        `half_b=(${xo.half_b.helix_id.slice(0, 8)} bp=${xo.half_b.index} ${xo.half_b.strand})`,
      )
      continue
    }

    const posA = new THREE.Vector3(...nucA.backbone_position)
    const posB = new THREE.Vector3(...nucB.backbone_position)
    arcCrossovers.push({ xo, nucA, nucB, posA, posB })
  }

  if (arcCrossovers.length === 0) return null

  const group = new THREE.Group()
  group.name = 'crossoverConnections'

  // ── Extra-base beads + slabs ──────────────────────────────────────────────
  let totalBeads = 0
  for (const ac of arcCrossovers) totalBeads += ac.xo.extra_bases.length

  const beadsMesh = new THREE.InstancedMesh(
    GEO_SPHERE,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    Math.max(1, totalBeads),
  )
  beadsMesh.frustumCulled = false
  beadsMesh.name = 'xoverExtraBeads'

  const slabsMesh = new THREE.InstancedMesh(
    GEO_UNIT_BOX,
    new THREE.MeshPhongMaterial({ color: 0xffffff, transparent: true, opacity: 0.90 }),
    Math.max(1, totalBeads),
  )
  slabsMesh.frustumCulled = false
  slabsMesh.name = 'xoverExtraSlabs'

  let beadIdx = 0
  const ctrl   = new THREE.Vector3()
  const pt     = new THREE.Vector3()
  const tan    = new THREE.Vector3()
  const avgAx  = new THREE.Vector3()
  const bowDir = new THREE.Vector3()
  const slabPt = new THREE.Vector3()
  const arcData = []

  for (const ac of arcCrossovers) {
    const { xo, nucA, nucB, posA, posB } = ac
    const n = xo.extra_bases.length

    // Compute control point and bow direction (away from Holliday junction)
    arcControlPoint(posA, posB, nucA, nucB, ctrl, bowDir)

    // Average helix axis (for slab orientation)
    avgAx.set(
      nucA.axis_tangent[0] + nucB.axis_tangent[0],
      nucA.axis_tangent[1] + nucB.axis_tangent[1],
      nucA.axis_tangent[2] + nucB.axis_tangent[2],
    ).normalize()

    // Bead + slab instances
    const beadStartIdx = beadIdx
    const beadColor = xoverNucColor(nucA, stapleColorMap)
    const slabColor = xoverSlabColor(nucA, stapleColorMap)

    // Slab Z offset: cadnano2 _stapH positions → +Z, _stapL → −Z.
    const isSQ   = design.lattice_type === 'SQUARE'
    const period = isSQ ? SQ_PERIOD : HC_PERIOD
    const plusZ   = isSQ ? SQ_PLUS_Z  : HC_PLUS_Z
    const minusZ  = isSQ ? SQ_MINUS_Z : HC_MINUS_Z
    const bpMod  = ((xo.half_a.index % period) + period) % period
    let zSign = 0
    if (plusZ.has(bpMod))       zSign =  1
    else if (minusZ.has(bpMod)) zSign = -1
    const zOffset = zSign * Math.abs(avgAx.z) * SLAB_OFFSET * 0.9

    for (let i = 1; i <= n; i++) {
      const t = i / (n + 1)

      // Bead position
      bezierAt(posA, ctrl, posB, t, pt)
      _mat.compose(pt, ID_QUAT, _scl.set(1, 1, 1))
      beadsMesh.setMatrixAt(beadIdx, _mat)
      beadsMesh.setColorAt(beadIdx, _col.setHex(beadColor))

      // Slab — oriented with face normal along arc tangent, width along helix axis.
      bezierTangent(posA, ctrl, posB, t, tan)
      tan.normalize()
      arcSlabQuaternion(tan, avgAx, _quat)
      slabPt.set(pt.x, pt.y, pt.z + zOffset)
      _mat.compose(slabPt, _quat, _scl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
      slabsMesh.setMatrixAt(beadIdx, _mat)
      slabsMesh.setColorAt(beadIdx, _col.setHex(slabColor))

      beadIdx++
    }

    arcData.push({
      xoId: xo.id,
      nucA, nucB,
      beadStartIdx,
      beadCount: n,
      avgAx: avgAx.clone(),
      zOffset,
      bowDir: bowDir.clone(),
    })
  }

  // Finalise instanced meshes
  beadsMesh.instanceMatrix.needsUpdate = true
  if (beadsMesh.instanceColor) beadsMesh.instanceColor.needsUpdate = true
  slabsMesh.instanceMatrix.needsUpdate = true
  if (slabsMesh.instanceColor) slabsMesh.instanceColor.needsUpdate = true
  group.add(beadsMesh)
  group.add(slabsMesh)

  return { group, arcData, beadsMesh, slabsMesh }
}

// ── Live update (called every animation frame) ──────────────────────────────

// Scratch vectors for updateExtraBaseInstances — separate from the build-time
// scratches above so there is no aliasing risk when called from unfold_view.
const _uPt   = new THREE.Vector3()
const _uTan  = new THREE.Vector3()
const _uSlab = new THREE.Vector3()
const _uQuat = new THREE.Quaternion()
const _uMat  = new THREE.Matrix4()
const _uScl  = new THREE.Vector3()

/**
 * Reposition extra-base beads + slabs along an animated Bezier arc.
 * Called once per crossover per animation frame.  Does NOT set needsUpdate —
 * the caller should batch all arcs then call flushExtraBaseMeshes() once.
 *
 * @param {THREE.InstancedMesh} beadsMesh
 * @param {THREE.InstancedMesh} slabsMesh
 * @param {number} beadStartIdx  first instance index for this arc
 * @param {number} beadCount     number of extra bases on this arc
 * @param {THREE.Vector3} posA   arc start (P0)
 * @param {THREE.Vector3} ctrl   arc control point
 * @param {THREE.Vector3} posB   arc end (P1)
 * @param {THREE.Vector3} avgAx  average helix axis (for slab orientation)
 * @param {number} zOffset       slab Z offset for this arc
 */
export function updateExtraBaseInstances(
  beadsMesh, slabsMesh, beadStartIdx, beadCount,
  posA, ctrl, posB, avgAx, zOffset,
) {
  for (let i = 1; i <= beadCount; i++) {
    const t   = i / (beadCount + 1)
    const idx = beadStartIdx + i - 1

    // Bead position
    bezierAt(posA, ctrl, posB, t, _uPt)
    _uMat.compose(_uPt, ID_QUAT, _uScl.set(1, 1, 1))
    beadsMesh.setMatrixAt(idx, _uMat)

    // Slab — oriented with face normal along arc tangent
    bezierTangent(posA, ctrl, posB, t, _uTan)
    _uTan.normalize()
    arcSlabQuaternion(_uTan, avgAx, _uQuat)
    _uSlab.set(_uPt.x, _uPt.y, _uPt.z + zOffset)
    _uMat.compose(_uSlab, _uQuat, _uScl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
    slabsMesh.setMatrixAt(idx, _uMat)
  }
}
