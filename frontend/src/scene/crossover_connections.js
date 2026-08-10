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
import {
  buildCrossoverExtraPlacements,
  crossoverControlPoint,
  crossoverExtraSlabQuaternion,
} from './crossover_extra_placement.js'
import {
  slabConnectionCorner,
  SLAB_CONNECTOR_RADIUS,
} from './helix_renderer.js'

// ── Constants ────────────────────────────────────────────────────────────────

const BEAD_RADIUS    = 0.10  // nm — matches helix_renderer
const HELIX_RADIUS   = 1.0   // nm — matches helix_renderer / constants.py
// Synthetic crossover-extra decoration only; canonical duplex slabs use
// helix_renderer.pairedSlabCenter and have no fixed backbone-to-center offset.
const SLAB_DISTANCE  = 0.55
export const SLAB_LENGTH    = 0.30  // nm (X scale)
export const SLAB_WIDTH     = 0.06  // nm (Y scale)
export const SLAB_THICK     = 0.70  // nm (Z scale)
export const SLAB_OFFSET    = HELIX_RADIUS - SLAB_DISTANCE

// Local geometry templates (duplicated from helix_renderer to avoid coupling).
// `userData.shared` marks them the same way helix_renderer._markShared does: they are
// module-level singletons handed to EVERY build, so a traverse-and-dispose over any one
// consumer's subtree (a ghost copy, an assembly instance being torn down) must skip them
// or it silently guts the meshes every other consumer is still drawing from.
function _markShared(g) { g.userData.shared = true; return g }
const GEO_SPHERE    = _markShared(new THREE.SphereGeometry(BEAD_RADIUS, 8, 6))
const GEO_UNIT_BOX  = _markShared(new THREE.BoxGeometry(1, 1, 1))
const GEO_UNIT_CONE = _markShared(new THREE.ConeGeometry(1, 1, 8))  // backbone arrow, apex +Y
// Exact geometry used by helix_renderer's standard bead→slab rods.
const GEO_UNIT_CYL  = _markShared(new THREE.CylinderGeometry(1.125, 1.125, 1, 8))

export const CONN_RADIUS = 0.075  // nm — matches helix_renderer CONE_RADIUS
const Y_HAT = new THREE.Vector3(0, 1, 0)

// Palette — matches helix_renderer.js / constants.py
const C_SCAFFOLD_BACKBONE = 0x0070bb
const C_SCAFFOLD_SLAB     = 0x0277bd
const C_UNASSIGNED        = 0x445566

// Scratch vectors (reused every frame to avoid allocation).
const _mat  = new THREE.Matrix4()
const _scl  = new THREE.Vector3()
const _col  = new THREE.Color()
const _quat = new THREE.Quaternion()
const ID_QUAT = new THREE.Quaternion()

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Set of every domain-END key `"helix:end_bp:direction"` in the design.
 *
 * Mirrors `domain_end_to_strand` in backend/core/atomistic.py (:2727) — the map the
 * simulation emitters use to decide which half of a crossover the strand EXITS from
 * (its 3′ side = `src`).  Kept as a set because the renderer only needs membership,
 * not the strand id.
 */
export function domainEndKeys(design) {
  const keys = new Set()
  for (const strand of design?.strands ?? []) {
    for (const dom of strand.domains ?? []) {
      keys.add(`${dom.helix_id}:${dom.end_bp}:${dom.direction}`)
    }
  }
  return keys
}

/**
 * Does this crossover's extra-base run need its simulated `k` indices reversed
 * before they address bead instances?
 *
 * Beads are laid out along the Bezier from `half_a` to `half_b`, so bead 0 is the one
 * next to `half_a`.  The emitters (NAMD atomistic.py:2795-2802, oxDNA
 * oxdna_interface.py:394-403) number the run **5′→3′ from `src`**, where `src` is
 * whichever half is a domain END — which is `half_b` whenever the strand happens to
 * enter the junction from the B side.  Same test as the backend, including its
 * default: half_a is `src` only if half_a is a domain end.
 *
 * Without this, a B→A crossover draws its inserts in reverse — each bead lands on its
 * neighbour's coordinates and the backbone connectors cross.
 */
export function extraBaseOrderReversed(xo, endKeys) {
  if (!endKeys) return false
  return !endKeys.has(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
}

/** Bead-instance offset for simulated insert `k` on an arc. */
export function simBeadIndex(k, beadCount, reversed) {
  return reversed ? beadCount - 1 - k : k
}

/**
 * Resolve the strand color for a crossover nucleotide.
 * Checks customColors (strand.color overrides) before palette stapleColorMap.
 * Mirrors helix_renderer's nucColor priority order.
 */
function xoverNucColor(nuc, stapleColorMap, customColors) {
  if (!nuc.strand_id) return C_UNASSIGNED
  if (nuc.strand_type === 'scaffold') return C_SCAFFOLD_BACKBONE
  if (customColors?.[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap?.get(nuc.strand_id) ?? C_UNASSIGNED
}
function xoverSlabColor(nuc, stapleColorMap, customColors) {
  if (!nuc.strand_id) return C_UNASSIGNED
  if (nuc.strand_type === 'scaffold') return C_SCAFFOLD_SLAB
  if (customColors?.[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap?.get(nuc.strand_id) ?? C_UNASSIGNED
}

// ── Main builder ─────────────────────────────────────────────────────────────

/**
 * Build extra-base bead + slab meshes for crossovers with extra bases.
 *
 * Crossover ARC lines (for regular, no-insert crossovers) are handled by
 * unfold_view.js.  This module produces the InstancedMesh objects for extra-base
 * backbone beads, nucleotide slabs, AND the arrow-cone backbone connectors that
 * thread prev_real → eb0 → … → eb_{n-1} → next_real along the insert run.
 *
 * @param {object} design      — the current design (must have .crossovers)
 * @param {Array}  geometry    — flat nucleotide array from /design/geometry
 * @param {Map}    [stapleColorMap] — strand_id → hex color (palette, from buildStapleColorMap)
 * @param {object} [customColors]  — strand_id → hex number (strand.color overrides, from _effectiveColors)
 * @returns {{
 *   group: THREE.Group,
 *   arcData: Array<{nucA, nucB, beadStartIdx, beadCount, xoId}>,
 *   beadsMesh: THREE.InstancedMesh | null,
 *   slabsMesh: THREE.InstancedMesh | null,
 * } | null}
 */
export function buildCrossoverConnections(design, geometry, stapleColorMap, customColors) {
  const crossovers      = design?.crossovers      ?? []
  const forcedLigations = design?.forced_ligations ?? []
  const hasAny = crossovers.length > 0 || forcedLigations.length > 0
  if (!hasAny || !geometry?.length) return null

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

  // Also collect forced ligations with extra bases.
  for (const fl of forcedLigations) {
    const n = fl.extra_bases?.length ?? 0
    if (n === 0) continue

    const nucA = nucMap.get(`${fl.three_prime_helix_id}:${fl.three_prime_bp}:${fl.three_prime_direction}`)
    const nucB = nucMap.get(`${fl.five_prime_helix_id}:${fl.five_prime_bp}:${fl.five_prime_direction}`)
    if (!nucA || !nucB) {
      console.warn(
        `[XOVER 3D] unresolved forced ligation ${fl.id?.slice(0, 8)}`,
        `3p=(${fl.three_prime_helix_id.slice(0, 8)} bp=${fl.three_prime_bp} ${fl.three_prime_direction})`,
        `5p=(${fl.five_prime_helix_id.slice(0, 8)} bp=${fl.five_prime_bp} ${fl.five_prime_direction})`,
      )
      continue
    }

    // Wrap the forced ligation as a crossover-compatible object so the shared
    // rendering loop below works unchanged.
    const xo = {
      id:          fl.id,
      extra_bases: fl.extra_bases,
      half_a:      { helix_id: fl.three_prime_helix_id, index: fl.three_prime_bp, strand: fl.three_prime_direction },
      half_b:      { helix_id: fl.five_prime_helix_id,  index: fl.five_prime_bp,  strand: fl.five_prime_direction  },
    }
    const posA = new THREE.Vector3(...nucA.backbone_position)
    const posB = new THREE.Vector3(...nucB.backbone_position)
    arcCrossovers.push({ xo, nucA, nucB, posA, posB })
  }

  if (arcCrossovers.length === 0) return null

  const group = new THREE.Group()
  group.name     = 'crossoverConnections'   // DEBUG ID — searchable via scene.traverse()
  group.userData = { debugType: 'xoverExtraBasesGroup' }

  // ── Extra-base beads + slabs ──────────────────────────────────────────────
  let totalBeads = 0
  for (const ac of arcCrossovers) totalBeads += ac.xo.extra_bases.length

  const beadsMesh = new THREE.InstancedMesh(
    GEO_SPHERE,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    Math.max(1, totalBeads),
  )
  beadsMesh.frustumCulled = false
  beadsMesh.name     = 'xoverExtraBeads'    // DEBUG ID
  beadsMesh.userData = { debugType: 'xoverExtraBeads' }

  // OPAQUE, matching the base-pair slabs in helix_renderer.js — these were 0.90
  // to track the removed slab-opacity slider (2026-08-02). Per-cluster fades still
  // work through `instanceAlpha`.
  const slabsMesh = new THREE.InstancedMesh(
    GEO_UNIT_BOX,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    Math.max(1, totalBeads),
  )
  // Structure, not overlay — once a per-instance fade turns the material
  // transparent, photo mode must still treat these as solid shadow casters. See
  // the same flag on `baseSlabs` in helix_renderer.js.
  slabsMesh.material.userData.photoForceDepthWrite = true
  slabsMesh.frustumCulled = false
  slabsMesh.name     = 'xoverExtraSlabs'    // DEBUG ID
  slabsMesh.userData = { debugType: 'xoverExtraSlabs' }

  // Backbone connectors: one arrow cone per segment threading
  // prev_real → eb0 → … → eb_{n-1} → next_real, i.e. (beadCount + 1) per arc.
  const totalSegs = totalBeads + arcCrossovers.length
  const connMesh = new THREE.InstancedMesh(
    GEO_UNIT_CONE,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    Math.max(1, totalSegs),
  )
  connMesh.frustumCulled = false
  connMesh.name     = 'xoverExtraConnectors'   // DEBUG ID
  connMesh.userData = { debugType: 'xoverExtraConnectors' }

  // One standard bead→base-slab rod per crossover insert. This is separate from
  // connMesh, which threads the phosphodiester backbone between residue beads.
  const slabConnMesh = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    Math.max(1, totalBeads),
  )
  slabConnMesh.frustumCulled = false
  slabConnMesh.name = 'xoverExtraSlabConnectors'
  slabConnMesh.userData = { debugType: 'xoverExtraSlabConnectors' }

  let beadIdx = 0
  let connIdx = 0
  const ctrl   = new THREE.Vector3()
  const pt     = new THREE.Vector3()
  const tan    = new THREE.Vector3()
  const avgAx  = new THREE.Vector3()
  const bowDir = new THREE.Vector3()
  const slabPt = new THREE.Vector3()
  const arcData = []
  // Which crossovers run half_b → half_a, so simulated insert k must be mirrored
  // onto the A→B bead layout.  Computed once for the whole design.
  const endKeys = domainEndKeys(design)

  for (const ac of arcCrossovers) {
    const { xo, nucA, nucB, posA, posB } = ac
    const n = xo.extra_bases.length
    const simReversed = extraBaseOrderReversed(xo, endKeys)
    const savedTransforms = new Map((design.nucleotide_transforms ?? [])
      .filter(tr => tr.kind === 'extra_base' && tr.crossover_id === xo.id)
      .map(tr => [tr.extra_base_k, new THREE.Matrix4()
        .makeTranslation(...tr.pivot.map((v, i) => v + tr.translation[i]))
        .multiply(new THREE.Matrix4().makeRotationFromQuaternion(new THREE.Quaternion(...tr.rotation)))
        .multiply(new THREE.Matrix4().makeTranslation(...tr.pivot.map(v => -v)))]))

    // Compute control point and bow direction (away from Holliday junction)
    crossoverControlPoint(posA, posB, nucA, nucB, ctrl, bowDir)

    // Average helix axis (for slab orientation)
    avgAx.set(
      nucA.axis_tangent[0] + nucB.axis_tangent[0],
      nucA.axis_tangent[1] + nucB.axis_tangent[1],
      nucA.axis_tangent[2] + nucB.axis_tangent[2],
    ).normalize()

    // Bead + slab instances
    const beadStartIdx = beadIdx
    const connStartIdx = connIdx
    const beadColor = xoverNucColor(nucA, stapleColorMap, customColors)
    const slabColor = xoverSlabColor(nucA, stapleColorMap, customColors)

    const placements = buildCrossoverExtraPlacements({
      xoId: xo.id, count: n, pointA: posA, control: ctrl, pointB: posB,
      helixAxis: avgAx, sequence: xo.extra_bases, simReversed, savedTransforms,
    })
    const posedPoints = placements.map(p => p.center.clone())

    for (const placement of placements) {
      // Bead position comes directly from the representation-neutral residue record.
      _mat.compose(placement.center, ID_QUAT, _scl.set(1, 1, 1))
      beadsMesh.setMatrixAt(beadIdx, _mat)
      beadsMesh.setColorAt(beadIdx, _col.setHex(beadColor))

      // Slab — oriented with face normal along arc tangent, width along helix axis.
      // Construct in the unposed residue frame, then apply the pose ONCE. Previously
      // this used the already-posed bead center and premultiplied pose again.
      crossoverExtraSlabQuaternion(placement.frameQuaternion, _quat)
      slabPt.copy(placement.sourceBaseCenter)
      _mat.compose(slabPt, _quat, _scl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
      if (placement.pose) _mat.premultiply(placement.pose)
      slabsMesh.setMatrixAt(beadIdx, _mat)
      slabsMesh.setColorAt(beadIdx, _col.setHex(slabColor))

      beadIdx++
    }

    // Initial connector positions along the geometric arc (sim frames re-thread
    // them through the live bead positions later via setExtraBaseConnectors).
    const cpts = [posA.clone()]
    cpts.push(...posedPoints)
    cpts.push(posB.clone())
    setExtraBaseConnectors(connMesh, connStartIdx, cpts, n + 1, beadColor)
    setExtraBaseSlabConnectors(
      beadsMesh, slabsMesh, slabConnMesh, beadStartIdx, n, slabColor,
    )
    connIdx += n + 1

    arcData.push({
      xoId: xo.id,
      nucA, nucB,
      beadStartIdx,
      beadCount: n,
      connStartIdx,
      pointA: posA.clone(),
      pointB: posB.clone(),
      sequence: xo.extra_bases,
      savedTransforms,
      avgAx: avgAx.clone(),
      // Simulated inserts arrive numbered 5′→3′ from the strand's exit half; beads are
      // laid out A→B.  True when those two disagree — see extraBaseOrderReversed.
      simReversed,
      bowDir: bowDir.clone(),
      beadBaseColor: beadColor,
      slabBaseColor: slabColor,
    })
  }

  // Finalise instanced meshes
  beadsMesh.instanceMatrix.needsUpdate = true
  if (beadsMesh.instanceColor) beadsMesh.instanceColor.needsUpdate = true
  slabsMesh.instanceMatrix.needsUpdate = true
  if (slabsMesh.instanceColor) slabsMesh.instanceColor.needsUpdate = true
  connMesh.instanceMatrix.needsUpdate = true
  if (connMesh.instanceColor) connMesh.instanceColor.needsUpdate = true
  slabConnMesh.instanceMatrix.needsUpdate = true
  if (slabConnMesh.instanceColor) slabConnMesh.instanceColor.needsUpdate = true
  group.add(beadsMesh)
  group.add(slabsMesh)
  group.add(connMesh)
  group.add(slabConnMesh)

  return { group, arcData, beadsMesh, slabsMesh, connMesh, slabConnMesh }
}

// ── Live update (called every animation frame) ──────────────────────────────

// Scratch vectors for updateExtraBaseInstances — separate from the build-time
// scratches above so there is no aliasing risk when called from unfold_view.
const _uPt   = new THREE.Vector3()
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
 */
export function updateExtraBaseInstances(
  beadsMesh, slabsMesh, beadStartIdx, beadCount,
  posA, ctrl, posB, avgAx,
  simReversed = false, savedTransforms = new Map(), sequence = '',
) {
  const placements = buildCrossoverExtraPlacements({
    xoId: null, count: beadCount, pointA: posA, control: ctrl, pointB: posB,
    helixAxis: avgAx, sequence, simReversed, savedTransforms,
  })
  for (const placement of placements) {
    const idx = beadStartIdx + placement.geometricIndex

    // Bead position
    _uMat.compose(placement.center, ID_QUAT, _uScl.set(1, 1, 1))
    beadsMesh.setMatrixAt(idx, _uMat)

    // Slab — oriented with face normal along arc tangent
    crossoverExtraSlabQuaternion(placement.frameQuaternion, _uQuat)
    _uSlab.copy(placement.sourceBaseCenter)
    _uMat.compose(_uSlab, _uQuat, _uScl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
    if (placement.pose) _uMat.premultiply(placement.pose)
    slabsMesh.setMatrixAt(idx, _uMat)
  }
}

/**
 * Split FEM/trajectory position updates into real-nucleotide updates and a
 * per-crossover map of simulation-driven extra-base positions.
 *
 * Extra-base inserts arrive with the sentinel key shape
 * ``{helix_id:"__xb__", bp_index:<crossover_id>, direction:<k>}`` (k is the 0-based
 * index within the crossover's insert run).  Real nucleotides pass through
 * untouched for the helix renderer.
 *
 * @returns {{real: Array|undefined, simXb: Map<string, Map<number, {pos:number[], normal:number[]}>>|null}}
 *   ``simXb`` is null when there are no inserts in the frame (Bezier fallback).
 *   ``real`` is the original array reference when there were no inserts at all.
 */
export function partitionExtraBaseUpdates(updates) {
  if (!updates) return { real: updates, simXb: null }
  let simXb = null
  let real = updates
  for (let i = 0; i < updates.length; i++) {
    if (updates[i].helix_id === '__xb__') { real = null; break }
  }
  if (real) return { real: updates, simXb: null }   // common case: no inserts, no copy
  real = []
  for (const u of updates) {
    if (u.helix_id !== '__xb__') { real.push(u); continue }
    if (!simXb) simXb = new Map()
    const cid = u.bp_index
    let m = simXb.get(cid)
    if (!m) { m = new Map(); simXb.set(cid, m) }
    m.set(u.direction | 0, {
      pos: u.backbone_position,
      normal: [u.nx ?? 0, u.ny ?? 0, u.nz ?? 0],
    })
  }
  return { real, simXb }
}

const _simNorm = new THREE.Vector3()
const _simTan  = new THREE.Vector3()
const _simAxis = new THREE.Vector3()
const _simBasis = new THREE.Matrix4()

/**
 * Slab orientation for a SIMULATED extra base — the same basis helix_renderer builds
 * for every real nucleotide it drives from an MD frame (:3416-3418):
 *
 *   X (SLAB_LENGTH  0.30) = tangential  = axis × baseNormal
 *   Y (SLAB_WIDTH   0.06) = helix axis  — the thin stacking direction
 *   Z (SLAB_THICK   0.70) = baseNormal  — the long axis, backbone → base
 *
 * This simulation-only projection uses the trajectory's base normal directly instead
 * of the native atom-template frame used by default crossover placements.
 */
export function simSlabQuaternion(baseNormal, helixAxis, out) {
  _simAxis.copy(helixAxis)
  _simTan.crossVectors(_simAxis, baseNormal)
  if (_simTan.lengthSq() < 1e-12) {
    // baseNormal ∥ axis — pick any perpendicular so the basis stays well-formed.
    _simTan.set(1, 0, 0).cross(baseNormal)
    if (_simTan.lengthSq() < 1e-12) _simTan.set(0, 1, 0).cross(baseNormal)
  }
  _simTan.normalize()
  _simBasis.makeBasis(_simTan, _simAxis, baseNormal)
  return out.setFromRotationMatrix(_simBasis)
}

/**
 * Place a SINGLE extra-base bead + slab at its REAL simulated position (from an
 * oxDNA/MD relaxed frame or trajectory), instead of the geometric Bezier arc.
 * The bead sits at the backbone position; the slab points its long axis along the
 * per-frame base normal (a1) and sits one SLAB_OFFSET inward toward the base — the
 * same convention helix_renderer uses for real nucleotides, so an insert's plate
 * reads the same way as the ones flanking it.
 * Does NOT set needsUpdate — batch then call flushExtraBaseMeshes() once.
 *
 * @param {number} idx          instance index (beadStartIdx + k)
 * @param {ArrayLike<number>} pos  real backbone position (nm) [x,y,z]
 * @param {ArrayLike<number>} baseNormal  per-frame a1 [nx,ny,nz]
 * @param {THREE.Vector3} avgAx average helix axis (slab in-plane reference)
 */
export function setExtraBaseInstanceFromSim(beadsMesh, slabsMesh, idx, pos, baseNormal, avgAx) {
  _uPt.set(pos[0], pos[1], pos[2])
  _uMat.compose(_uPt, ID_QUAT, _uScl.set(1, 1, 1))
  beadsMesh.setMatrixAt(idx, _uMat)

  _simNorm.set(baseNormal?.[0] ?? 0, baseNormal?.[1] ?? 0, baseNormal?.[2] ?? 0)
  if (_simNorm.lengthSq() < 1e-12) _simNorm.set(0, 0, 1)
  _simNorm.normalize()
  simSlabQuaternion(_simNorm, avgAx, _uQuat)
  _uSlab.copy(_uPt).addScaledVector(_simNorm, SLAB_OFFSET)
  _uMat.compose(_uSlab, _uQuat, _uScl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
  slabsMesh.setMatrixAt(idx, _uMat)
}

// Scratch for connector-cone placement — separate set so a per-frame connector
// sync can't alias the bead/slab update scratches above.
const _kDir  = new THREE.Vector3()
const _kMid  = new THREE.Vector3()
const _kQuat = new THREE.Quaternion()
const _kMat  = new THREE.Matrix4()
const _kScl  = new THREE.Vector3()
const _kCol  = new THREE.Color()

// Scratch for the bead→slab rods. These derive from the actual live instance
// matrices, so saved poses, animated arcs, and simulation placement cannot diverge.
const _bsBeadMat = new THREE.Matrix4()
const _bsSlabMat = new THREE.Matrix4()
const _bsBeadPos = new THREE.Vector3()
const _bsBeadQuat = new THREE.Quaternion()
const _bsBeadScale = new THREE.Vector3()
const _bsSlabPos = new THREE.Vector3()
const _bsSlabQuat = new THREE.Quaternion()
const _bsSlabScale = new THREE.Vector3()
const _bsCorner = new THREE.Vector3()
const _bsDir = new THREE.Vector3()
const _bsMid = new THREE.Vector3()
const _bsRodQuat = new THREE.Quaternion()
const _bsScale = new THREE.Vector3()
const _bsColor = new THREE.Color()

/**
 * Rebuild crossover inserts' bead→slab rods from the rendered bead/slab matrices.
 * This is the same N3-corner attachment and radius used by standard Full residues.
 */
export function setExtraBaseSlabConnectors(
  beadsMesh, slabsMesh, slabConnMesh, beadStartIdx, beadCount, colorHex = null,
) {
  if (!beadsMesh || !slabsMesh || !slabConnMesh) return
  for (let i = 0; i < beadCount; i++) {
    const idx = beadStartIdx + i
    beadsMesh.getMatrixAt(idx, _bsBeadMat)
    slabsMesh.getMatrixAt(idx, _bsSlabMat)
    _bsBeadMat.decompose(_bsBeadPos, _bsBeadQuat, _bsBeadScale)
    _bsSlabMat.decompose(_bsSlabPos, _bsSlabQuat, _bsSlabScale)

    const rendered = _bsBeadScale.lengthSq() > 1e-18 && _bsSlabScale.lengthSq() > 1e-18
    slabConnectionCorner(
      _bsSlabPos, _bsSlabQuat, _bsBeadPos,
      _bsSlabScale.x * 0.5, _bsSlabScale.z * 0.5, _bsCorner,
    )
    _bsDir.copy(_bsCorner).sub(_bsBeadPos)
    const length = Math.max(0.001, _bsDir.length())
    _bsMid.copy(_bsBeadPos).add(_bsCorner).multiplyScalar(0.5)
    _bsRodQuat.setFromUnitVectors(Y_HAT, _bsDir.divideScalar(length))
    _bsScale.set(
      rendered ? SLAB_CONNECTOR_RADIUS : 0,
      rendered ? length : 0,
      rendered ? SLAB_CONNECTOR_RADIUS : 0,
    )
    slabConnMesh.setMatrixAt(idx, _bsSlabMat.compose(_bsMid, _bsRodQuat, _bsScale))
    if (colorHex != null) slabConnMesh.setColorAt(idx, _bsColor.setHex(colorHex))
  }
}

/**
 * Place the backbone-arrow connector cones threading one extra-base run:
 *   posA(real) → bead0 → … → bead_{n-1} → posB(real).
 * Mirrors the helix_renderer backbone cone — one cone per segment, apex along
 * the chain direction, radius = CONN_RADIUS.  Does NOT set needsUpdate.
 *
 * @param {THREE.InstancedMesh} connMesh
 * @param {number} connStartIdx  first cone instance index for this arc
 * @param {ArrayLike<THREE.Vector3>} points  ordered path points (length ≥ segCount+1)
 * @param {number} segCount      number of segments (= beadCount + 1)
 * @param {number|null} colorHex  strand color; null leaves color untouched
 */
export function setExtraBaseConnectors(connMesh, connStartIdx, points, segCount, colorHex) {
  for (let s = 0; s < segCount; s++) {
    const from = points[s]
    const to   = points[s + 1]
    _kDir.subVectors(to, from)
    const dist = _kDir.length()
    const h = Math.max(1e-4, dist)
    _kDir.multiplyScalar(dist > 1e-9 ? 1 / dist : 0)
    _kMid.copy(from).addScaledVector(_kDir, dist / 2)
    _kQuat.setFromUnitVectors(Y_HAT, dist > 1e-9 ? _kDir : Y_HAT)
    _kMat.compose(_kMid, _kQuat, _kScl.set(CONN_RADIUS, h, CONN_RADIUS))
    connMesh.setMatrixAt(connStartIdx + s, _kMat)
    if (colorHex != null) connMesh.setColorAt(connStartIdx + s, _kCol.setHex(colorHex))
  }
}

/**
 * Scalar (flexibility-map) colour for every backbone connector cone of ONE extra-base
 * arc, in segment order.
 *
 * Mirrors the helix_renderer bond-cone convention exactly: a cone takes the colour of
 * the nucleotide it points away FROM (`coneEntries[].fromNuc`).  The chain is
 *   posA(real) → eb0 → … → eb_{n-1} → posB(real)
 * so segment 0 starts at the real nucleotide `nucA`, and segments 1..n start at
 * inserts 0..n-1.  The trailing real nucleotide `nucB` is only ever a segment END, so
 * it never colours a cone — same as a real backbone, where the last nucleotide of a
 * strand owns no outgoing cone.
 *
 * @param {{xoId:*, nucA:object, beadCount:number}} arc  one entry of buildCrossoverConnections' arcData
 * @param {(key:string)=>number|undefined} lookup        colorByKey accessor (hex int)
 * @returns {(number|null)[]} length beadCount+1; null = no scalar datum, leave as-is
 */
export function extraBaseConnectorScalarColors(arc, lookup) {
  const n = arc.beadCount
  const out = new Array(n + 1)
  const norm = (h) => (h === undefined || h === null) ? null : h
  const a = arc.nucA
  // Real nucleotides are keyed "helix:bp:dir:copy"; rmsfColorMap also emits the
  // 3-part form for copy 0.  We don't track the loop-copy of a crossover endpoint,
  // so fall back to copy 0 — a missing key just leaves that cone alone.
  out[0] = a
    ? norm(lookup(`${a.helix_id}:${a.bp_index}:${a.direction}`) ?? lookup(`${a.helix_id}:${a.bp_index}:${a.direction}:0`))
    : null
  // Segment s starts at bead s−1.  Which INSERT occupies that bead depends on the
  // arc's direction — simBeadIndex is its own inverse, so it maps both ways.
  for (let s = 1; s <= n; s++) {
    const k = simBeadIndex(s - 1, n, arc.simReversed)
    out[s] = norm(lookup(`__xb__:${arc.xoId}:${k}`))
  }
  return out
}

/** Zero-scale an arc's connector cones (hidden crossover), keeping their position. */
export function hideExtraBaseConnectors(connMesh, connStartIdx, segCount) {
  for (let s = 0; s < segCount; s++) {
    connMesh.getMatrixAt(connStartIdx + s, _kMat)
    _kMid.setFromMatrixPosition(_kMat)
    connMesh.setMatrixAt(connStartIdx + s, _kMat.compose(_kMid, ID_QUAT, _kScl.set(0, 0, 0)))
  }
}
