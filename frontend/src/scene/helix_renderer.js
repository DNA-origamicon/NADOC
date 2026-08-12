/**
 * Helix renderer — builds Three.js instanced objects from geometry API data.
 *
 * Uses THREE.InstancedMesh for all nucleotide components so the entire design
 * renders in 4 WebGL draw calls regardless of helix count or length:
 *   iSpheres  — backbone beads (all non-5′ nucleotides)
 *   iCubes    — 5′-end markers (one per strand)
 *   iCones    — strand-direction connectors
 *   iSlabs    — base-pair orientation slabs
 *   iSlabConnectors — thin instanced rods linking beads to slab N3 corners
 *
 * Entry shapes exposed in backboneEntries / coneEntries / slabEntries:
 *   backbone  { instMesh, id, nuc, pos, defaultColor }
 *   cone      { instMesh, id, fromNuc, toNuc, strandId,
 *               midPos, quat, coneHeight, coneRadius, defaultColor }
 *   slab      { instMesh, id, nuc, quat, bnDir, bbPos, defaultColor }
 *
 * Callers update instance colors/scales via the helper methods exposed on the
 * return object (setEntryColor, setBeadScale, setConeXZScale) rather than
 * accessing mesh.material directly.
 */

import * as THREE from 'three'
import { baseKey } from './base_ref.js'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import {
  impostorsEnabled,
  IMPOSTOR_QUAD,
  makeImpostorPhongMaterial,
  installSphereImpostorRaycast,
  enableImpostorInstanceAlpha,
} from './impostor_material.js'

import {
  C,
  STAPLE_PALETTE,
  BASE_COLORS,
  buildNucLetterMap,
  buildClusterLookup,
  buildClusterColorLookup,
  buildStapleColorMap,
  nucColor,
  nucSlabColor,
  nucArrowColor,
} from './helix_renderer/palette.js'
import { installInstanceAlpha, installInstanceAlphaGeometry } from './instance_alpha.js'
import { clusterAlphaForNuc } from './cluster_entries.js'

// ── Constants ─────────────────────────────────────────────────────────────────

const HELIX_RADIUS    = 1.0    // nm — must match backend/core/constants.py
const BDNA_RISE_PER_BP = 0.334  // nm/bp — must match backend/core/constants.py
// Must match `_AXIS_SAMPLE_STEP` in backend/core/deformation.py. tubeSamp from
// deformed_helix_axes() is one entry every AXIS_SAMPLE_STEP bp along the
// helix's local bp axis, with length_bp-1 appended last.
const AXIS_SAMPLE_STEP = 7

// Re-export palette helpers consumed by external modules (main.js, etc.).
export { buildNucLetterMap, buildStapleColorMap }

// ── Shared geometries ─────────────────────────────────────────────────────────

export const BEAD_RADIUS  = 0.10
export const CONE_RADIUS  = 0.075
// The slab boundary extends this far past the associated bead center. This makes
// bead/slab contact visually unambiguous without burying the bead in the slab.
export const SLAB_BEAD_CENTER_PENETRATION = 0.02
export const SLAB_N3_CORNER_SIGN = 1
export const SLAB_CONNECTOR_RADIUS = 0.025

// Representation name → `setDetailLevel()` argument for the CG representations.
// Lower = more detail (full=0 > beads=1 > cylinders=2). Lives here because
// `setDetailLevel` is part of the control surface buildHelixObjects returns;
// the assembly renderers pass these values straight back into it.
export const CG_LOD = { full: 0, beads: 1, cylinders: 2 }

const Y_HAT       = new THREE.Vector3(0, 1, 0)
const ID_QUAT     = new THREE.Quaternion()

// Module-level geometry templates. These are SHARED across every helix /
// instance the renderer builds — if any single disposeGroup traversal
// called `.dispose()` on them, it would invalidate the buffer for everyone
// else (BufferGeometry.dispose frees GPU memory + emits a "dispose" event
// that Three.js material wrappers listen to). We tag every template with
// `userData.shared = true` so traverse-and-dispose call sites can skip
// them. assembly_renderer's _disposeGroup honours this flag.
function _markShared(g) { g.userData.shared = true; return g }
const GEO_SPHERE    = _markShared(new THREE.SphereGeometry(BEAD_RADIUS, 10, 8))
const GEO_CUBE_5P   = _markShared(new THREE.BoxGeometry(0.18, 0.18, 0.18))
const GEO_UNIT_BOX  = _markShared(new THREE.BoxGeometry(1, 1, 1))
const GEO_UNIT_CONE = _markShared(new THREE.ConeGeometry(1, 1, 8))
const GEO_UNIT_CYL  = _markShared(new THREE.CylinderGeometry(1.125, 1.125, 1, 8))  // LOD level-2 domain cylinder (r=2.25nm/2)
// LOD overhang half-cylinder: 180° wall + half-disc caps + a flat rectangular
// face capping the open diametral side, so the shape reads as a closed
// half-cylinder instead of an open trough.  Wall sweeps from theta=0 (+Z) to
// theta=π (-Z) on the +X half; the flat cap sits in the YZ plane at x=0,
// normal -X (outward from the closed interior).  DoubleSide material in the
// InstancedMesh keeps lighting correct from either viewing angle.
const GEO_HALF_CYL  = _markShared((() => {
  const wall = new THREE.CylinderGeometry(1.125, 1.125, 1, 8, 1, false, 0, Math.PI)
  const face = new THREE.PlaneGeometry(2.25, 1).rotateY(-Math.PI / 2)
  const merged = mergeGeometries([wall, face])
  wall.dispose()
  face.dispose()
  return merged
})())
const GEO_FLUORO_SPHERE = _markShared(new THREE.SphereGeometry(0.25, 12, 10))       // fluorophore modification bead

const DIRECT_CONNECTION_TYPES = new Set(['root-to-root', 'end-to-root'])

export function directConnectedOverhangIds(design) {
  const ids = new Set()
  for (const b of design?.overhang_bindings ?? []) {
    if (b?.bound === false || !DIRECT_CONNECTION_TYPES.has(b?.connection_type)) continue
    if (b.driver_oh_id) ids.add(b.driver_oh_id)
    if (b.driven_oh_id) ids.add(b.driven_oh_id)
    if (!b.driver_oh_id && !b.driven_oh_id) {
      if (b.overhang_a_id) ids.add(b.overhang_a_id)
      if (b.overhang_b_id) ids.add(b.overhang_b_id)
    }
  }
  for (const d of design?.duplexes ?? []) {
    if (d?.bound === false || !DIRECT_CONNECTION_TYPES.has(d?.connection_type)) continue
    if (d.left?.overhang_id) ids.add(d.left.overhang_id)
    if (d.right?.overhang_id) ids.add(d.right.overhang_id)
  }
  return ids
}

// Modification type → Three.js hex color (display color in the 3D scene)
const MODIFICATION_COLORS = {
  cy3:     0xff8c00,
  cy5:     0xcc0000,
  fam:     0x00cc00,
  tamra:   0xcc00cc,
  bhq1:    0x444444,
  bhq2:    0x666666,
  atto488: 0x00ffcc,
  atto550: 0xffaa00,
  biotin:  0xeeeeee,
}

/**
 * Fluorescence-mode emission colors — approximate actual fluorophore emission
 * wavelengths for use in the Fluorescence View toggle.
 * BHQ-1, BHQ-2 (quenchers) and Biotin (non-fluorescent) are omitted; the
 * absence of an entry signals "no glow for this modification".
 */
export const FLUORO_EMISSION_COLORS = new Map([
  ['cy3',     0xddff00],   // ~570 nm  yellow-green
  ['cy5',     0xff1a1a],   // ~670 nm  deep red
  ['fam',     0x00ff66],   // ~520 nm  bright green
  ['tamra',   0xff6600],   // ~580 nm  orange
  ['atto488', 0x11ff55],   // ~520 nm  green
  ['atto550', 0xbbff00],   // ~576 nm  yellow-green
])

// ── Reusable temporaries (never held across async boundaries) ─────────────────

const _tColor  = new THREE.Color()
const _tMatrix = new THREE.Matrix4()
const _tScale  = new THREE.Vector3()
const _tPos    = new THREE.Vector3()
const _physDir  = new THREE.Vector3()   // shared direction scratch (cylinder/cone/segment orientation)
const _physDir2 = new THREE.Vector3()   // second scratch for applyPositionLerp
const _saDir   = new THREE.Vector3()   // straight-axis direction scratch (applyUnfoldOffsets)
// Axis-segment per-bp-range scratch (reused inside applyPositionLerp's
// straight-helix segment recomputation loop).
const _segS_from = new THREE.Vector3()
const _segE_from = new THREE.Vector3()
const _segS_to   = new THREE.Vector3()
const _segE_to   = new THREE.Vector3()
const _segS      = new THREE.Vector3()
const _segE      = new THREE.Vector3()

// ── Cluster-transform scratch (reused per-frame) ──────────────────────────────
const _clusterV = new THREE.Vector3()
const _clusterQ = new THREE.Quaternion()


// ── Deform-lerp slab scratch (reused per-frame, never held across awaits) ─────
const _slabAxisDir = new THREE.Vector3()
const _slabProj    = new THREE.Vector3()
const _slabBnS     = new THREE.Vector3()   // straight base-normal
const _slabTanS    = new THREE.Vector3()   // straight tangential (for basis)
const _slabCenterS = new THREE.Vector3()   // straight slab center
const _slabCenterD = new THREE.Vector3()   // deformed slab center
const _slabCenterL = new THREE.Vector3()   // lerped slab center
const _slabBaseS   = new THREE.Vector3()   // translated authoritative base position
const _slabMateBaseS = new THREE.Vector3() // translated paired base position
const _slabRescaleQ   = new THREE.Quaternion()  // scratch for the in-place slab rescale
const _slabQuatS      = new THREE.Quaternion()
const _slabQuatL      = new THREE.Quaternion()
const _slabBasis      = new THREE.Matrix4()
const _straightHeadQ  = new THREE.Quaternion()  // scratch for arrowhead lerp
const _cylQ           = new THREE.Quaternion()  // scratch for helix cylinder LOD
// 180° roll about the cylinder axis (Y).  GEO_HALF_CYL covers the +X half;
// rolling a copy of an overhang's orientation by π puts the linker's binding
// (complement) half on the −X half so the two together read as one full,
// two-toned duplex cylinder.
const _QUAT_ROLL_PI   = new THREE.Quaternion().setFromAxisAngle(Y_HAT, Math.PI)
const _cylQRolled     = new THREE.Quaternion()  // scratch for the rolled binding-half orientation

// ── Instance update helpers ───────────────────────────────────────────────────

function _setInstColor(entry, hexColor) {
  entry.instMesh.setColorAt(entry.id, _tColor.setHex(hexColor))
  if (entry.instMesh.instanceColor) entry.instMesh.instanceColor.needsUpdate = true
  // A slab's bead-to-slab rod is part of that slab, not an independently-coloured
  // overlay. Keep it on the exact same instance colour for sidebar colouring modes,
  // strand edits, highlights and every other caller of the shared recolour helper.
  if (entry.connectorMesh && entry.connectorId != null) {
    entry.connectorMesh.setColorAt(entry.connectorId, _tColor.setHex(hexColor))
    if (entry.connectorMesh.instanceColor) {
      entry.connectorMesh.instanceColor.needsUpdate = true
    }
  }
}

/**
 * Set backbone bead scale (uniform).  Beads have no rotation so the matrix is
 * compose(pos, identity, (s,s,s)).
 */
function _setBeadScale(entry, s) {
  _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(s, s, s))
  entry.instMesh.setMatrixAt(entry.id, _tMatrix)
  entry.instMesh.instanceMatrix.needsUpdate = true
}

/**
 * Set cone XZ radius while preserving its stored midPos, quat, and coneHeight.
 */
function _setConeXZScale(entry, r) {
  _tMatrix.compose(entry.midPos, entry.quat, _tScale.set(r, entry.coneHeight, r))
  entry.instMesh.setMatrixAt(entry.id, _tMatrix)
  entry.instMesh.instanceMatrix.needsUpdate = true
}

// ── Reference-geometry transparency ────────────────────────────────────────────
//
// Reference strands render translucent (true per-instance alpha) and the View
// toggle hides them. Per-instance alpha needs an InstancedBufferAttribute, which
// must live on a (cloned) per-mesh geometry — the GEO_* templates are shared.
// Only installed for designs that actually contain reference strands, so normal
// designs keep their opaque, non-transparent bead materials (zero regression).
const REF_ALPHA = 0.4   // reference geometry opacity in the 3D scene

function _setEntryAlpha(entry, a) {
  const attr = entry.instMesh._instanceAlpha
  if (attr) {
    attr.setX(entry.id, a)
    attr.needsUpdate = true
  }
  const connectorAttr = entry.connectorMesh?._instanceAlpha
  if (connectorAttr) {
    connectorAttr.setX(entry.connectorId, a)
    connectorAttr.needsUpdate = true
  }
}

/**
 * Install per-instance alpha, routing impostor materials through their own
 * composed patch. `applyInstanceAlphaMaterial` ASSIGNS onBeforeCompile, which on an
 * impostor would wipe the billboard + gl_FragDepth patch and leave flat quads — so
 * impostors get the geometry half plus an opt-in flag their own factory reads.
 * This is why `iSpheres`/`iFluoros` used to be skipped entirely under impostors.
 */
function _installInstanceAlpha(mesh) {
  if (!mesh) return
  if (mesh.material?.userData?.isImpostor) {
    if (installInstanceAlphaGeometry(mesh)) enableImpostorInstanceAlpha(mesh.material)
    return
  }
  installInstanceAlpha(mesh)
}

// ── Slab helpers ──────────────────────────────────────────────────────────────

export function slabQuaternion(bnDir, tanDir) {
  // base_normal is the measured cross-strand vector and may contain an axial
  // component (the two base centroids can be axially staggered).  makeBasis
  // requires an ORTHONORMAL frame; feeding it the raw non-perpendicular pair
  // creates a sheared matrix which setFromRotationMatrix misreads as a rotation.
  // The slab's largest face must be normal to the helix axis, so Gram-Schmidt
  // the long direction into that plane before constructing the rotation.
  const axial = new THREE.Vector3().copy(tanDir).normalize()
  const inPlaneNormal = new THREE.Vector3().copy(bnDir)
    .addScaledVector(axial, -bnDir.dot(axial))
    .normalize()
  const tangential = new THREE.Vector3().crossVectors(axial, inPlaneNormal).normalize()
  const m = new THREE.Matrix4().makeBasis(tangential, axial, inPlaneNormal)
  return new THREE.Quaternion().setFromRotationMatrix(m)
}

/**
 * Display centre for one slab in a base pair.
 *
 * The two base-ring centroids can carry different measured axial offsets.  A box
 * centred independently on each therefore has two parallel but non-coplanar largest
 * faces. Put both centers on their mean axis-normal plane. The paired base positions
 * determine that shared axial plane. The associated
 * bead and slab orientation determine only the outward radial contact shift.
 */
export function pairedSlabCenter(
  beadPos,
  basePos,
  mateBasePos,
  axisTangent,
  baseNormal,
  out = new THREE.Vector3(),
) {
  out.copy(basePos)

  if (mateBasePos) {
    const ownAxial = out.dot(axisTangent)
    const mateAxial = mateBasePos.dot(axisTangent)
    out.addScaledVector(axisTangent, (mateAxial - ownAxial) * 0.5)
  }

  // Move radially outward until the oriented slab rectangle reaches its bead.
  // The move is perpendicular to the axis, so paired top/bottom faces stay coplanar.
  _physDir.copy(beadPos).sub(out)
  _physDir.addScaledVector(axisTangent, -_physDir.dot(axisTangent))
  const beadDistance = _physDir.length()
  if (beadDistance > 1e-9) {
    _physDir.divideScalar(beadDistance)
    _slabBnS.copy(baseNormal)
      .addScaledVector(axisTangent, -baseNormal.dot(axisTangent))
      .normalize()
    _slabTanS.crossVectors(axisTangent, _slabBnS).normalize()
    // GEO_UNIT_BOX scaled to x=.30 and z=.70: largest-face half-extents .15/.35.
    const support = Math.abs(_physDir.dot(_slabTanS)) * 0.15
                  + Math.abs(_physDir.dot(_slabBnS)) * 0.35
    const shift = Math.max(0, beadDistance - support + SLAB_BEAD_CENTER_PENETRATION)
    out.addScaledVector(_physDir, shift)
  }

  return out
}

/** Translate a nucleotide's authoritative equilibrium base site by its live bead
 * displacement. Simulation overlays currently carry P/bead positions + orientation,
 * not a second base-centroid position; keeping the equilibrium base fixed mixes two
 * frames and was the full-vs-atomistic MD display regression. */
export function translatedBasePosition(
  basePosition, equilibriumBead, liveBead, out = new THREE.Vector3(),
) {
  return out.copy(basePosition).add(liveBead).sub(equilibriumBead)
}

/**
 * N3-side attachment corner for a rendered slab.
 *
 * In the canonical slab basis local +X is the chemically stable N3 side,
 * while local Z runs across the base pair.  Pick the +/-Z edge facing the
 * nucleotide's own backbone bead, yielding one corner rather than the old,
 * visually ambiguous edge midpoint.
 */
export function slabConnectionCorner(
  slabCenter,
  slabQuat,
  beadPos,
  halfLength = 0.15,
  halfThickness = 0.35,
  out = new THREE.Vector3(),
) {
  _physDir.copy(beadPos).sub(slabCenter).applyQuaternion(_slabRescaleQ.copy(slabQuat).invert())
  const zSign = _physDir.z < 0 ? -1 : 1
  return out.set(SLAB_N3_CORNER_SIGN * halfLength, 0, zSign * halfThickness)
    .applyQuaternion(slabQuat)
    .add(slabCenter)
}

// ── Main builder ──────────────────────────────────────────────────────────────

/**
 * @param {string} [lod='full']  LOD level — 'full' (default), 'beads', or
 *   'cylinders'. Skips allocating heavy per-bp InstancedMesh buffers when
 *   the LOD doesn't need them. Without this skip, a 61k-bp design at
 *   'cylinders' rep would still allocate ~250 MB of hidden bead/cone/slab
 *   instance buffers per copy — devastating for polymerized assemblies.
 *
 *   The downstream control surface (setDetailLevel, applyFemPositions, etc.)
 *   iterates the per-entry arrays returned by this function. When the
 *   corresponding mesh was skipped those arrays are empty, so the loops
 *   are no-ops — no special-casing needed at the call sites.
 *
 *   Switching back to a heavier LOD requires a rebuild of the instance —
 *   setDetailLevel(...) returns `{ needsRebuild: true }` so the assembly
 *   renderer can invalidate and rebuild.
 */

/**
 * Set a cross-fade material's opacity and the depthWrite/transparent flags that
 * MUST track it.  An opacity-0 transparent mesh that still has depthWrite=true is
 * an INVISIBLE OCCLUDER: it writes the depth buffer and punches voids into
 * whatever is behind it — e.g. the faded straight-proxy cylinders (opacity 0 in
 * the deformed view) were occluding the bent tubes behind them at certain camera
 * angles. And a transparent mesh at full opacity causes depth-sort artifacts
 * among the 100s of overlapping curved tubes.  So: write depth only when
 * (near-)opaque, be transparent only while actually blending.
 */
function _fadeMat(mat, opacity) {
  mat.opacity = opacity
  const opaque = opacity >= 0.996
  mat.transparent = !opaque
  mat.depthWrite  = opaque
}

/**
 * Sort one strand's nucleotides into 5′→3′ backbone order (in place, also returned).
 *
 * Ordering: by domain, then bp_index (ascending for FORWARD, descending for REVERSE),
 * then LOOP-COPY index. A loop insertion emits several nucleotides at ONE bp_index,
 * stacked up the helix axis in emission order (copy 0 lowest). They must be threaded
 * in the direction the strand travels the axis — a FORWARD strand climbs (0→n-1), a
 * REVERSE strand descends (n-1→0) — otherwise the backbone connector zig-zags down
 * into the bulge and back out (an out-of-order over-stretched bond). Copy index is the
 * per-(helix,bp,dir) appearance order in `nucs`, which the geometry list emits ascending.
 */
export function orderStrandNucleotides(nucs) {
  const copyIdx = new Map()   // nuc → copy index
  const seen    = new Map()   // "helix:bp:dir" → running count
  for (const n of nucs) {
    const k = `${n.helix_id}:${n.bp_index}:${n.direction}`
    const c = seen.get(k) ?? 0
    copyIdx.set(n, c)
    seen.set(k, c + 1)
  }
  nucs.sort((a, b) => {
    const di = (a.domain_index ?? 0) - (b.domain_index ?? 0)
    if (di !== 0) return di
    const bpDiff = a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
    if (bpDiff !== 0) return bpDiff
    const ca = copyIdx.get(a) ?? 0
    const cb = copyIdx.get(b) ?? 0
    return a.direction === 'FORWARD' ? ca - cb : cb - ca
  })
  return nucs
}

export function buildHelixObjects(geometry, design, scene, customColors = {}, loopStrandIds = [], helixAxes = null, lod = 'full') {
  const loopSet = new Set(loopStrandIds)
  const independentPoses = new Map((design?.nucleotide_transforms ?? [])
    .filter(t => t.kind === 'base')
    .map(t => [`${t.helix_id}:${t.bp_index}:${t.direction}:${t.copy_k ?? 0}`, t]))
  const poseMatrix = (pose) => new THREE.Matrix4()
    .makeTranslation(...pose.pivot.map((v, i) => v + pose.translation[i]))
    .multiply(new THREE.Matrix4().makeRotationFromQuaternion(new THREE.Quaternion(...pose.rotation)))
    .multiply(new THREE.Matrix4().makeTranslation(...pose.pivot.map(v => -v)))

  // LOD skip flags. Order matters: 'cylinders' implies 'beads' skips too.
  const _initialLodKey = lod === 'cylinders' ? 'cylinders' : (lod === 'beads' ? 'beads' : 'full')
  const _skipBeads   = _initialLodKey === 'cylinders'
  const _skipCones   = _initialLodKey === 'cylinders'
  const _skipFluoros = _initialLodKey === 'cylinders'
  const _skipSlabs   = _initialLodKey !== 'full'   // slabs only at full LOD
  // Track what was built so setDetailLevel can detect when an upgrade
  // requires a rebuild (because the heavier meshes were never allocated).
  const _builtFlags = {
    beads:   !_skipBeads,
    cones:   !_skipCones,
    fluoros: !_skipFluoros,
    slabs:   !_skipSlabs,
  }

  // ── Index geometry ─────────────────────────────────────────────────────────

  // ss-linker bridge nucs live on the virtual `__lnk__{conn}` helix and on the
  // single-strand bridge `__lnk__{conn}__s`. The ss linker is drawn by
  // overhang_link_arcs.js as a Bezier bead/slab chain following the curved
  // arc between the two anchors — rendering the bridge nucs here as a regular
  // strand puts a straight chain of cones + beads + slabs along the virtual
  // helix axis (a chord between the anchors), which clashes with the curved
  // arc. ds-linker bridges (`__lnk__{conn}__a` / `__b`) are explicitly drawn
  // by helix_renderer as the dsDNA bridge segment, so they're NOT filtered.
  const _isSsLinkerBridgeNuc = (nuc) =>
    typeof nuc.strand_id === 'string'
    && nuc.strand_id.startsWith('__lnk__')
    && nuc.strand_id.endsWith('__s')
    && typeof nuc.helix_id === 'string'
    && nuc.helix_id.startsWith('__lnk__')

  // Beads marked as a flexible ssDNA segment are excluded from the rigid bead
  // meshes (they don't follow their helix's cluster); overhang_link_arcs.js
  // draws them on a fixed-length arc between the live cluster anchors instead.
  const _isFlexibleSegmentNuc = (nuc) => nuc.is_flexible_segment === true

  const byStrand = new Map()
  const byBp     = new Map()

  for (const nuc of geometry) {
    if (_isSsLinkerBridgeNuc(nuc) || _isFlexibleSegmentNuc(nuc)) continue
    if (nuc.strand_id) {
      if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
      byStrand.get(nuc.strand_id).push(nuc)
    }

    if (!byBp.has(nuc.bp_index)) byBp.set(nuc.bp_index, {})
    byBp.get(nuc.bp_index)[nuc.direction] = nuc
  }

  for (const [, nucs] of byStrand) orderStrandNucleotides(nucs)

  // ── Periodic-seam connectors ───────────────────────────────────────────────
  // A forced ligation with is_periodic_seam merges a far 3' end into a near 5'
  // end, so the merged strand has those two termini as CONSECUTIVE nucleotides —
  // on the SAME helix but ~a-whole-part apart. That renders as one giant
  // full-radius cone spanning the structure (getCrossHelixConnections skips it
  // since it isn't cross-helix). We treat such a pair AS cross-helix so the fat
  // cone is suppressed (radius 0 at every site that keys off isCrossHelix) and
  // the connector flows into the arc pipeline tagged isPeriodicSeam, where the
  // View-menu toggle hides it by default. Empty map ⇒ zero behaviour change for
  // designs without periodic seams.
  const _periodicSeamSiteToFl = new Map()
  for (const fl of (design?.forced_ligations ?? [])) {
    if (!fl.is_periodic_seam) continue
    _periodicSeamSiteToFl.set(`${fl.three_prime_helix_id}:${fl.three_prime_bp}:${fl.three_prime_direction}`, fl.id)
    _periodicSeamSiteToFl.set(`${fl.five_prime_helix_id}:${fl.five_prime_bp}:${fl.five_prime_direction}`, fl.id)
  }
  const _isPeriodicSeamPair = (a, b) => {
    if (!_periodicSeamSiteToFl.size) return false
    const ia = _periodicSeamSiteToFl.get(`${a.helix_id}:${a.bp_index}:${a.direction}`)
    const ib = _periodicSeamSiteToFl.get(`${b.helix_id}:${b.bp_index}:${b.direction}`)
    return ia != null && ia === ib
  }

  // ── Root group ─────────────────────────────────────────────────────────────

  const root = new THREE.Group()
  scene.add(root)

  // ── Helix axis sticks ──────────────────────────────────────────────────────
  // Each scaffold domain (or fallback domain) on a helix becomes one world-space
  // cylinder mesh. This lets cluster transforms with domain_ids move only the
  // segments that belong to the cluster, while leaving other segments in place.
  // Curved (deformed) helices keep a single TubeGeometry + a straight-cylinder
  // placeholder used by the deform-lerp transition.

  const AXIS_SHAFT_R  = 0.05   // shaft radius (nm)
  const _AY = new THREE.Vector3(0, 1, 0)

  const axisArrows = []   // each: see push() below
  let _axisArrowsVisible = true  // set false by cadnano mode; respected by setDetailLevel
  // Cached value of the last `setAxisShaftMode()` call. Used by
  // setAxisArrowsVisible(true) so cadnano exit restores the correct
  // mutually-exclusive shaft visibility rather than turning every shaft on
  // (which would render both the deformed curve and the straight chord
  // simultaneously for single-segment curved helices). Matches the deform
  // store default `deformVisuActive: true`.
  let _currentShaftMode = 'deformed'

  // Axis lines belong to the full/beads representation. These gate ALL axis-mesh
  // visibility (here AND in applyDeformLerp/_lerpPerSegment, which set .visible
  // directly during the deform lerp) so axis lines only show where the helix
  // renders as beads — hidden for cylinder/surface/atomistic columns (and globally
  // in cylinder LOD). Called every lerp frame → keep it to a couple of lookups.
  const _axisColRep = (helixId, bp) =>
    _repColumnRep.get(`${helixId}:${bp}`) ?? (_detailLevel === 2 ? 'cylinders' : 'full')
  const _axisSegOn = (helixId, lo, hi) =>
    _axisColRep(helixId, lo) === 'full' && _axisColRep(helixId, hi) === 'full'

  // Apply mode-based visibility to every axis arrow.  Extracted so
  // setAxisShaftMode and setAxisArrowsVisible(true) share one implementation
  // and stay consistent — never set `arrow.shaft.visible = true` directly,
  // always route through here so mutual exclusion is preserved.
  function _applyShaftModeVisibility(mode) {
    const segsVisible = (mode !== 'hidden')
    const _segAxisOn = _axisSegOn
    for (const arrow of axisArrows) {
      if (arrow.useSegments) {
        // Curved multi-segment helices carry both a straight cylinder (drives
        // the lerp animation; correct shape at t=0) and a curved tube (true
        // bent center-line; shown at deformed steady state). They swap as a
        // mutually-exclusive pair just like the single-shaft case below.
        for (const seg of arrow.segments ?? []) {
          const on = _segAxisOn(arrow.helixId, seg.bp_lo, seg.bp_hi)
          if (seg.tubeMesh) {
            seg.mesh.visible      = on && (mode === 'straight')
            seg.tubeMesh.visible  = on && (mode === 'deformed')
          } else if (seg.mesh) {
            seg.mesh.visible = on && segsVisible
          }
        }
      } else if (arrow.isCurved) {
        const on = _segAxisOn(arrow.helixId, arrow.bp_lo ?? 0, arrow.bp_hi ?? 0)
        if (arrow.shaft)         arrow.shaft.visible         = on && (mode === 'deformed')
        if (arrow.straightShaft) arrow.straightShaft.visible = on && (mode === 'straight')
      }
    }
  }

  // Returns per-domain axis segments for a helix, sorted ascending by bp_lo.
  // Each segment carries its owning strand+domain identity for cluster filtering.
  // Prefers scaffold strand domains; falls back to all strand domains (for stub
  // helices); falls back further to a single full-helix segment with no identity.
  function _axisDomainSegments(helix) {
    const cands = []
    for (const strand of design.strands ?? []) {
      if (strand.strand_type !== 'scaffold') continue
      for (let di = 0; di < (strand.domains ?? []).length; di++) {
        const dom = strand.domains[di]
        if (dom.helix_id !== helix.id) continue
        cands.push({ strand, di, dom })
      }
    }
    if (!cands.length) {
      for (const strand of design.strands ?? []) {
        for (let di = 0; di < (strand.domains ?? []).length; di++) {
          const dom = strand.domains[di]
          if (dom.helix_id !== helix.id) continue
          cands.push({ strand, di, dom })
        }
      }
    }
    if (!cands.length) {
      return [{
        strandId:    null,
        domainIndex: -1,
        ovhgId:      null,
        bp_lo:       helix.bp_start,
        bp_hi:       helix.bp_start + helix.length_bp - 1,
      }]
    }
    cands.sort((a, b) => Math.min(a.dom.start_bp, a.dom.end_bp) - Math.min(b.dom.start_bp, b.dom.end_bp))
    const seen = new Set()
    const out = []
    for (const { strand, di, dom } of cands) {
      const lo = Math.min(dom.start_bp, dom.end_bp)
      const hi = Math.max(dom.start_bp, dom.end_bp)
      const key = `${lo}:${hi}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        strandId:    strand.id,
        domainIndex: di,
        ovhgId:      dom.overhang_id ?? null,
        bp_lo:       lo,
        bp_hi:       hi,
      })
    }
    return out
  }

  for (const helix of design.helices) {
    // Skip linker virtual helices (`__lnk__<conn>`). Their bridge half is
    // rendered by overhang_link_arcs as a synthesized duplex / bead-string,
    // not as a regular helix axis stick — drawing one here produces stray
    // black lines floating between the two clusters at the linker midpoint.
    if (helix.id?.startsWith('__lnk__')) continue
    const axDef     = helixAxes?.[helix.id]
    const tubeSamp  = axDef?.samples
    const isCurved  = tubeSamp != null && tubeSamp.length > 2

    // Fallback: if no per-helix axes were supplied, use the topology axes
    // stored on the Helix model. These are the "straight" axes — equal to
    // straightHelixAxes since the backend strips cluster_transforms when
    // computing straight geometry. So at t=0 (deformed view off) this is
    // correct; at t=1 (deformed view on) the lerp will move arrows to the
    // deformed positions on the next reapplyLerp.
    //
    // This branch should not fire in normal flow: every API response that
    // updates currentGeometry also updates currentHelixAxes. If we see the
    // warning, currentHelixAxes was null or missing a specific helix at
    // render time — a state-sync regression worth investigating.
    if (helixAxes != null && axDef == null) {
      console.warn(`[helix_renderer] no axis entry for helix ${helix.id}; ` +
                   `falling back to topology axes (helix.axis_start/end). ` +
                   `currentHelixAxes is missing this helix.`)
    }
    const aStart = axDef
      ? new THREE.Vector3(...axDef.start)
      : new THREE.Vector3(helix.axis_start.x, helix.axis_start.y, helix.axis_start.z)
    const aEnd   = axDef
      ? new THREE.Vector3(...axDef.end)
      : new THREE.Vector3(helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z)

    let shaft         = null   // TubeGeometry mesh (curved helices only)
    let straightShaft = null   // unit cylinder placeholder, only for curved helices' deform lerp
    const segments    = []     // per-domain world-space cylinder meshes (straight helices)

    // Helices with multiple axis segments (bp-range gaps between strand domains
    // on the same helix — e.g. compliant joints) need per-segment axis lines
    // so the gap regions stay empty. The single TubeGeometry shaft built from
    // a continuous CatmullRomCurve3 ignores domain boundaries; it would draw
    // a line straight through the gap. For these helices we build the same
    // per-segment cylinder array used by non-curved helices below and skip
    // the single shaft entirely.
    const useSegments = !isCurved || (axDef?.segments?.length ?? 0) > 1
    if (isCurved && !useSegments) {
      const pts   = tubeSamp.map(s => new THREE.Vector3(...s))
      const curve = new THREE.CatmullRomCurve3(pts)
      const segs  = Math.max(tubeSamp.length * 4, 16)
      const geo   = new THREE.TubeGeometry(curve, segs, AXIS_SHAFT_R, 6, false)
      shaft = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({ color: C.axis }))
      shaft.name = 'axisLine'
      // Shaft + straightShaft opacities are the curved/straight cross-fade
      // driven by deform_view's lerp. _traverseSetOpacity (deform tool dim/
      // restore + ghost preview) must NOT clobber them, otherwise the
      // cross-fade snaps until the next reapplyLerp call.
      shaft.material.userData.skipOpacityRestore = true
      root.add(shaft)

      straightShaft = new THREE.Mesh(
        new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, 1, 8),
        new THREE.MeshPhongMaterial({ color: C.axis }),
      )
      straightShaft.name = 'axisLine'
      // Hidden by default — the curved shaft starts visible (deformVisuActive
      // is true by default). deform_view.setAxisShaftMode() flips these two
      // meshes as a mutually-exclusive pair on every toggle.
      straightShaft.visible = false
      straightShaft.userData.skipBounds = true
      straightShaft.material.userData.skipOpacityRestore = true
      root.add(straightShaft)
    }
    if (useSegments) {
      // Straight helix: one world-space cylinder per scaffold domain (no merging).
      // Backend supplies pre-transformed per-segment endpoints when present
      // (axDef.segments); otherwise compute from the helix's straight axis. The
      // backend path covers cluster transforms and partial-coverage clusters
      // correctly; the local fallback only applies to designs without a backend
      // axes payload.
      //
      // Curved + multi-segment: also build a TubeGeometry per segment that
      // follows the bent helix center-line within the segment's bp range
      // (sub-sampled from tubeSamp). Visible at the deformed steady state
      // (mode='deformed'); the straight cylinder takes over during the lerp
      // and when un-deformed (mode='straight'). Mirrors the single-shaft
      // cross-fade so multi-domain bent helices don't show straight chords.
      const aVec = aEnd.clone().sub(aStart)
      const aLen = aVec.length()
      const aDir = aLen > 0.001 ? aVec.clone().normalize() : _AY.clone()

      const backendSegs = axDef?.segments
      const domSegs = backendSegs?.length ? null : _axisDomainSegments(helix)
      const segCount = backendSegs?.length ?? domSegs.length
      for (let i = 0; i < segCount; i++) {
        const bs = backendSegs?.[i]
        const ds = bs ?? domSegs[i]
        const ovhgEntry = ds.ovhgId && axDef?.ovhgAxes ? axDef.ovhgAxes[ds.ovhgId] : null
        let ws, we
        if (bs && bs.start && bs.end) {
          ws = new THREE.Vector3(...bs.start)
          we = new THREE.Vector3(...bs.end)
        } else if (ovhgEntry) {
          ws = new THREE.Vector3(...ovhgEntry.start)
          we = new THREE.Vector3(...ovhgEntry.end)
        } else {
          const tStart = (ds.bp_lo - helix.bp_start) * BDNA_RISE_PER_BP
          const tEnd   = (ds.bp_hi - helix.bp_start + 1) * BDNA_RISE_PER_BP
          ws = aStart.clone().addScaledVector(aDir, tStart)
          we = aStart.clone().addScaledVector(aDir, tEnd)
        }
        const wsDir = we.clone().sub(ws)
        const wsLen = wsDir.length()
        const adjLen = Math.max(0.01, wsLen)
        const wsUnit = wsLen > 0.001 ? wsDir.clone().normalize() : aDir.clone()
        const mesh = new THREE.Mesh(
          new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, adjLen, 8),
          new THREE.MeshPhongMaterial({ color: C.axis }),
        )
        mesh.name = 'axisLine'
        mesh.position.copy(ws.clone().addScaledVector(wsUnit, adjLen * 0.5))
        mesh.quaternion.setFromUnitVectors(_AY, wsUnit)
        root.add(mesh)

        // Curved tube companion for bent helices. tubeSamp is the helix-wide
        // post-cluster-transformed center-line; we pluck the interior samples
        // whose local bp index falls strictly inside (bp_lo, bp_hi] and anchor
        // the curve at the segment's own ws/we (which may carry a per-segment
        // cluster transform). For helices with diverging per-segment transforms
        // the interior samples may not match the endpoint frame exactly — the
        // tube still looks far closer to the truth than a straight chord.
        let tubeMesh = null
        if (isCurved && tubeSamp && tubeSamp.length > 2) {
          const localLo = ds.bp_lo - helix.bp_start
          const localHi = ds.bp_hi - helix.bp_start
          const pts = [ws.clone()]
          const lastSampleIdx = tubeSamp.length - 1
          for (let si = 0; si < tubeSamp.length; si++) {
            // Mirror backend _sample_bp_list_for_axis: samples are at local bp
            // 0, AXIS_SAMPLE_STEP, 2*step, …, with length_bp-1 appended last.
            const localBp = (si === lastSampleIdx)
              ? helix.length_bp - 1
              : si * AXIS_SAMPLE_STEP
            if (localBp > localLo && localBp <= localHi) {
              pts.push(new THREE.Vector3(...tubeSamp[si]))
            }
          }
          pts.push(we.clone())
          // Skip tube construction when the segment spans no interior samples
          // (pts is just [ws, we] → would render as a straight line, no win
          // over the cylinder companion we already built).
          if (pts.length >= 3) {
            const curve = new THREE.CatmullRomCurve3(pts)
            const tubeSegs = Math.max(pts.length * 4, 16)
            const tubeGeo = new THREE.TubeGeometry(curve, tubeSegs, AXIS_SHAFT_R, 6, false)
            tubeMesh = new THREE.Mesh(tubeGeo, new THREE.MeshPhongMaterial({ color: C.axis }))
            tubeMesh.name = 'axisLine'
            tubeMesh.material.userData.skipOpacityRestore = true
            tubeMesh.visible = false  // setAxisShaftMode swaps it in at deformed steady state
            root.add(tubeMesh)
          }
        }

        // Normalise key names since backend uses snake_case while our local
        // helper emits camelCase.
        segments.push({
          mesh,
          tubeMesh,
          strandId:    bs ? bs.strand_id    : ds.strandId,
          domainIndex: bs ? bs.domain_index : ds.domainIndex,
          ovhgId:      bs ? bs.ovhg_id      : ds.ovhgId,
          bp_lo:       ds.bp_lo,
          bp_hi:       ds.bp_hi,
          adjLen,
          wsStart:     ws.clone(),
          wsEnd:       we.clone(),
        })
      }
    }

    axisArrows.push({
      helixId: helix.id,
      bp_lo:   helix.bp_start,
      bp_hi:   helix.bp_start + helix.length_bp - 1,
      isCurved,
      // True when this helix renders its axis via per-segment cylinders
      // rather than a single shaft. Set for every non-curved helix and for
      // curved helices with bp-range gaps between segments (so the gap
      // stays empty). When true: shaft + straightShaft are null and
      // segments[] is populated; downstream code paths (visibility, lerp,
      // revert) dispatch on this flag.
      useSegments,
      shaft,                              // tube mesh for single-segment curved helices, null otherwise
      straightShaft,                      // straight-cylinder placeholder for single-segment curved deform lerp
      segments,                           // per-domain world-space meshes (non-curved + multi-segment curved)
      aStart: aStart.clone(),
      aEnd:   aEnd.clone(),
      samples: isCurved ? tubeSamp : null,
      bpStart: helix.bp_start,
      bpLen:   helix.length_bp,
    })
  }

  // Per-segment lerp helper for multi-segment curved helices (e.g. compliant
  // joints). For each segment we have:
  //   wsStart/wsEnd     — stored deformed endpoints (from currentHelixAxes
  //                        segments at build time)
  //   straightSegs[i]   — straight endpoints passed in at lerp time (from
  //                        straightAxesMap.get(helixId).segments)
  // Position is the lerped midpoint; quaternion follows the lerped chord
  // direction; mesh length is fixed at adjLen (rigid transforms preserve
  // chord length, so the residual variation during the lerp is negligible
  // and the visible artifact is much smaller than the gap-filling alternative).
  function _lerpPerSegment(arrow, straightSegs, t) {
    if (!arrow.segments?.length) return
    for (let i = 0; i < arrow.segments.length; i++) {
      const seg = arrow.segments[i]
      const ss  = straightSegs?.[i]
      let sx0, sy0, sz0, sx1, sy1, sz1
      if (ss) {
        sx0 = ss.start[0] + (seg.wsStart.x - ss.start[0]) * t
        sy0 = ss.start[1] + (seg.wsStart.y - ss.start[1]) * t
        sz0 = ss.start[2] + (seg.wsStart.z - ss.start[2]) * t
        sx1 = ss.end[0]   + (seg.wsEnd.x   - ss.end[0])   * t
        sy1 = ss.end[1]   + (seg.wsEnd.y   - ss.end[1])   * t
        sz1 = ss.end[2]   + (seg.wsEnd.z   - ss.end[2])   * t
      } else {
        sx0 = seg.wsStart.x; sy0 = seg.wsStart.y; sz0 = seg.wsStart.z
        sx1 = seg.wsEnd.x;   sy1 = seg.wsEnd.y;   sz1 = seg.wsEnd.z
      }
      const dx = sx1 - sx0, dy = sy1 - sy0, dz = sz1 - sz0
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (len < 0.001) continue
      _segDir.set(dx / len, dy / len, dz / len)
      seg.mesh.position.set((sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, (sz0 + sz1) * 0.5)
      seg.mesh.quaternion.setFromUnitVectors(_AY, _segDir)
    }
  }

  // Reposition every per-domain segment of a straight helix along the axis line
  // (baseStart → baseEnd). Used by revertToGeometry, applyUnfoldOffsets, and
  // applyDeformLerp; all three need to keep segments aligned to a recomputed axis.
  // Mesh geometry length is fixed at build time, so this only translates+rotates;
  // bp ranges are static so segLen ≈ build-time length under any rigid axis change.
  const _segDir = new THREE.Vector3()
  const _segQ   = new THREE.Quaternion()
  function _layStraightSegments(arrow, baseStart, baseEnd) {
    if (arrow.isCurved || !arrow.segments?.length) return
    _segDir.set(baseEnd.x - baseStart.x, baseEnd.y - baseStart.y, baseEnd.z - baseStart.z)
    const dlen = _segDir.length()
    if (dlen < 0.001) return
    _segDir.divideScalar(dlen)
    _segQ.setFromUnitVectors(_AY, _segDir)
    for (const seg of arrow.segments) {
      const tS = (seg.bp_lo - arrow.bpStart) * BDNA_RISE_PER_BP
      const tE = (seg.bp_hi - arrow.bpStart + 1) * BDNA_RISE_PER_BP
      const wsX = baseStart.x + _segDir.x * tS
      const wsY = baseStart.y + _segDir.y * tS
      const wsZ = baseStart.z + _segDir.z * tS
      const weX = baseStart.x + _segDir.x * tE
      const weY = baseStart.y + _segDir.y * tE
      const weZ = baseStart.z + _segDir.z * tE
      seg.wsStart.set(wsX, wsY, wsZ)
      seg.wsEnd.set(weX, weY, weZ)
      seg.mesh.position.set(
        (wsX + weX) * 0.5,
        (wsY + weY) * 0.5,
        (wsZ + weZ) * 0.5,
      )
      seg.mesh.quaternion.copy(_segQ)
    }
  }

  // ── Staple colour map ──────────────────────────────────────────────────────

  const stapleColorMap = buildStapleColorMap(geometry, design)

  // ── Backbone beads (InstancedMesh) ────────────────────────────────────────

  // Exclude fluorophore beads from the regular bead meshes — they go in iFluoros.
  // Also exclude ss-linker bridge nucs (see _isSsLinkerBridgeNuc above) so their
  // chord-aligned bead/cone/slab chain doesn't compete with the curved arc that
  // overhang_link_arcs.js renders for ss linkers.
  const assignedGeometry = geometry.filter(n => n.strand_id && !n.is_modification && !_isSsLinkerBridgeNuc(n) && !_isFlexibleSegmentNuc(n))
  const fluoroGeometry   = geometry.filter(n => n.is_modification)
  const sphereNucs  = assignedGeometry.filter(n => !n.is_five_prime)
  const cubeNucs    = assignedGeometry.filter(n =>  n.is_five_prime)

  // At cheap LOD we allocate dummy count=1 meshes so downstream code that
  // references `iSpheres` / `iCubes` continues to type-check; we just don't
  // populate them per-bp, and we hide them. backboneEntries stays empty so
  // color/lerp loops are no-ops.
  // Phantom-instance guard (see big comment near _domainCylCount setup below).
  // Capacity stays Math.max(1, …) for Three.js; we set `.count` to the real
  // count so zero-instance meshes render nothing.
  const _sphereCount = _skipBeads ? 1 : Math.max(1, sphereNucs.length)
  const _cubeCount   = _skipBeads ? 1 : Math.max(1, cubeNucs.length)
  // Sphere impostors (flag-gated): backbone beads become 2-tri camera-facing
  // quads that ray-paint a lit sphere — ~70x fewer triangles at full rep. The
  // center still rides the instance matrix, so setMatrixAt-based moves (mrDNA
  // relax / deform / unfold / fade) and setColorAt are unchanged. 5' cubes stay real
  // geometry (oriented markers, not spheres). See project_sphere_impostors.md.
  const _useImpostors = impostorsEnabled()
  const iSpheres = new THREE.InstancedMesh(
    _useImpostors ? IMPOSTOR_QUAD : GEO_SPHERE,
    _useImpostors ? makeImpostorPhongMaterial({ radius: BEAD_RADIUS })
                  : new THREE.MeshPhongMaterial({ color: 0xffffff }),
    _sphereCount)
  if (_useImpostors) installSphereImpostorRaycast(iSpheres, BEAD_RADIUS)
  const iCubes   = new THREE.InstancedMesh(
    GEO_CUBE_5P, new THREE.MeshPhongMaterial({ color: 0xffffff }), _cubeCount)
  iSpheres.count = _skipBeads ? 0 : sphereNucs.length
  iCubes.count   = _skipBeads ? 0 : cubeNucs.length
  iSpheres.frustumCulled = false
  iCubes.frustumCulled   = false
  iSpheres.name = 'backboneSpheres'
  iCubes.name   = 'backboneCubes'
  if (_skipBeads) { iSpheres.visible = false; iCubes.visible = false }
  root.add(iSpheres)
  root.add(iCubes)

  const backboneEntries = []
  let sphereId = 0, cubeId = 0

  if (!_skipBeads) {
    for (const nuc of assignedGeometry) {
      const color = nucColor(nuc, stapleColorMap, customColors, loopSet)
      const pos   = new THREE.Vector3(...nuc.backbone_position)
      _tMatrix.compose(pos, ID_QUAT, _tScale.set(1, 1, 1))

      if (nuc.is_five_prime) {
        iCubes.setMatrixAt(cubeId, _tMatrix)
        iCubes.setColorAt(cubeId, _tColor.setHex(color))
        backboneEntries.push({ instMesh: iCubes, id: cubeId, nuc, pos, defaultColor: color })
        cubeId++
      } else {
        iSpheres.setMatrixAt(sphereId, _tMatrix)
        iSpheres.setColorAt(sphereId, _tColor.setHex(color))
        backboneEntries.push({ instMesh: iSpheres, id: sphereId, nuc, pos, defaultColor: color })
        sphereId++
      }
    }
    iSpheres.instanceMatrix.needsUpdate = true
    if (iSpheres.instanceColor) iSpheres.instanceColor.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true
    if (iCubes.instanceColor)   iCubes.instanceColor.needsUpdate   = true
  }

  // ── Fluorophore beads (InstancedMesh) — modification markers at extension tips ─

  const _fluoroCount = _skipFluoros ? 1 : Math.max(1, fluoroGeometry.length)
  const iFluoros = new THREE.InstancedMesh(
    _useImpostors ? IMPOSTOR_QUAD : GEO_FLUORO_SPHERE,
    _useImpostors ? makeImpostorPhongMaterial({ radius: 0.25 })  // matches GEO_FLUORO_SPHERE
                  : new THREE.MeshPhongMaterial({ color: 0xffffff }),
    _fluoroCount,
  )
  if (_useImpostors) installSphereImpostorRaycast(iFluoros, 0.25)
  iFluoros.count = _skipFluoros ? 0 : fluoroGeometry.length
  iFluoros.frustumCulled = false
  iFluoros.name = 'extensionFluorophores'
  if (_skipFluoros) iFluoros.visible = false
  root.add(iFluoros)

  const fluoroEntries = []
  let fluoroId = 0

  if (!_skipFluoros) {
    for (const nuc of fluoroGeometry) {
      const color = MODIFICATION_COLORS[nuc.modification] ?? 0xffffff
      const pos   = new THREE.Vector3(...nuc.backbone_position)
      _tMatrix.compose(pos, ID_QUAT, _tScale.set(1, 1, 1))
      iFluoros.setMatrixAt(fluoroId, _tMatrix)
      iFluoros.setColorAt(fluoroId, _tColor.setHex(color))
      fluoroEntries.push({ instMesh: iFluoros, id: fluoroId, nuc, pos, defaultColor: color })
      fluoroId++
    }
    iFluoros.instanceMatrix.needsUpdate = true
    if (iFluoros.instanceColor) iFluoros.instanceColor.needsUpdate = true
  }

  // ── Strand direction cones (InstancedMesh) ────────────────────────────────

  let totalCones = 0
  for (const [, nucs] of byStrand) totalCones += Math.max(0, nucs.length - 1)

  const _coneCount = _skipCones ? 1 : Math.max(1, totalCones)
  const iCones = new THREE.InstancedMesh(
    GEO_UNIT_CONE, new THREE.MeshPhongMaterial({ color: 0xffffff }), _coneCount)
  iCones.count = _skipCones ? 0 : totalCones
  iCones.frustumCulled = false
  iCones.name = 'strandCones'
  if (_skipCones) iCones.visible = false
  root.add(iCones)

  const coneEntries = []
  let coneId = 0

  if (!_skipCones) {
    for (const [, nucs] of byStrand) {
      const color = nucArrowColor(nucs[0], stapleColorMap, customColors, loopSet)
      for (let i = 0; i < nucs.length - 1; i++) {
        const from   = new THREE.Vector3(...nucs[i].backbone_position)
        const to     = new THREE.Vector3(...nucs[i + 1].backbone_position)
        const dir    = to.clone().sub(from)
        const dist   = dir.length()
        const coneHeight = Math.max(0.001, dist)
        const midPos = from.clone().addScaledVector(dir.clone().normalize(), dist / 2)
        const quat   = new THREE.Quaternion().setFromUnitVectors(Y_HAT, dir.clone().normalize())

        // Cross-helix connections — and periodic-seam far↔near connectors — are
        // rendered as arcs; hide the cone. (Treating the periodic seam as
        // cross-helix suppresses the giant cone via the existing radius logic.)
        const isPeriodicSeam = _isPeriodicSeamPair(nucs[i], nucs[i + 1])
        const isCrossHelix = (nucs[i].helix_id !== nucs[i + 1].helix_id) || isPeriodicSeam
        const r = isCrossHelix ? 0 : CONE_RADIUS
        _tMatrix.compose(midPos, quat, _tScale.set(r, coneHeight, r))
        iCones.setMatrixAt(coneId, _tMatrix)
        iCones.setColorAt(coneId, _tColor.setHex(color))

        coneEntries.push({
          instMesh: iCones, id: coneId,
          fromNuc: nucs[i], toNuc: nucs[i + 1],
          strandId: nucs[i].strand_id,
          midPos, quat, coneHeight,
          coneRadius: isCrossHelix ? 0 : CONE_RADIUS,
          isCrossHelix,
          isPeriodicSeam,
          defaultColor: color,
        })
        coneId++
      }
    }
    iCones.instanceMatrix.needsUpdate = true
    if (iCones.instanceColor) iCones.instanceColor.needsUpdate = true
  }

  // ── Base slabs (InstancedMesh) ────────────────────────────────────────────

  // Nominal slab dimensions (nm). NOTE the historical naming: `width` is the
  // PLATE THICKNESS — the smallest dimension, normal to the base-plate face —
  // while `thickness` is the long in-plane extent. The sidebar slider drives
  // `width` (see setSlabThickness). `slabParams` is the LIVE copy every slab
  // matrix-compose in this file reads, so the deform / MD / cluster paths that
  // compose slab matrices inline stay consistent with the user's chosen value.
  const SLAB_WIDTH_DEFAULT = 0.06
  const slabParams = { length: 0.30, width: SLAB_WIDTH_DEFAULT, thickness: 0.70, distance: 0.55 }

  const _slabCount = _skipSlabs ? 1 : Math.max(1, assignedGeometry.length)
  // OPAQUE. The slabs shipped at opacity 0.90 with a sidebar slider on top; the
  // slider was removed 2026-08-02 for colliding with the other opacity controls,
  // and the leftover 0.90 baseline kept them faintly see-through. Per-cluster /
  // reference fades still work — they ride the `instanceAlpha` attribute, and
  // `applyInstanceAlphaMaterial` flips `transparent` on when one is installed.
  const iSlabs = new THREE.InstancedMesh(
    GEO_UNIT_BOX,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    _slabCount,
  )
  // Slabs are STRUCTURE, not overlay: once a per-instance fade makes the material
  // transparent, photo mode must still treat them as solid shadow casters. See
  // photo_mode.js `swapToFlatMaterials` / shadow_bounds.js `isShadowExcluded`,
  // which otherwise read depthWrite:false as "cannot occlude" and drop the slabs
  // out of the shadow pass entirely.
  iSlabs.material.userData.photoForceDepthWrite = true
  iSlabs.count = _skipSlabs ? 0 : assignedGeometry.length
  iSlabs.frustumCulled = false
  iSlabs.name = 'baseSlabs'
  if (_skipSlabs) iSlabs.visible = false
  root.add(iSlabs)

  // One thin, instanced 8-sided rod per nucleotide: still one draw call for the
  // whole design, but unlike a one-pixel WebGL line it remains legible on HiDPI
  // displays and against both light and dark backgrounds.
  const iSlabConnectors = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    _slabCount,
  )
  iSlabConnectors.count = 0
  iSlabConnectors.name = 'slabBackboneConnectors'
  iSlabConnectors.frustumCulled = false
  iSlabConnectors.visible = !_skipSlabs
  root.add(iSlabConnectors)

  const slabEntries = []
  let _slabConnectorsReady = false
  let slabId = 0

  if (!_skipSlabs) {
    // Pair by helix/bp and occurrence index.  The occurrence index preserves loop
    // insert copies, where several nucleotides legitimately share the same labels.
    const slabPairGroups = new Map()
    const slabMate = new Map()
    for (const nuc of assignedGeometry) {
      if (nuc.helix_id.startsWith('__ext_')) continue
      const key = `${nuc.helix_id}:${nuc.bp_index}`
      let group = slabPairGroups.get(key)
      if (!group) slabPairGroups.set(key, group = { FORWARD: [], REVERSE: [] })
      group[nuc.direction]?.push(nuc)
    }
    for (const group of slabPairGroups.values()) {
      const count = Math.min(group.FORWARD.length, group.REVERSE.length)
      for (let i = 0; i < count; i++) {
        slabMate.set(group.FORWARD[i], group.REVERSE[i])
        slabMate.set(group.REVERSE[i], group.FORWARD[i])
      }
    }

    for (const nuc of assignedGeometry) {
      // Extension beads have no base-pair slabs.
      if (nuc.helix_id.startsWith('__ext_')) continue
      let bnDir  = new THREE.Vector3(...nuc.base_normal)
      let tanDir = new THREE.Vector3(...nuc.axis_tangent)
      const color  = nucSlabColor(nuc, stapleColorMap, customColors, loopSet)
      const bbPos  = new THREE.Vector3(...nuc.backbone_position)
      // The backend frame supplies base position, normal, and axis tangent. The display
      // solver adds only the shared-plane and O5'-bead contact adjustment documented above.
      let quat   = slabQuaternion(bnDir, tanDir)
      const mate   = slabMate.get(nuc)
      const pose = independentPoses.get(
        `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}:${nuc.copy ?? 0}`)
      const independentPose = !!pose
      let center
      if (pose) {
        // Geometry already carries the saved nucleotide delta. Reconstruct the slab
        // from the pre-pose residue + mate, then apply that SAME delta to the complete
        // slab. Re-solving contact from the posed bead changed the bead↔slab distance
        // after Apply (2hb_1xT: 0.35205 → 0.30000 nm).
        const delta = poseMatrix(pose)
        const inverse = delta.clone().invert()
        const originalBb = bbPos.clone().applyMatrix4(inverse)
        const originalBase = new THREE.Vector3(...nuc.base_position).applyMatrix4(inverse)
        const originalBn = bnDir.clone().transformDirection(inverse)
        const originalTan = tanDir.clone().transformDirection(inverse)
        if (pose.display_slab_offset && pose.display_slab_rotation) {
          center = originalBb.clone()
            .add(new THREE.Vector3(...pose.display_slab_offset))
            .applyMatrix4(delta)
          quat = new THREE.Quaternion(...pose.rotation)
            .multiply(new THREE.Quaternion(...pose.display_slab_rotation))
        } else {
        let originalMateBase = null
        if (mate?.base_position) {
          originalMateBase = new THREE.Vector3(...mate.base_position)
          const matePose = independentPoses.get(
            `${mate.helix_id}:${mate.bp_index}:${mate.direction}:${mate.copy ?? 0}`)
          if (matePose) originalMateBase.applyMatrix4(poseMatrix(matePose).invert())
        }
        center = pairedSlabCenter(
          originalBb, originalBase, originalMateBase, originalTan, originalBn,
        ).applyMatrix4(delta)
        quat = new THREE.Quaternion(...pose.rotation).multiply(slabQuaternion(originalBn, originalTan))
        }
      } else {
        center = pairedSlabCenter(
          bbPos,
          new THREE.Vector3(...nuc.base_position),
          mate?.base_position ? new THREE.Vector3(...mate.base_position) : null,
          tanDir,
          bnDir,
        )
      }

      _tMatrix.compose(center, quat,
        _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slabId, _tMatrix)
      iSlabs.setColorAt(slabId, _tColor.setHex(color))

      slabEntries.push({
        instMesh: iSlabs, id: slabId,
        connectorMesh: iSlabConnectors, connectorId: slabId,
        nuc, mate, independentPose, pose, quat, bnDir, bbPos, center, defaultColor: color,
      })
      slabId++
    }
    iSlabs.instanceMatrix.needsUpdate = true
    _refreshSlabConnectors()
    if (iSlabs.instanceColor) iSlabs.instanceColor.needsUpdate = true
  }
  iSlabConnectors.count = slabEntries.length

  /** Canonical paired slab center for build, animation, restore, and overrides. */
  function _slabCenterAt(
    slab, tangent, baseMap = null, beadMap = null, out = new THREE.Vector3(),
  ) {
    const n = slab.nuc
    const key = `${n.helix_id}:${n.bp_index}:${n.direction}`
    _slabBaseS.copy(baseMap?.get(key) ?? _tPos.set(...n.base_position))
    const liveEntry = _nucToEntry.get(n)
    _slabCenterL.copy(beadMap?.get(key) ?? liveEntry?.pos ?? _tPos.set(...n.backbone_position))
    if (slab.independentPose && slab.pose?.display_slab_offset) {
      return out.copy(_slabCenterL).add(
        _slabBaseS.set(...slab.pose.display_slab_offset)
          .applyQuaternion(new THREE.Quaternion(...slab.pose.rotation)),
      )
    }
    let mateBase = null
    if (!slab.independentPose && slab.mate?.base_position) {
      const mate = slab.mate
      const mateKey = `${mate.helix_id}:${mate.bp_index}:${mate.direction}`
      _slabMateBaseS.copy(baseMap?.get(mateKey) ?? _tPos.set(...mate.base_position))
      mateBase = _slabMateBaseS
    }
    return pairedSlabCenter(_slabCenterL, _slabBaseS, mateBase, tangent, slab.bnDir, out)
  }

  // ── Domain cylinders (LOD level 2 — one per domain, strand-colored) ─────────
  // One cylinder per non-overhang domain, positioned along the helix axis at
  // the domain's bp extent and colored by the owning strand.
  // Invisible by default; activated by setDetailLevel(2) when far out.
  //
  // Straight helices: InstancedMesh (iHelixCylinders / iOverhangCylinders)
  // Curved  helices:  TubeGeometry per-domain (iCurvedHelixCylinders proxy for
  //                   lerp + individual tube meshes in _curvedCylGroup).

  // Build arrow map once so counting can check isCurved.
  const _arrowByHelixId = new Map(axisArrows.map(a => [a.helixId, a]))
  const _directConnectedOverhangIds = directConnectedOverhangIds(design)

  // Count per-category.  Scaffold domains skipped to avoid z-fighting.
  //
  // Linker strands get special handling so their two pieces read correctly in
  // cylinder rep (see the build pass below):
  //   - binding (complement) domains — on a real overhang helix — become a
  //     half-cylinder opposite the overhang half (iLinkerBindingCylinders).
  //   - the ds bridge — on a virtual `__lnk__` helix — becomes ONE simple full
  //     cylinder per bridge helix (iLinkerBridgeCylinders), built from the
  //     emitted bridge nucs (the `__lnk__` helix has no axis arrow).
  // ss bridges are left to overhang_link_arcs.js (FJC bead chain), so only ds
  // bridge helices (`__a` / `__b` side strands) are counted here.
  let _domainCylCount        = 0
  let _curvedDomainCylCount  = 0
  let _overhangCylCount      = 0
  let _overhangFullCylCount  = 0
  let _curvedOvhgCylCount    = 0
  let _curvedOvhgFullCylCount = 0
  let _bindingCylCount       = 0
  const _dsBridgeHelixIds    = new Set()
  for (const strand of design.strands) {
    if (strand.strand_type === 'scaffold') continue
    const isLinker = strand.strand_type === 'linker'
    for (const dom of strand.domains) {
      const onBridge = dom.helix_id?.startsWith('__lnk__')
      if (isLinker && onBridge) {
        if (/__(a|b)$/.test(strand.id)) _dsBridgeHelixIds.add(dom.helix_id)
        continue   // bridge: ds → one cyl per helix (counted below); ss → no cyl
      }
      if (isLinker && !onBridge) { _bindingCylCount++; continue }   // binding half-cyl
      const arrowC = _arrowByHelixId.get(dom.helix_id)
      const curved = arrowC?.isCurved ?? false
      if (dom.overhang_id != null) {
        const directFull = _directConnectedOverhangIds.has(dom.overhang_id)
        if (curved) {
          if (directFull) _curvedOvhgFullCylCount++
          else _curvedOvhgCylCount++
        } else {
          if (directFull) _overhangFullCylCount++
          else _overhangCylCount++
        }
      } else {
        if (curved) _curvedDomainCylCount++; else _domainCylCount++
      }
    }
  }
  const _bridgeCylCount = _dsBridgeHelixIds.size

  // ── Phantom-instance guard ────────────────────────────────────────────────
  // Each of the four cylinder InstancedMeshes below uses `Math.max(1, count)`
  // for its CAPACITY because Three.js refuses size-0 InstancedMesh. But the
  // default Float32Array for an InstancedMesh's `instanceMatrix` is all
  // zeros — and a zero matrix produces NaN/degenerate vertex positions when
  // applied to geometry. With visibility flipped on in coarse-LOD ("cylinders"
  // rep, the assembly default for clones), that phantom instance renders as
  // a garbage-shape at world origin — looking like a mystery "part origin
  // gizmo" sitting where the part's local (0,0,0) lands in world space.
  //
  // Fix: set `mesh.count = realCount` immediately after construction. Three.js
  // honours `.count` for rendering regardless of capacity, so zero-count
  // meshes render nothing while capacity stays ≥ 1 to satisfy the InstancedMesh
  // constructor. setMatrixAt later raises `.count` as instances are populated.

  // Straight-helix instanced meshes (existing approach).
  const iHelixCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff }),
    Math.max(1, _domainCylCount),
  )
  iHelixCylinders.count = _domainCylCount
  iHelixCylinders.frustumCulled = false
  iHelixCylinders.visible = false
  iHelixCylinders.name = 'helixCylinders'
  root.add(iHelixCylinders)

  // Curved-helix straight-proxy instanced mesh — used only for lerp cross-fade.
  // Opacity 1 at t=0 (straight), 0 at t=1 (fully deformed, curved tubes take over).
  const iCurvedHelixCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    // depthWrite:false at opacity 0 so the faded-out proxy is not an invisible
    // occluder of the bent tubes behind it (see _fadeMat). The lerp re-enables it
    // when the proxy fades in (straight view).
    new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false }),
    Math.max(1, _curvedDomainCylCount),
  )
  iCurvedHelixCylinders.count = _curvedDomainCylCount
  iCurvedHelixCylinders.frustumCulled = false
  iCurvedHelixCylinders.visible = false
  iCurvedHelixCylinders.name = 'curvedHelixCylindersProxy'
  root.add(iCurvedHelixCylinders)

  // Group of per-domain TubeGeometry meshes for curved helices.
  const _curvedCylGroup = new THREE.Group()
  _curvedCylGroup.name = 'curvedCylGroup'
  _curvedCylGroup.visible = false
  root.add(_curvedCylGroup)

  // Half-cylinder mesh for single-stranded overhang domains (amber, DoubleSide so
  // the inside of the curved surface is visible when viewed at oblique angles).
  const iOverhangCylinders = new THREE.InstancedMesh(
    GEO_HALF_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide }),
    Math.max(1, _overhangCylCount),
  )
  iOverhangCylinders.count = _overhangCylCount
  iOverhangCylinders.frustumCulled = false
  iOverhangCylinders.visible = false
  iOverhangCylinders.name = 'overhangCylinders'
  root.add(iOverhangCylinders)

  // Full-cylinder mesh for overhang domains that are part of a direct
  // connection. These are duplexed, but do not have a linker complement mesh to
  // fill the other half, so rendering them as half-cylinders makes them look ss.
  const iOverhangFullCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff }),
    Math.max(1, _overhangFullCylCount),
  )
  iOverhangFullCylinders.count = _overhangFullCylCount
  iOverhangFullCylinders.frustumCulled = false
  iOverhangFullCylinders.visible = false
  iOverhangFullCylinders.name = 'overhangFullCylinders'
  root.add(iOverhangFullCylinders)

  // ── Per-domain cylinder selection glow (additive outline) ──────────────────
  // A halo InstancedMesh that mirrors selected domains' solid-cylinder poses,
  // inflated slightly so it rims the solid additively. Driven by the selection
  // drill (see glowCylinderDomains); tracks the live solid matrices via
  // _refreshCylGlow at every cylinder-matrix recompute (deform / radius).
  const GLOW_CYL_FACTOR = 1.28
  const _cylGlowMat = new THREE.MeshBasicMaterial({
    color: 0x3fb950, transparent: true, opacity: 0.45,
    blending: THREE.AdditiveBlending, depthWrite: false,
  })
  const iHelixCylGlow = new THREE.InstancedMesh(GEO_UNIT_CYL, _cylGlowMat, Math.max(1, _domainCylCount))
  iHelixCylGlow.count = 0
  iHelixCylGlow.frustumCulled = false
  iHelixCylGlow.renderOrder = 1
  iHelixCylGlow.name = 'helixCylGlow'
  root.add(iHelixCylGlow)
  const iOverhangCylGlow = new THREE.InstancedMesh(GEO_HALF_CYL, _cylGlowMat, Math.max(1, _overhangCylCount))
  iOverhangCylGlow.count = 0
  iOverhangCylGlow.frustumCulled = false
  iOverhangCylGlow.renderOrder = 1
  iOverhangCylGlow.name = 'overhangCylGlow'
  root.add(iOverhangCylGlow)
  const iOverhangFullCylGlow = new THREE.InstancedMesh(GEO_UNIT_CYL, _cylGlowMat, Math.max(1, _overhangFullCylCount))
  iOverhangFullCylGlow.count = 0
  iOverhangFullCylGlow.frustumCulled = false
  iOverhangFullCylGlow.renderOrder = 1
  iOverhangFullCylGlow.name = 'overhangFullCylGlow'
  root.add(iOverhangFullCylGlow)
  let _cylGlowRefs = []   // [{strandId, domainIndex}] currently glowing

  // Resolve domain refs → sets of cylIdx for the straight + overhang cyl meshes.
  function _refsToCylIdxSets(domainRefs) {
    const want = new Set((domainRefs ?? []).map(r => `${r.strandId}:${r.domainIndex}`))
    const straight = new Set(), overhang = new Set(), overhangFull = new Set()
    for (const d of _domainCylData)   if (want.has(`${d.strandId}:${d.domainIndex}`)) straight.add(d.cylIdx)
    for (const d of _overhangCylData) if (want.has(`${d.strandId}:${d.domainIndex}`)) {
      if (d.fullCylinder) overhangFull.add(d.cylIdx)
      else overhang.add(d.cylIdx)
    }
    return { straight, overhang, overhangFull }
  }
  // Re-pose glow instances from the live solid-cylinder matrices, inflated.
  function _writeCylGlow(glowMesh, srcMesh, domEntries, cylIdxSet) {
    let n = 0
    for (const dom of domEntries) {
      if (!cylIdxSet.has(dom.cylIdx)) continue
      srcMesh.getMatrixAt(dom.cylIdx, _tMatrix)
      _tMatrix.decompose(_tPos, _cylQ, _tScale)
      _tScale.x *= GLOW_CYL_FACTOR; _tScale.z *= GLOW_CYL_FACTOR
      _tMatrix.compose(_tPos, _cylQ, _tScale)
      glowMesh.setMatrixAt(n++, _tMatrix)
    }
    glowMesh.count = n
    glowMesh.instanceMatrix.needsUpdate = true
  }
  function _refreshCylGlow() {
    if (!_cylGlowRefs.length) return
    const { straight, overhang, overhangFull } = _refsToCylIdxSets(_cylGlowRefs)
    _writeCylGlow(iHelixCylGlow, iHelixCylinders, _domainCylData, straight)
    _writeCylGlow(iOverhangCylGlow, iOverhangCylinders, _overhangCylData.filter(d => !d.fullCylinder), overhang)
    _writeCylGlow(iOverhangFullCylGlow, iOverhangFullCylinders, _overhangCylData.filter(d => d.fullCylinder), overhangFull)
  }
  // Is this domain FULLY cylinder-rendered right now? (every column → 'cylinders')
  function _isDomainCyl(strandId, domainIndex) {
    const dom = _domainCylData.find(d => d.strandId === strandId && d.domainIndex === domainIndex)
             ?? _overhangCylData.find(d => d.strandId === strandId && d.domainIndex === domainIndex)
    if (!dom) return false
    const baseCyl = _detailLevel === 2
    for (let bp = dom.bp_lo; bp <= dom.bp_hi; bp++) {
      if ((_repColumnRep.get(`${dom.helixId}:${bp}`) ?? (baseCyl ? 'cylinders' : 'full')) !== 'cylinders') return false
    }
    return true
  }

  // Curved-helix straight-proxy for overhang half-cylinders.
  const iCurvedOverhangCylinders = new THREE.InstancedMesh(
    GEO_HALF_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0, depthWrite: false }),
    Math.max(1, _curvedOvhgCylCount),
  )
  iCurvedOverhangCylinders.count = _curvedOvhgCylCount
  iCurvedOverhangCylinders.frustumCulled = false
  iCurvedOverhangCylinders.visible = false
  iCurvedOverhangCylinders.name = 'curvedOverhangCylindersProxy'
  root.add(iCurvedOverhangCylinders)

  const iCurvedOverhangFullCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false }),
    Math.max(1, _curvedOvhgFullCylCount),
  )
  iCurvedOverhangFullCylinders.count = _curvedOvhgFullCylCount
  iCurvedOverhangFullCylinders.frustumCulled = false
  iCurvedOverhangFullCylinders.visible = false
  iCurvedOverhangFullCylinders.name = 'curvedOverhangFullCylindersProxy'
  root.add(iCurvedOverhangFullCylinders)

  // Group of per-domain curved half-tube meshes for overhang domains on curved helices.
  const _curvedOvhgGroup = new THREE.Group()
  _curvedOvhgGroup.name = 'curvedOvhgGroup'
  _curvedOvhgGroup.visible = false
  root.add(_curvedOvhgGroup)

  // Linker binding (complement) half-cylinders — the half opposite the overhang
  // half, in the linker strand's colour, so the duplexed overhang reads as one
  // two-toned full cylinder.  Built once in the deferred pass below; not woven
  // into the per-frame recompute passes (they track a full rebuild instead).
  const iLinkerBindingCylinders = new THREE.InstancedMesh(
    GEO_HALF_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide }),
    Math.max(1, _bindingCylCount),
  )
  iLinkerBindingCylinders.count = _bindingCylCount
  iLinkerBindingCylinders.frustumCulled = false
  iLinkerBindingCylinders.visible = false
  iLinkerBindingCylinders.name = 'linkerBindingCylinders'
  root.add(iLinkerBindingCylinders)

  // Linker ds bridge — one simple full cylinder per `__lnk__` bridge helix,
  // spanning the emitted bridge nucs' axis (the `__lnk__` helix is skipped in
  // the axis-arrow loop, so it never gets a normal domain cylinder).
  const iLinkerBridgeCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff }),
    Math.max(1, _bridgeCylCount),
  )
  iLinkerBridgeCylinders.count = _bridgeCylCount
  iLinkerBridgeCylinders.frustumCulled = false
  iLinkerBridgeCylinders.visible = false
  iLinkerBridgeCylinders.name = 'linkerBridgeCylinders'
  root.add(iLinkerBridgeCylinders)

  // Per-domain metadata used by applyUnfoldOffsets / revertToGeometry / setStrandColor.
  // _domainCylData: straight-helix domains.  _curvedDomainCylData: curved-helix domains.
  // Each entry: { helixId, strandId, t0, t1, cylIdx, arrow, defaultColor [, mesh] }
  const _domainCylData        = []
  const _curvedDomainCylData  = []
  const _overhangCylData      = []
  const _curvedOvhgCylData    = []
  // Linker cylinder bookkeeping (populated in the cylinder build pass).
  const _deferredBindings     = []   // {helixId, strandId, domainIndex, lo, hi, color, arrow} — emitted opposite their overhang
  // Instance→domain map for iLinkerBindingCylinders. Did not exist until 2026-08-01,
  // which is why binding cylinders were the one cylinder family with no per-instance
  // alpha: nothing could say which domain an instance belonged to.
  const _bindingCylData       = []   // {helixId, strandId, domainIndex, bp_lo, bp_hi, cylIdx}
  const _ovhgBuildXform       = new Map()  // `${helixId}|${lo}|${hi}` → {pos, quat, lenY} of the overhang half
  const _bridgeCylData        = []   // per ds-bridge cylinder instance: {bridgeHelixId, strandId}
  let _structuralCylSaved = []

  const _ovhgCylMesh = (dom) => dom.fullCylinder ? iOverhangFullCylinders : iOverhangCylinders
  const _curvedOvhgCylMesh = (dom) => dom.fullCylinder ? iCurvedOverhangFullCylinders : iCurvedOverhangCylinders
  const _markOvhgCylMatricesDirty = () => {
    iOverhangCylinders.instanceMatrix.needsUpdate = true
    iOverhangFullCylinders.instanceMatrix.needsUpdate = true
  }
  const _markCurvedOvhgCylMatricesDirty = () => {
    iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true
    iCurvedOverhangFullCylinders.instanceMatrix.needsUpdate = true
  }
  const _markOvhgCylColorsDirty = () => {
    if (iOverhangCylinders.instanceColor) iOverhangCylinders.instanceColor.needsUpdate = true
    if (iOverhangFullCylinders.instanceColor) iOverhangFullCylinders.instanceColor.needsUpdate = true
  }
  const _markCurvedOvhgCylColorsDirty = () => {
    if (iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true
    if (iCurvedOverhangFullCylinders.instanceColor) iCurvedOverhangFullCylinders.instanceColor.needsUpdate = true
  }

  let _detailLevel    = 0    // 0=full, 1=beads-only, 2=cylinders
  let _beadScale      = 1.0  // global scale factor applied to all backbone beads
  // Keys for cluster visibility toggle.  Two formats:
  //   'h:<helix_id>'                   — hide the whole helix (helix-level cluster)
  //   'd:<strand_id>:<domain_index>'   — hide specific domain (domain-level cluster)
  let _hiddenNucKeys = new Set()
  const _isNucHidden = (nuc, copy = nuc?.copy_k ?? 0) =>
    _hiddenNucKeys.has('h:' + nuc.helix_id) ||
    (nuc.domain_index != null && _hiddenNucKeys.has('d:' + nuc.strand_id + ':' + nuc.domain_index)) ||
    _hiddenNucKeys.has(baseKey(nuc, copy))
  let _cylRadiusScale = 1.0  // XZ scale applied to domain cylinders (1 = geometry default 1.125 nm)

  // ── Curved-tube builder ────────────────────────────────────────────────────
  // Builds a TubeGeometry for a domain spanning bp [lo, hi] on a curved helix.
  // Returns { geo, t0Curve, t1Curve } where t0/t1Curve are the curve parameters
  // used (so they can be re-used when rebuilding after a radius change).
  function _buildDomainTubeGeo(arrow, lo, hi, tubRadius, openAngle = 2 * Math.PI) {
    const nSamples  = arrow.samples.length
    const bpSpan    = Math.max(1, arrow.bpLen - 1)
    const halfBpT   = 0.5 / bpSpan
    const t0c = Math.max(0, Math.min(1, (lo - arrow.bpStart) / bpSpan - halfBpT))
    const t1c = Math.max(0, Math.min(1, (hi - arrow.bpStart) / bpSpan + halfBpT))
    if (t1c <= t0c) return null

    const fullCurve = new THREE.CatmullRomCurve3(arrow.samples.map(s => new THREE.Vector3(s[0], s[1], s[2])))
    const nPts = Math.max(4, Math.ceil(nSamples * (t1c - t0c)) + 2)
    const pts  = []
    for (let i = 0; i <= nPts; i++) pts.push(fullCurve.getPoint(t0c + (i / nPts) * (t1c - t0c)))
    const segCurve = new THREE.CatmullRomCurve3(pts)
    const segs     = Math.max(2, nPts)
    const fullTube  = openAngle >= 2 * Math.PI - 1e-6
    const radialSeg = fullTube ? 8 : 4
    const tube = new THREE.TubeGeometry(segCurve, segs, tubRadius, radialSeg, false)
    // TubeGeometry is OPEN at both ends. Uncapped, the open ends read as dark
    // see-through holes at helix tips and FrontSide back-face culls into them —
    // "portions of the cylinder disappear at certain angles". Cap full tubes with
    // two oriented discs so they look solid like the capped straight GEO_UNIT_CYL
    // cylinders. (Half-tube overhangs, openAngle<2π, stay uncapped + DoubleSide.)
    if (!fullTube) return { geo: tube, t0Curve: t0c, t1Curve: t1c }
    const _Z = new THREE.Vector3(0, 0, 1)
    const _one = new THREE.Vector3(1, 1, 1)
    const _q = new THREE.Quaternion()
    const mkCap = (point, outwardNormal) => {
      const cap = new THREE.CircleGeometry(tubRadius, radialSeg)  // XY plane, +Z normal
      cap.applyMatrix4(new THREE.Matrix4().compose(point, _q.setFromUnitVectors(_Z, outwardNormal), _one))
      return cap
    }
    const tStart = segCurve.getTangent(0).normalize()
    const tEnd   = segCurve.getTangent(1).normalize()
    const capA   = mkCap(pts[0],                tStart.clone().negate())  // start cap faces away from tube
    const capB   = mkCap(pts[pts.length - 1],   tEnd)                     // end cap faces forward
    const geo = mergeGeometries([tube, capA, capB], false) ?? tube
    return { geo, t0Curve: t0c, t1Curve: t1c }
  }

  {
    const helixMap = new Map(design.helices.map(h => [h.id, h]))
    let cylIdx       = 0   // straight domain instanced-mesh counter
    let curvedIdx    = 0   // curved domain proxy instanced-mesh counter
    let ovhgIdx      = 0   // straight overhang instanced-mesh counter
    let ovhgFullIdx  = 0   // straight full-overhang instanced-mesh counter
    let curvedOvhgIdx = 0  // curved overhang proxy instanced-mesh counter
    let curvedOvhgFullIdx = 0

    const CYL_TUBE_R = 1.125 * _cylRadiusScale  // tube radius matching GEO_UNIT_CYL

    for (const strand of design.strands) {
      // Scaffold domains skipped to avoid z-fighting.
      if (strand.strand_type === 'scaffold') continue
      const isLinker = strand.strand_type === 'linker'

      const strandColor = loopSet.has(strand.id) ? C.highlight_red
        : (customColors[strand.id] ?? stapleColorMap.get(strand.id) ?? C.unassigned)

      for (let domIdx = 0; domIdx < strand.domains.length; domIdx++) {
        const dom    = strand.domains[domIdx]
        const isOvhg = dom.overhang_id != null
        const helix  = helixMap.get(dom.helix_id)
        const arrow  = _arrowByHelixId.get(dom.helix_id)
        // Bridge domains live on `__lnk__` helices, which have no axis arrow
        // (skipped above) — the deferred pass draws their cylinder from nucs.
        if (!helix || !arrow) continue

        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        const isDirectFullOvhg = isOvhg && _directConnectedOverhangIds.has(dom.overhang_id)

        // Linker binding (complement) domain: defer — drawn as a half-cylinder
        // opposite its overhang half, in the linker colour, after this loop.
        if (isLinker) {
          _deferredBindings.push({ helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, lo, hi, color: strandColor, arrow })
          continue
        }

        if (arrow.isCurved) {
          // ── Curved helix: TubeGeometry + straight proxy ─────────────────────
          const openAngle = (isOvhg && !isDirectFullOvhg) ? Math.PI : 2 * Math.PI
          const built = _buildDomainTubeGeo(arrow, lo, hi, CYL_TUBE_R, openAngle)
          if (built) {
            const tubeMesh = new THREE.Mesh(
              built.geo,
              new THREE.MeshLambertMaterial({
                // Resting (deformed) state is opacity 1 → opaque + depthWrite so it
                // sorts correctly and does not sit in the transparent queue (see
                // _fadeMat). The lerp flips these when fading toward the straight proxy.
                color: strandColor, transparent: false, opacity: 1, depthWrite: true,
                side: (isOvhg && !isDirectFullOvhg) ? THREE.DoubleSide : THREE.FrontSide,
              }),
            )
            tubeMesh.userData = { helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, bp_lo: lo, bp_hi: hi, t0: built.t0Curve, t1: built.t1Curve, isOvhg, fullCylinder: isDirectFullOvhg, defaultColor: strandColor }
            if (isOvhg) _curvedOvhgGroup.add(tubeMesh)
            else        _curvedCylGroup.add(tubeMesh)
          }

          // Straight proxy (straight line between aStart/aEnd, used during lerp t→0).
          const s = arrow.aStart, e = arrow.aEnd
          const axLen = s.distanceTo(e)
          if (axLen >= 0.001) {
            const tRaw0 = (lo - helix.bp_start) * BDNA_RISE_PER_BP / axLen
            const tRaw1 = (hi - helix.bp_start) * BDNA_RISE_PER_BP / axLen
            const hBp   = 0.5 * BDNA_RISE_PER_BP / axLen
            const t0p   = Math.max(0, tRaw0 - hBp)
            const t1p   = Math.min(1, tRaw1 + hBp)
            const p0x = s.x + (e.x - s.x) * t0p, p0y = s.y + (e.y - s.y) * t0p, p0z = s.z + (e.z - s.z) * t0p
            const p1x = s.x + (e.x - s.x) * t1p, p1y = s.y + (e.y - s.y) * t1p, p1z = s.z + (e.z - s.z) * t1p
            _tPos.set((p0x + p1x) * 0.5, (p0y + p1y) * 0.5, (p0z + p1z) * 0.5)
            _physDir.set(p1x - p0x, p1y - p0y, p1z - p0z)
            const pLen = _physDir.length()
            if (pLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(pLen))
            else _cylQ.identity()
            _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, pLen, _cylRadiusScale))
            const iProxy = isOvhg
              ? (isDirectFullOvhg ? iCurvedOverhangFullCylinders : iCurvedOverhangCylinders)
              : iCurvedHelixCylinders
            const idxProxy = isOvhg
              ? (isDirectFullOvhg ? curvedOvhgFullIdx : curvedOvhgIdx)
              : curvedIdx
            iProxy.setMatrixAt(idxProxy, _tMatrix)
            iProxy.setColorAt(idxProxy, _tColor.setHex(strandColor))
            if (isOvhg) {
              const cylIdx = isDirectFullOvhg ? curvedOvhgFullIdx++ : curvedOvhgIdx++
              _curvedOvhgCylData.push({ helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, bp_lo: lo, bp_hi: hi, t0: t0p, t1: t1p, cylIdx, arrow, fullCylinder: isDirectFullOvhg, defaultColor: strandColor })
            } else {
              _curvedDomainCylData.push({ helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, bp_lo: lo, bp_hi: hi, t0: t0p, t1: t1p, cylIdx: curvedIdx, arrow, defaultColor: strandColor })
              curvedIdx++
            }
          }
        } else {
          // ── Straight helix: existing instanced-mesh approach ─────────────────
          const s = arrow.aStart, e = arrow.aEnd
          const axLen = s.distanceTo(e)
          if (axLen < 0.001) continue
          const tRaw0 = (lo - helix.bp_start) * BDNA_RISE_PER_BP / axLen
          const tRaw1 = (hi - helix.bp_start) * BDNA_RISE_PER_BP / axLen
          const hBp   = 0.5 * BDNA_RISE_PER_BP / axLen
          const t0     = Math.max(0, tRaw0 - hBp)
          const t1     = Math.min(1, tRaw1 + hBp)
          const d0x = s.x + (e.x - s.x) * t0, d0y = s.y + (e.y - s.y) * t0, d0z = s.z + (e.z - s.z) * t0
          const d1x = s.x + (e.x - s.x) * t1, d1y = s.y + (e.y - s.y) * t1, d1z = s.z + (e.z - s.z) * t1
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          if (isOvhg) {
            // If per-domain ovhg_axes are available, use them directly for the initial
            // cylinder matrix and store world-space endpoints for cluster transforms.
            const ovhgAx = helixAxes?.[dom.helix_id]?.ovhgAxes?.[dom.overhang_id] ?? null
            let wsStart = null, wsEnd = null
            if (ovhgAx) {
              const ws = new THREE.Vector3(...ovhgAx.start)
              const we = new THREE.Vector3(...ovhgAx.end)
              const bpSpan = ovhgAx.bp_max - ovhgAx.bp_min + 1
              const hf = 0.5 / bpSpan
              const t0ov = Math.max(0, (lo - ovhgAx.bp_min) / bpSpan - hf)
              const t1ov = Math.min(1, (hi - ovhgAx.bp_min) / bpSpan + hf)
              const dir = we.clone().sub(ws)
              wsStart = ws.clone().addScaledVector(dir, t0ov)
              wsEnd   = ws.clone().addScaledVector(dir, t1ov)
              _tPos.set((wsStart.x + wsEnd.x) * 0.5, (wsStart.y + wsEnd.y) * 0.5, (wsStart.z + wsEnd.z) * 0.5)
              _physDir.set(wsEnd.x - wsStart.x, wsEnd.y - wsStart.y, wsEnd.z - wsStart.z)
              const cl2 = _physDir.length()
              if (cl2 > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cl2))
              else _cylQ.identity()
              _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cl2, _cylRadiusScale))
            }
            // Record this overhang half's final orientation so a linker binding
            // domain on the same helix + bp range can be placed on the opposite
            // half (same pose, rolled π about the axis).
            _ovhgBuildXform.set(`${dom.helix_id}|${lo}|${hi}`, {
              pos: _tPos.clone(), quat: _cylQ.clone(), lenY: _tScale.y,
            })
            const cylMesh = isDirectFullOvhg ? iOverhangFullCylinders : iOverhangCylinders
            const cylIdx = isDirectFullOvhg ? ovhgFullIdx++ : ovhgIdx++
            cylMesh.setMatrixAt(cylIdx, _tMatrix)
            cylMesh.setColorAt(cylIdx, _tColor.setHex(strandColor))
            _overhangCylData.push({ helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, overhangId: dom.overhang_id, bp_lo: lo, bp_hi: hi, t0, t1, cylIdx, arrow, fullCylinder: isDirectFullOvhg, defaultColor: strandColor, wsStart, wsEnd })
          } else {
            iHelixCylinders.setMatrixAt(cylIdx, _tMatrix)
            iHelixCylinders.setColorAt(cylIdx, _tColor.setHex(strandColor))
            _domainCylData.push({ helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, bp_lo: lo, bp_hi: hi, t0, t1, cylIdx, arrow, defaultColor: strandColor })
            cylIdx++
          }
        }
      }
    }

    // ── Deferred pass: linker binding halves + ds bridge cylinders ───────────
    // Binding (complement) half-cylinders: same pose as their overhang half,
    // rolled π so they sit on the opposite face → one two-toned full duplex.
    let bindIdx = 0
    for (const b of _deferredBindings) {
      const xf = _ovhgBuildXform.get(`${b.helixId}|${b.lo}|${b.hi}`)
      if (xf) {
        _cylQRolled.copy(xf.quat).multiply(_QUAT_ROLL_PI)
        _tMatrix.compose(xf.pos, _cylQRolled, _tScale.set(_cylRadiusScale, xf.lenY, _cylRadiusScale))
      } else {
        // Fallback (no overhang half in this build — e.g. assembly linker group,
        // or a curved overhang helix): place from the binding domain's own axis.
        const s = b.arrow.aStart, e = b.arrow.aEnd
        const axLen = s.distanceTo(e)
        if (axLen < 0.001) continue
        const helix = helixMap.get(b.helixId)
        const tRaw0 = (b.lo - (helix?.bp_start ?? 0)) * BDNA_RISE_PER_BP / axLen
        const tRaw1 = (b.hi - (helix?.bp_start ?? 0)) * BDNA_RISE_PER_BP / axLen
        const hBp   = 0.5 * BDNA_RISE_PER_BP / axLen
        const t0 = Math.max(0, tRaw0 - hBp), t1 = Math.min(1, tRaw1 + hBp)
        const d0x = s.x + (e.x - s.x) * t0, d0y = s.y + (e.y - s.y) * t0, d0z = s.z + (e.z - s.z) * t0
        const d1x = s.x + (e.x - s.x) * t1, d1y = s.y + (e.y - s.y) * t1, d1z = s.z + (e.z - s.z) * t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cl = _physDir.length()
        if (cl > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cl)); else _cylQ.identity()
        _cylQRolled.copy(_cylQ).multiply(_QUAT_ROLL_PI)
        _tMatrix.compose(_tPos, _cylQRolled, _tScale.set(_cylRadiusScale, cl, _cylRadiusScale))
      }
      iLinkerBindingCylinders.setMatrixAt(bindIdx, _tMatrix)
      iLinkerBindingCylinders.setColorAt(bindIdx, _tColor.setHex(b.color))
      // Record the instance→domain mapping. It must be written INSIDE the loop:
      // the fallback branch above can `continue` without incrementing bindIdx, so
      // an instance's index is not its position in _deferredBindings.
      _bindingCylData.push({
        helixId: b.helixId, strandId: b.strandId, domainIndex: b.domainIndex,
        bp_lo: b.lo, bp_hi: b.hi, cylIdx: bindIdx,
      })
      bindIdx++
    }
    iLinkerBindingCylinders.count = bindIdx

    // ds bridge: one full cylinder per `__lnk__` helix, spanning the bridge
    // duplex axis recovered by averaging the paired beads at each end bp.
    let bridgeIdx = 0
    for (const bridgeHelixId of _dsBridgeHelixIds) {
      const bnucs = geometry.filter(n => n.helix_id === bridgeHelixId)
      if (bnucs.length < 2) continue
      let loBp = Infinity, hiBp = -Infinity
      for (const n of bnucs) { if (n.bp_index < loBp) loBp = n.bp_index; if (n.bp_index > hiBp) hiBp = n.bp_index }
      const axisAtBp = (bp) => {
        const pts = bnucs.filter(n => n.bp_index === bp)
        if (!pts.length) return null
        const v = new THREE.Vector3()
        for (const n of pts) { const p = n.base_position ?? n.backbone_position; v.x += p[0]; v.y += p[1]; v.z += p[2] }
        return v.multiplyScalar(1 / pts.length)
      }
      const a = axisAtBp(loBp), z = axisAtBp(hiBp)
      if (!a || !z) continue
      const _linkColor = (sid) => loopSet.has(sid) ? C.highlight_red
        : (customColors[sid] ?? stapleColorMap.get(sid) ?? C.unassigned)
      const color = _linkColor(`${bridgeHelixId}__a`)
      _tPos.copy(a).add(z).multiplyScalar(0.5)
      _physDir.copy(z).sub(a)
      const len = _physDir.length()
      if (len > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(len)); else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, Math.max(len, 0.001), _cylRadiusScale))
      iLinkerBridgeCylinders.setMatrixAt(bridgeIdx, _tMatrix)
      iLinkerBridgeCylinders.setColorAt(bridgeIdx, _tColor.setHex(color))
      // Map this cylinder instance → the ds-linker strand (so it's clickable) and
      // its bridge-helix bp span (so per-region reps can drive its visibility).
      _bridgeCylData[bridgeIdx] = { bridgeHelixId, strandId: `${bridgeHelixId}__a`, bp_lo: loBp, bp_hi: hiBp, cylIdx: bridgeIdx }
      bridgeIdx++
    }
    iLinkerBridgeCylinders.count = bridgeIdx
    iLinkerBindingCylinders.instanceMatrix.needsUpdate = true
    if (iLinkerBindingCylinders.instanceColor) iLinkerBindingCylinders.instanceColor.needsUpdate = true
    iLinkerBridgeCylinders.instanceMatrix.needsUpdate = true
    if (iLinkerBridgeCylinders.instanceColor) iLinkerBridgeCylinders.instanceColor.needsUpdate = true
  }

  iHelixCylinders.instanceMatrix.needsUpdate        = true
  if (iHelixCylinders.instanceColor)         iHelixCylinders.instanceColor.needsUpdate         = true
  iCurvedHelixCylinders.instanceMatrix.needsUpdate  = true
  if (iCurvedHelixCylinders.instanceColor)   iCurvedHelixCylinders.instanceColor.needsUpdate   = true
  iOverhangCylinders.instanceMatrix.needsUpdate     = true
  if (iOverhangCylinders.instanceColor)      iOverhangCylinders.instanceColor.needsUpdate      = true
  iOverhangFullCylinders.instanceMatrix.needsUpdate = true
  if (iOverhangFullCylinders.instanceColor)  iOverhangFullCylinders.instanceColor.needsUpdate  = true
  iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true
  if (iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true
  iCurvedOverhangFullCylinders.instanceMatrix.needsUpdate = true
  if (iCurvedOverhangFullCylinders.instanceColor) iCurvedOverhangFullCylinders.instanceColor.needsUpdate = true

  // ── Slab param update ──────────────────────────────────────────────────────

  function applySlabParams() {
    for (const entry of slabEntries) {
      _slabAxisDir.set(...entry.nuc.axis_tangent).normalize()
      const center = _slabCenterAt(entry, _slabAxisDir, null, null, _slabCenterD)
      _tMatrix.compose(center, entry.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(entry.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true
    _refreshSlabConnectors()
  }

  // ── Validation overlay ─────────────────────────────────────────────────────

  let overlayObjects = []
  let distLabelInfo  = null

  function clearOverlay() {
    for (const obj of overlayObjects) {
      root.remove(obj)
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) obj.material.dispose()
    }
    overlayObjects = []
    document.querySelector('.dist-label')?.remove()
    distLabelInfo = null
  }

  // ── Reset helpers ──────────────────────────────────────────────────────────

  /**
   * Reset all instance colours and bead scales.
   *
   * dimmed=true  →  colour all instances with C.dim (dark slate) to indicate
   *                 they are "background".  A validation mode then selectively
   *                 re-colours its highlighted subset.
   * dimmed=false →  restore each instance to its defaultColor.
   */
  function resetAllToDefault(dimmed = false) {
    const dimHex = C.dim
    for (const entry of backboneEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
      _setBeadScale(entry, _isNucHidden(entry.nuc) ? 0 : _beadScale)
    }
    for (const entry of coneEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
      // Cross-helix cones stay hidden (rendered as arc lines instead).
      if (!entry.isCrossHelix) _setConeXZScale(entry, _isNucHidden(entry.fromNuc) ? 0 : CONE_RADIUS)
    }
    for (const entry of slabEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
    }
    const axisOpacity = dimmed ? 0.15 : 1.0
    for (const arrow of axisArrows) {
      for (const m of _arrowMaterials(arrow)) {
        m.opacity     = axisOpacity
        m.transparent = dimmed
      }
    }
  }

  // Iterate every material on an axis arrow (shaft + per-domain segments) so
  // dim/highlight passes can flip opacity/colour without touching node count.
  // Yields every mesh on the arrow including the straight-shaft companion
  // and per-segment curved tubes — callers need all of them to stay in sync.
  function* _arrowMaterials(arrow) {
    if (arrow.shaft?.material)         yield arrow.shaft.material
    if (arrow.straightShaft?.material) yield arrow.straightShaft.material
    for (const seg of arrow.segments ?? []) {
      if (seg.mesh?.material)     yield seg.mesh.material
      if (seg.tubeMesh?.material) yield seg.tubeMesh.material
    }
  }

  function highlightBackbone(nuc, color, scale = 1) {
    const entry = backboneEntries.find(e => e.nuc === nuc)
    if (!entry) return
    _setInstColor(entry, color)
    _setBeadScale(entry, scale)
  }

  function setDistLabel(midpoint, text) {
    distLabelInfo = { midpoint, text }
  }

  // ── Validation modes ───────────────────────────────────────────────────────

  function modeNormal() { clearOverlay(); resetAllToDefault(false) }
  function modeV21()    { clearOverlay(); resetAllToDefault(false) }

  function modeV11() {
    clearOverlay()
    resetAllToDefault(false)
    for (const entry of backboneEntries) {
      if (entry.nuc.direction === 'REVERSE') _setInstColor(entry, C.dim)
    }
    for (const entry of slabEntries) {
      if (entry.nuc.direction === 'REVERSE') _setInstColor(entry, C.dim)
    }
  }

  function modeV12() {
    clearOverlay()
    resetAllToDefault(true)
    const bp0 = byBp.get(0)?.['FORWARD']
    const bp1 = byBp.get(1)?.['FORWARD']
    if (!bp0 || !bp1) return
    highlightBackbone(bp0, C.highlight_red, 3.0)
    highlightBackbone(bp1, C.highlight_red, 3.0)
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...bp0.backbone_position),
      new THREE.Vector3(...bp1.backbone_position),
    ])
    const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: C.white }))
    root.add(line)
    overlayObjects.push(line)
    const v   = new THREE.Vector3(...bp1.backbone_position).sub(new THREE.Vector3(...bp0.backbone_position))
    const tan = new THREE.Vector3(...bp0.axis_tangent)
    const mid = [
      (bp0.backbone_position[0] + bp1.backbone_position[0]) / 2,
      (bp0.backbone_position[1] + bp1.backbone_position[1]) / 2,
      (bp0.backbone_position[2] + bp1.backbone_position[2]) / 2,
    ]
    setDistLabel(mid, `axial rise: ${Math.abs(v.dot(tan)).toFixed(4)} nm`)
  }

  function modeV13() {
    clearOverlay()
    resetAllToDefault(true)
    const bp0 = byBp.get(0)?.['FORWARD']
    if (!bp0) return
    highlightBackbone(bp0, C.highlight_red, 2.0)
    const se = slabEntries.find(e => e.nuc === bp0)
    if (se) _setInstColor(se, C.highlight_yellow)
    const spike = new THREE.ArrowHelper(
      new THREE.Vector3(...bp0.base_normal),
      new THREE.Vector3(...bp0.backbone_position),
      1.5, C.highlight_yellow, 0.25, 0.10,
    )
    root.add(spike)
    overlayObjects.push(spike)
  }

  function modeV14() {
    clearOverlay()
    resetAllToDefault(true)
    const bp10f = byBp.get(10)?.['FORWARD']
    const bp10r = byBp.get(10)?.['REVERSE']
    if (!bp10f || !bp10r) return
    highlightBackbone(bp10f, C.highlight_red,  3.0)
    highlightBackbone(bp10r, C.highlight_blue, 3.0)
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...bp10f.backbone_position),
      new THREE.Vector3(...bp10r.backbone_position),
    ])
    const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: C.white }))
    root.add(line)
    overlayObjects.push(line)
    for (const arrow of axisArrows) {
      for (const m of _arrowMaterials(arrow)) {
        m.color.setHex(C.white)
        m.opacity     = 1.0
        m.transparent = false
      }
    }
  }

  function modeV22() {
    clearOverlay()
    resetAllToDefault(true)
    for (const entry of backboneEntries) {
      if (entry.nuc.is_five_prime || entry.nuc.is_three_prime) highlightBackbone(entry.nuc, C.white, 3.0)
    }
  }

  function modeV23() {
    clearOverlay()
    resetAllToDefault(true)
    for (const entry of backboneEntries) {
      if (entry.nuc.is_five_prime)  highlightBackbone(entry.nuc, C.scaffold_backbone, 3.0)
      if (entry.nuc.is_three_prime) highlightBackbone(entry.nuc, C.highlight_red,     3.0)
    }
  }

  function modeV24() {
    clearOverlay()
    resetAllToDefault(true)
    for (const entry of backboneEntries) {
      if (entry.nuc.strand_type === 'scaffold') _setInstColor(entry, entry.defaultColor)
    }
    for (const entry of slabEntries) {
      if (entry.nuc.strand_type === 'scaffold') _setInstColor(entry, entry.defaultColor)
    }
    for (const entry of backboneEntries) {
      if (entry.nuc.strand_type === 'scaffold' && (entry.nuc.is_five_prime || entry.nuc.is_three_prime)) {
        highlightBackbone(entry.nuc, C.highlight_magenta, 3.5)
      }
    }
  }

  // ── Live position-update support (lookup maps + per-frame mesh updaters) ──

  // Fast lookup: nuc object → backboneEntry, and key string → backboneEntry.
  const _nucToEntry = new Map()
  const _keyToEntry = new Map()
  // Loop insertions put several nucleotides at one (helix,bp,dir); they collapse in
  // _keyToEntry (last wins). _copyKeyToEntry keys each one by its loop-copy index
  // ("helix:bp:dir:copy", copy = appearance order = geometry emission order) so a
  // sim/scalar update carrying a copy index can address the RIGHT bead instead of
  // only the last copy. Non-loop beads are copy 0. See applyFemPositions/applyScalarColors.
  const _copyKeyToEntry = new Map()
  const _copySeenBB = new Map()
  for (const entry of backboneEntries) {
    _nucToEntry.set(entry.nuc, entry)
    const n = entry.nuc
    const bk = `${n.helix_id}:${n.bp_index}:${n.direction}`
    _keyToEntry.set(bk, entry)
    const ci = _copySeenBB.get(bk) ?? 0
    _copySeenBB.set(bk, ci + 1)
    entry._copy = ci
    _copyKeyToEntry.set(`${bk}:${ci}`, entry)
  }

  const _connectorCenter = new THREE.Vector3()
  const _connectorQuat = new THREE.Quaternion()
  const _connectorScale = new THREE.Vector3()
  const _connectorCorner = new THREE.Vector3()
  const _connectorMid = new THREE.Vector3()
  const _connectorDirection = new THREE.Vector3()
  const _connectorRodQuat = new THREE.Quaternion()
  const _connectorColor = new THREE.Color()
  function _refreshSlabConnectors() {
    if (!_slabConnectorsReady) return
    for (let i = 0; i < slabEntries.length; i++) {
      const slab = slabEntries[i]
      const bead = _nucToEntry.get(slab.nuc)?.pos ?? slab.bbPos
      iSlabs.getMatrixAt(slab.id, _tMatrix)
      _tMatrix.decompose(_connectorCenter, _connectorQuat, _connectorScale)
      slabConnectionCorner(
        _connectorCenter, _connectorQuat, bead,
        _connectorScale.x * 0.5, _connectorScale.z * 0.5, _connectorCorner,
      )
      _connectorDirection.copy(_connectorCorner).sub(bead)
      const length = Math.max(0.001, _connectorDirection.length())
      _connectorMid.copy(bead).add(_connectorCorner).multiplyScalar(0.5)
      _connectorRodQuat.setFromUnitVectors(Y_HAT, _connectorDirection.divideScalar(length))
      _tMatrix.compose(
        _connectorMid,
        _connectorRodQuat,
        _tScale.set(SLAB_CONNECTOR_RADIUS, length, SLAB_CONNECTOR_RADIUS),
      )
      iSlabConnectors.setMatrixAt(i, _tMatrix)
      // Geometry refreshes happen during trajectory/FEM/flexible displays. Never reset
      // the rod to the design default: mirror the slab's CURRENT colour so an active
      // flex map or right-sidebar colouring mode survives the position update.
      iSlabs.getColorAt(slab.id, _connectorColor)
      iSlabConnectors.setColorAt(i, _connectorColor)
    }
    iSlabConnectors.instanceMatrix.needsUpdate = true
    if (iSlabConnectors.instanceColor) iSlabConnectors.instanceColor.needsUpdate = true
  }
  _slabConnectorsReady = true
  _refreshSlabConnectors()
  // Per-instance colour captured before a scalar (RMSF) recolour overlay (beads +
  // cones + slabs), so it can be restored when the overlay is cleared.  null = no
  // overlay active.
  let _savedScalarColors = null
  const _scalarColorScratch = new THREE.Color()
  function _flagScalarColorMeshes() {
    for (const m of [iSpheres, iCubes, iCones, iSlabs, iSlabConnectors]) {
      if (m && m.instanceColor) m.instanceColor.needsUpdate = true
    }
  }
  // key string → slab entry (for surgical per-bead overrides, e.g. overhang
  // unzip animation that moves only a handful of beads each frame).
  const _keyToSlab = new Map()
  const _copySeenSlab = new Map()
  for (const slab of slabEntries) {
    const n = slab.nuc
    const sk = `${n.helix_id}:${n.bp_index}:${n.direction}`
    _keyToSlab.set(sk, slab)
    // Loop-copy index (geometry emission order) so a per-copy sim normal reaches the
    // right slab — see the normalMap lookup in applyFemPositions.
    const ci = _copySeenSlab.get(sk) ?? 0
    _copySeenSlab.set(sk, ci + 1)
    slab._copy = ci
  }
  // key string → connector cones touching that bead (from OR to), so a surgical
  // per-bead move (setBeadOverrides) can recompose only the affected cones.
  const _keyToCones = new Map()
  for (const cone of coneEntries) {
    for (const n of [cone.fromNuc, cone.toNuc]) {
      const k = `${n.helix_id}:${n.bp_index}:${n.direction}`
      let arr = _keyToCones.get(k); if (!arr) { arr = []; _keyToCones.set(k, arr) }
      arr.push(cone)
    }
  }
  /** Recompose one connector cone from its endpoints' CURRENT bead positions. */
  function _recomposeCone(cone) {
    const fe = _nucToEntry.get(cone.fromNuc)
    const te = _nucToEntry.get(cone.toNuc)
    if (fe && te) {
      _physDir.copy(te.pos).sub(fe.pos)
      const dist = _physDir.length()
      cone.coneHeight = Math.max(0.001, dist)
      _physDir.divideScalar(dist || 1)
      cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
      cone.quat.setFromUnitVectors(Y_HAT, _physDir)
    }
    const r = cone.isCrossHelix ? 0 : cone.coneRadius
    _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, cone.coneHeight, r))
    iCones.setMatrixAt(cone.id, _tMatrix)
  }
  // Fluorophore beads live in fluoroEntries (separate from backboneEntries) and
  // are intentionally NOT added to _nucToEntry — the cone-update path doesn't
  // gate cross-helix cones to radius 0, so including fluoros there would draw
  // visible cones from the strand-end bead to the fluorophore. getNucLivePos
  // falls back to this map so arc endpoints landing on a fluorophore (e.g. the
  // cross-helix arc rendered by unfold_view._arcGroup) update correctly under
  // cluster transforms.
  const _fluoroNucToEntry = new Map()
  for (const entry of fluoroEntries) _fluoroNucToEntry.set(entry.nuc, entry)

  // ── Extension → parent helix map (for cluster rigid transforms) ─────────────
  // Maps extension_id → helix_id of the real terminal helix.
  const _extToRealHelix = new Map()
  for (const cone of coneEntries) {
    const fn = cone.fromNuc, tn = cone.toNuc
    if (!fn.helix_id.startsWith('__ext_') && tn.helix_id.startsWith('__ext_')) {
      const extId = tn.extension_id
      if (extId && !_extToRealHelix.has(extId)) _extToRealHelix.set(extId, fn.helix_id)
    } else if (fn.helix_id.startsWith('__ext_') && !tn.helix_id.startsWith('__ext_')) {
      const extId = fn.extension_id
      if (extId && !_extToRealHelix.has(extId)) _extToRealHelix.set(extId, tn.helix_id)
    }
  }

  // ── Extension → terminal-domain key (for sub-cluster cluster transforms) ────
  // Each extension dangles off one end of a parent strand. When the cluster
  // we're moving has `domain_ids` set (split-domain cluster), we need to know
  // whether the strand's terminal domain is in the moved domain set so we can
  // decide whether to move the extension with it. Without this map, sub-cluster
  // moves silently skip extensions on the moved cluster (the bug surfaced on
  // scadnano-imported designs where every cluster carries domain_ids).
  const _extToTerminalDomainKey = new Map()
  if (Array.isArray(design.extensions) && Array.isArray(design.strands)) {
    const strandById = new Map(design.strands.map(s => [s.id, s]))
    for (const ext of design.extensions) {
      const strand = strandById.get(ext.strand_id)
      if (!strand?.domains?.length) continue
      const idx = ext.end === 'five_prime' ? 0 : strand.domains.length - 1
      _extToTerminalDomainKey.set(ext.id, `${strand.id}:${idx}`)
    }
  }

  /**
   * Restore all geometry to its canonical 3D positions.
   *
   * When straightPosMap / straightAxesMap are supplied (deform view is OFF),
   * straight positions are used as the base so the scene stays in the
   * non-deformed state.  Without those maps the raw (possibly deformed)
   * backbone_position values are used instead.
   *
   * @param {Map<string,THREE.Vector3>|null} straightPosMap
   * @param {Map<string,{start,end}>|null}  straightAxesMap
   */
  function revertToGeometry(straightPosMap = null, straightAxesMap = null) {
    const useStraight = !!(straightPosMap && straightAxesMap)

    // 1. Backbone beads.
    for (const entry of backboneEntries) {
      const nuc = entry.nuc
      let bx, by, bz
      if (useStraight) {
        const sp = straightPosMap.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        bx = sp ? sp.x : nuc.backbone_position[0]
        by = sp ? sp.y : nuc.backbone_position[1]
        bz = sp ? sp.z : nuc.backbone_position[2]
      } else {
        const bp = nuc.backbone_position
        bx = bp[0]; by = bp[1]; bz = bp[2]
      }
      entry.pos.set(bx, by, bz)
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iSpheres.instanceMatrix.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true

    // 2. Cones — derived from bead positions so no separate map lookup needed.
    for (const cone of coneEntries) {
      const fe = _nucToEntry.get(cone.fromNuc)
      const te = _nucToEntry.get(cone.toNuc)
      let h
      if (fe && te) {
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        h = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
      } else {
        // Fallback to raw positions if entry lookup fails.
        const bp1 = cone.fromNuc.backbone_position
        const bp2 = cone.toNuc.backbone_position
        _physDir.set(bp2[0] - bp1[0], bp2[1] - bp1[1], bp2[2] - bp1[2])
        const dist = _physDir.length()
        h = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.set(
          (bp1[0] + bp2[0]) * 0.5,
          (bp1[1] + bp2[1]) * 0.5,
          (bp1[2] + bp2[2]) * 0.5,
        )
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
      }
      // Keep cross-helix cones hidden; they are rendered as arc lines.
      const r = cone.isCrossHelix ? 0 : cone.coneRadius
      _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
      iCones.setMatrixAt(cone.id, _tMatrix)
    }
    iCones.instanceMatrix.needsUpdate = true

    // 3. Slabs.
    for (const slab of slabEntries) {
      const nuc = slab.nuc
      let center_, quat_
      if (useStraight) {
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const sp  = straightPosMap.get(key)
        const sa  = straightAxesMap.get(nuc.helix_id)
        if (sp && sa) {
          _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
          _slabBnS.set(...nuc.base_normal)
          _slabQuatS.copy(slabQuaternion(_slabBnS, _slabAxisDir))
          slab.bbPos.copy(sp)
          center_ = _slabCenterAt(slab, _slabAxisDir, null, straightPosMap, _slabCenterS)
          quat_   = _slabQuatS
        } else {
          slab.bbPos.set(nuc.backbone_position[0], nuc.backbone_position[1], nuc.backbone_position[2])
          _slabAxisDir.set(...nuc.axis_tangent).normalize()
          center_ = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
          quat_   = slab.quat
        }
      } else {
        const bp = nuc.backbone_position
        slab.bbPos.set(bp[0], bp[1], bp[2])
        _slabAxisDir.set(...nuc.axis_tangent).normalize()
        center_ = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
        quat_   = slab.quat
      }
      _tMatrix.compose(center_, quat_,
        _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true
    _refreshSlabConnectors()

    // 4. Axis sticks.
    for (const arrow of axisArrows) {
      const sa = useStraight ? straightAxesMap.get(arrow.helixId) : null
      const baseStart = sa ? sa.start : arrow.aStart
      const baseEnd   = sa ? sa.end   : arrow.aEnd

      if (arrow.useSegments && arrow.isCurved) {
        // Multi-segment curved helix: per-segment positioning. Pass t=0
        // when reverting to straight (sa.segments are the destination), t=1
        // when reverting to deformed (stored wsStart/wsEnd are deformed).
        _lerpPerSegment(arrow, sa?.segments, useStraight ? 0 : 1)
      } else if (arrow.isCurved) {
        arrow.shaft.position.set(0, 0, 0)
        // Mutually-exclusive visibility (same rule as setAxisShaftMode), but
        // also gated by per-region rep so cylinder/surface columns stay axis-free.
        const axOn = _axisSegOn(arrow.helixId, arrow.bp_lo ?? 0, arrow.bp_hi ?? 0)
        if (arrow.shaft)         arrow.shaft.visible         = axOn && !useStraight
        if (arrow.straightShaft) arrow.straightShaft.visible = axOn &&  useStraight
        if (arrow.straightShaft && sa) {
          arrow.straightShaft.position.set(
            (sa.start.x + sa.end.x) * 0.5,
            (sa.start.y + sa.end.y) * 0.5,
            (sa.start.z + sa.end.z) * 0.5,
          )
        }
      } else {
        // Non-curved helix: lay each per-domain segment along baseStart→baseEnd.
        _layStraightSegments(arrow, baseStart, baseEnd)
      }
    }

    // 5. Helix cylinders (LOD) — reset to per-domain axis positions.
    for (const dom of _domainCylData) {
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iHelixCylinders.instanceMatrix.needsUpdate = true
    _refreshCylGlow()

    // 5b. Overhang half-cylinders.
    for (const dom of _overhangCylData) {
      if (dom.wsStart) continue  // shared-stub: stays at current rotated position; stubs don't bend
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      _ovhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
    }
    _markOvhgCylMatricesDirty()

    // 5c. Curved-helix proxy cylinders — snap to straight or deformed axis positions.
    for (const dom of _curvedDomainCylData) {
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLen0 = _physDir.length()
      if (cLen0 > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen0))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen0, _cylRadiusScale))
      iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
    const _cvProxyOp = useStraight ? 1 : 0
    _fadeCurvedProxy(iCurvedHelixCylinders.material, _cvProxyOp)
    for (const mesh of _curvedCylGroup.children)   _fadeCurvedTube(mesh, 1 - _cvProxyOp)
    for (const dom of _curvedOvhgCylData) {
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLen1 = _physDir.length()
      if (cLen1 > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen1))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen1, _cylRadiusScale))
      _curvedOvhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
    }
    _markCurvedOvhgCylMatricesDirty()
    _fadeCurvedProxy(iCurvedOverhangCylinders.material, _cvProxyOp)
    _fadeCurvedProxy(iCurvedOverhangFullCylinders.material, _cvProxyOp)
    for (const mesh of _curvedOvhgGroup.children) _fadeCurvedTube(mesh, 1 - _cvProxyOp)

    // 6. Fluorophore beads — always revert to backbone_position (no straight map).
    for (const entry of fluoroEntries) {
      const bp = entry.nuc.backbone_position
      entry.pos.set(bp[0], bp[1], bp[2])
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iFluoros.instanceMatrix.needsUpdate = true
  }

  /**
   * Translate all geometry to the 2D unfolded layout at lerp factor t (0=3D, 1=unfolded).
   * Called every animation frame during the unfold/refold transition.
   *
   * @param {Map<string, THREE.Vector3>} helixOffsets  helix_id → translation vector
   * @param {number} t  lerp factor in [0, 1]
   * @returns {Array<{from: THREE.Vector3, to: THREE.Vector3}>}  cross-helix connections
   *          (unfolded positions at the current t, for drawing arc overlays)
   */
  function applyUnfoldOffsets(helixOffsets, t, straightPosMap, straightAxesMap) {
    // 1. Backbone beads.
    for (const entry of backboneEntries) {
      // Extension beads (__ext_) are handled by their own method.
      if (entry.nuc.helix_id.startsWith('__ext_')) continue
      const off = helixOffsets.get(entry.nuc.helix_id)
      const nuc = entry.nuc
      let bx, by, bz
      if (straightPosMap) {
        const sp = straightPosMap.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        bx = sp ? sp.x : nuc.backbone_position[0]
        by = sp ? sp.y : nuc.backbone_position[1]
        bz = sp ? sp.z : nuc.backbone_position[2]
      } else {
        bx = nuc.backbone_position[0]
        by = nuc.backbone_position[1]
        bz = nuc.backbone_position[2]
      }
      entry.pos.set(
        bx + (off ? off.x * t : 0),
        by + (off ? off.y * t : 0),
        bz + (off ? off.z * t : 0),
      )
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iSpheres.instanceMatrix.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true

    // 2. Cones — hide cross-helix cones (they become arcs in unfold view).
    const crossHelixConns = []
    for (const cone of coneEntries) {
      const fe = _nucToEntry.get(cone.fromNuc)
      const te = _nucToEntry.get(cone.toNuc)
      if (!fe || !te) continue

      const isCrossHelix = cone.fromNuc.helix_id !== cone.toNuc.helix_id

      _physDir.copy(te.pos).sub(fe.pos)
      const dist = _physDir.length()
      const h    = Math.max(0.001, dist)
      _physDir.divideScalar(dist || 1)
      cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
      cone.quat.setFromUnitVectors(Y_HAT, _physDir)
      cone.coneHeight = h

      const r = isCrossHelix ? 0 : cone.coneRadius   // hide cross-helix cones
      _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
      iCones.setMatrixAt(cone.id, _tMatrix)

      if (isCrossHelix) crossHelixConns.push({
        from: fe.pos.clone(), to: te.pos.clone(), color: cone.defaultColor,
        fromHelixId: cone.fromNuc.helix_id, toHelixId: cone.toNuc.helix_id,
      })
    }
    iCones.instanceMatrix.needsUpdate = true

    // 3. Slabs — use straight bnDir/quaternion when straight maps are available.
    for (const slab of slabEntries) {
      // Extension beads (__ext_) have no slabs.
      if (slab.nuc.helix_id.startsWith('__ext_')) continue
      const entry = _nucToEntry.get(slab.nuc)
      if (!entry) continue

      const nuc = slab.nuc
      const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      const sp  = straightPosMap?.get(key)
      const sa  = straightAxesMap?.get(nuc.helix_id)

      let center_, quat_
      if (sp && sa) {
        // Compute straight base-normal via axis projection (same logic as applyDeformLerp at t=0).
        _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
        const axisProj = (sp.x - sa.start.x) * _slabAxisDir.x
                       + (sp.y - sa.start.y) * _slabAxisDir.y
                       + (sp.z - sa.start.z) * _slabAxisDir.z
        _slabProj.copy(sa.start).addScaledVector(_slabAxisDir, axisProj)
        _slabBnS.copy(_slabProj).sub(sp).normalize()
        _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
        _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
        _slabQuatS.setFromRotationMatrix(_slabBasis)

        center_ = _slabCenterAt(slab, _slabAxisDir, null, straightPosMap, _slabCenterS)
        quat_   = _slabQuatS
      } else {
        slab.bbPos.copy(entry.pos)
        _slabAxisDir.set(...nuc.axis_tangent).normalize()
        center_ = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
        quat_   = slab.quat
      }

      slab.bbPos.copy(entry.pos)
      _tMatrix.compose(center_, quat_,
        _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true
    _refreshSlabConnectors()

    // 4. Axis sticks.
    for (const arrow of axisArrows) {
      const off = helixOffsets.get(arrow.helixId)
      const ox  = off ? off.x * t : 0
      const oy  = off ? off.y * t : 0
      const oz  = off ? off.z * t : 0

      const sa         = straightAxesMap?.get(arrow.helixId)
      const baseStart  = sa ? sa.start : arrow.aStart
      const baseEnd    = sa ? sa.end   : arrow.aEnd

      if (arrow.useSegments && arrow.isCurved) {
        // Multi-segment curved helix: position each segment at its per-segment
        // straight endpoint + the unfold offset. Same rule as _lerpPerSegment
        // but with a uniform per-helix offset instead of an interpolation.
        const segs = sa?.segments
        for (let i = 0; i < arrow.segments.length; i++) {
          const seg = arrow.segments[i]
          const ss  = segs?.[i]
          const sx0 = (ss ? ss.start[0] : seg.wsStart.x) + ox
          const sy0 = (ss ? ss.start[1] : seg.wsStart.y) + oy
          const sz0 = (ss ? ss.start[2] : seg.wsStart.z) + oz
          const sx1 = (ss ? ss.end[0]   : seg.wsEnd.x)   + ox
          const sy1 = (ss ? ss.end[1]   : seg.wsEnd.y)   + oy
          const sz1 = (ss ? ss.end[2]   : seg.wsEnd.z)   + oz
          const dx = sx1 - sx0, dy = sy1 - sy0, dz = sz1 - sz0
          const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
          if (len < 0.001) continue
          _segDir.set(dx / len, dy / len, dz / len)
          seg.mesh.position.set((sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, (sz0 + sz1) * 0.5)
          seg.mesh.quaternion.setFromUnitVectors(_AY, _segDir)
        }
      } else if (arrow.isCurved) {
        arrow.shaft.position.set(ox, oy, oz)
        if (arrow.straightShaft && sa) {
          arrow.straightShaft.position.set(
            (sa.start.x + sa.end.x) * 0.5 + ox,
            (sa.start.y + sa.end.y) * 0.5 + oy,
            (sa.start.z + sa.end.z) * 0.5 + oz,
          )
        }
      } else {
        // Non-curved (single straight axis): lay segments along
        // (baseStart+offset) → (baseEnd+offset).
        _physDir.set(baseStart.x + ox, baseStart.y + oy, baseStart.z + oz)
        _physDir2.set(baseEnd.x + ox, baseEnd.y + oy, baseEnd.z + oz)
        _layStraightSegments(arrow, _physDir, _physDir2)
      }
    }

    // 5. Helix cylinders (LOD) — translate with unfold offset per domain.
    for (const dom of _domainCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0
      const oy2 = off ? off.y * t : 0
      const oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iHelixCylinders.instanceMatrix.needsUpdate = true
    _refreshCylGlow()

    // 5b. Overhang half-cylinders — translate with unfold offset.
    for (const dom of _overhangCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0
      const oy2 = off ? off.y * t : 0
      const oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      _ovhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
    }
    _markOvhgCylMatricesDirty()

    // 5c. Curved-helix proxy cylinders — translate with unfold offset (tubes are invisible at t=0 deform).
    for (const dom of _curvedDomainCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0, oy2 = off ? off.y * t : 0, oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLenA = _physDir.length()
      if (cLenA > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLenA))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLenA, _cylRadiusScale))
      iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
    for (const dom of _curvedOvhgCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0, oy2 = off ? off.y * t : 0, oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLenB = _physDir.length()
      if (cLenB > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLenB))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLenB, _cylRadiusScale))
      _curvedOvhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
    }
    _markCurvedOvhgCylMatricesDirty()

    return crossHelixConns
  }

  // ── Cluster base-position snapshot (captured at gizmo attach time) ───────────
  // Keyed so applyClusterTransform applies an incremental transform from these
  // positions rather than re-applying the full formula to already-transformed
  // backbone_position values (which would double the movement).

  let _cbEntries      = new Map()   // `helix_id:bp_index:direction` → THREE.Vector3
  let _cbSlabs        = new Map()   // slab.nuc ref → {bnDir: Vector3, quat: Quaternion}
  let _cbArrows       = new Map()   // helixId → {aStart, aEnd, shaftPos, shaftQuat, ssPos, ssQuat}
  let _cbExtEntries   = new Map()   // `helix_id:bp_index` → THREE.Vector3 for __ext_ beads
  let _cbFluoEntries  = new Map()   // `helix_id:bp_index` → THREE.Vector3 for fluorophore beads
  let _cbOvhgCyls     = new Map()   // _overhangCylData entry → {wsStart, wsEnd}
  let _cbSegments     = new Map()   // arrow.segments entry → {wsStart, wsEnd}

  // ── Reference geometry: per-instance alpha + hide ──────────────────────────
  // Installed only when the design has reference strands, so plain designs keep
  // their opaque bead materials. setReferenceStrands / setReferenceHidden are
  // (re)applied by design_renderer after each rebuild and on the View toggle.
  let _refIdSet  = new Set()
  let _refHidden = false
  const _hasReference = (design?.strands ?? []).some(s => s.is_reference)
  // Helices carrying ONLY reference strands — their helical-axis arrows hide with
  // the rest of the reference geometry (a mixed helix keeps its axis for the active part).
  const _refOnlyHelixIds = (() => {
    const ref = new Set(), active = new Set()
    for (const s of (design?.strands ?? [])) {
      const t = s.is_reference ? ref : active
      for (const d of (s.domains ?? [])) t.add(d.helix_id)
    }
    for (const h of active) ref.delete(h)
    return ref
  })()
  if (_hasReference) {
    _installInstanceAlpha(iSpheres)
    _installInstanceAlpha(iCubes)
    _installInstanceAlpha(iFluoros)
    _installInstanceAlpha(iCones)
    _installInstanceAlpha(iSlabs)
    _installInstanceAlpha(iSlabConnectors)
  }
  function _refAlphaFor(strandId) {
    if (!_refIdSet.has(strandId)) return 1.0
    return _refHidden ? 0.0 : REF_ALPHA
  }

  // ── Per-cluster opacity ─────────────────────────────────────────────────────
  // The third factor on the shared instanceAlpha channel. Keyed by the same nucKey
  // strings setHiddenNucs uses ('h:<helix_id>' / 'd:<strand_id>:<domain_index>'),
  // built by scene/cluster_entries.js and pushed in by design_renderer, which
  // re-pushes after every rebuild (a rebuild makes fresh meshes).
  let _clusterAlphaKeys = new Map()
  const _clusterAlphaFor = (nuc) => clusterAlphaForNuc(_clusterAlphaKeys, nuc)
  // A cylinder spans one domain, so it has its own {helixId, strandId, domainIndex}.
  const _clusterAlphaForCyl = (dom) => _clusterAlphaFor(
    dom && { helix_id: dom.helixId, strand_id: dom.strandId, domain_index: dom.domainIndex })
  const _hiddenAlphaFor = (nuc, copy = nuc?.copy_k ?? 0) => _isNucHidden(nuc, copy) ? 0 : 1
  function _hiddenAlphaForCyl(dom) {
    // Read source geometry, not backboneEntries: cheap cylinder-only builds
    // intentionally allocate no bead instances, but visibility must still work.
    const nucs = assignedGeometry.filter(n => n.strand_id === dom.strandId &&
      n.domain_index === dom.domainIndex)
    return nucs.length && nucs.every(n => _isNucHidden(n, n.copy_k ?? 0)) ? 0 : 1
  }

  // ── The composite alpha channel ─────────────────────────────────────────────
  // THREE independent factors multiply into ONE instanceAlpha attribute:
  //   reference-geometry ghosting × mixed-representation visibility × cluster opacity
  // They used to be written by two separate ABSOLUTE writers that clobbered each
  // other (the second hand-multiplied the first's factor back in). This is the
  // single writer for the no-override case; _applyRepOverrides is the single writer
  // when overrides are active. A future fourth factor is a new term, not a new sweep.
  const _anyAlpha = () => _hasReference || _repActive || _clusterAlphaKeys.size > 0 || _hiddenNucKeys.size > 0
  function _applyAlphaChannel() {
    if (!_anyAlpha() && !_repAlphaReady) return
    for (const e of backboneEntries) _setEntryAlpha(e, _refAlphaFor(e.nuc?.strand_id) * _clusterAlphaFor(e.nuc) * _hiddenAlphaFor(e.nuc, e._copy ?? 0))
    for (const e of slabEntries)     _setEntryAlpha(e, _refAlphaFor(e.nuc?.strand_id) * _clusterAlphaFor(e.nuc) * _hiddenAlphaFor(e.nuc, e._copy ?? 0))
    for (const e of fluoroEntries)   _setEntryAlpha(e, _refAlphaFor(e.nuc?.strand_id) * _clusterAlphaFor(e.nuc) * _hiddenAlphaFor(e.nuc, e._copy ?? 0))
    for (const e of coneEntries)     _setEntryAlpha(e, _refAlphaFor(e.strandId) * _clusterAlphaFor(e.fromNuc) * _hiddenAlphaFor(e.fromNuc))
    // Cylinders only once the buffers exist. Reference ghosting never drove them, so
    // this stays a no-op until per-cluster opacity (or a rep override) installs them
    // — and once installed it keeps maintaining them, so clearing a fade restores 1.
    if (_repAlphaReady) {
      for (const dom of _domainCylData)   _setCylAlpha(iHelixCylinders, dom.cylIdx, _refAlphaFor(dom.strandId) * _clusterAlphaForCyl(dom) * _hiddenAlphaForCyl(dom))
      for (const dom of _overhangCylData) _setCylAlpha(_ovhgCylMesh(dom), dom.cylIdx, _refAlphaFor(dom.strandId) * _clusterAlphaForCyl(dom) * _hiddenAlphaForCyl(dom))
      // Bridge cylinders live on synthetic '__lnk__' helices that no cluster lists,
      // so they never carry a cluster fade — restored to opaque, as before.
      for (const br of _bridgeCylData)    _setCylAlpha(iLinkerBridgeCylinders, br.cylIdx, 1)
    }
    // Curved proxies, curved tubes and binding cylinders. Unconditional: the tube
    // compositor has to run even before the instanceAlpha buffers exist, because
    // tube meshes fade through material.opacity, not through the buffers.
    _refreshCurvedAlpha()
    if (!_hasReference) return
    // Helical axis arrows of reference-only helices: hard-hide when reference is
    // hidden; restore via the normal shaft-mode logic when shown (respecting the
    // cadnano global axis gate).
    if (_refHidden && _refOnlyHelixIds.size) {
      for (const arrow of axisArrows) {
        if (!_refOnlyHelixIds.has(arrow.helixId)) continue
        if (arrow.shaft)         arrow.shaft.visible         = false
        if (arrow.straightShaft) arrow.straightShaft.visible = false
        for (const seg of arrow.segments ?? []) {
          if (seg.mesh)     seg.mesh.visible     = false
          if (seg.tubeMesh) seg.tubeMesh.visible = false
        }
      }
    } else if (_axisArrowsVisible) {
      _applyShaftModeVisibility(_currentShaftMode)
    }
  }
  // ── Per-region representation overrides (mixed representation) ──────────────
  // Pin some domains/strands to a different render rep than the global LOD, so a
  // focal region can show full bead-and-base detail against a cylinder-bundle
  // background. Implemented with per-instance alpha (NOT scale): bead/cylinder
  // matrices are rewritten by deform-lerp / radius changes, but the alpha
  // attribute is not, so the override survives every overlay. Reference alpha
  // and override visibility multiply.
  let _repColumnRep  = new Map()  // "helixId:bp" -> 'full' | 'cylinders' (both strands)
  let _repActive     = false
  // Latch: once the instanceAlpha buffers exist, every alpha writer keeps
  // maintaining them (so clearing a fade or an override restores 1.0 rather than
  // leaving the last written value baked in).
  let _repAlphaReady = false
  function _setCylAlpha(mesh, idx, a) {
    const attr = mesh._instanceAlpha
    if (!attr) return
    attr.setX(idx, a)
    attr.needsUpdate = true
  }
  /** Install per-instance alpha on every mesh the alpha channel drives. Lazy and
   *  idempotent: _installInstanceAlpha clones geometry and flips the material to
   *  transparent, so a design with no reference strands, no rep override and no
   *  cluster fade must never pay for it. */
  function _ensureAlphaInstalled() {
    if (_repAlphaReady) return
    _installInstanceAlpha(iSpheres)
    _installInstanceAlpha(iCubes)
    _installInstanceAlpha(iFluoros)
    _installInstanceAlpha(iCones)
    _installInstanceAlpha(iSlabs)
    _installInstanceAlpha(iSlabConnectors)
    _installInstanceAlpha(iHelixCylinders)
    // The curved proxies and the linker BINDING cylinders were the last three
    // cylinder families with no alpha channel. Their material.opacity is owned by
    // the deform cross-fade (proxies) or nothing at all (binding), so a per-instance
    // channel is the only way to fade one domain without touching the rest — and the
    // two compose for free: three multiplies material opacity into diffuseColor.a
    // before the instanceAlpha patch multiplies again.
    _installInstanceAlpha(iCurvedHelixCylinders)
    _installInstanceAlpha(iCurvedOverhangCylinders)
    _installInstanceAlpha(iCurvedOverhangFullCylinders)
    _installInstanceAlpha(iLinkerBindingCylinders)
    _installInstanceAlpha(iOverhangCylinders)
    _installInstanceAlpha(iOverhangFullCylinders)
    _installInstanceAlpha(iLinkerBridgeCylinders)
    _repAlphaReady = true
  }
  // Re-run the LOD .visible toggles for the current _detailLevel (used when
  // overrides are cleared, to hand visibility back to setDetailLevel's scheme).
  function _reapplyDetailVisibility() {
    const coarse = _detailLevel === 2
    iSpheres.visible = !coarse; iCubes.visible = !coarse; iCones.visible = !coarse
    iSlabs.visible = _detailLevel === 0; iSlabConnectors.visible = _detailLevel === 0; iFluoros.visible = !coarse
    iHelixCylinders.visible = coarse; iOverhangCylinders.visible = coarse; iOverhangFullCylinders.visible = coarse
    iCurvedHelixCylinders.visible = coarse; _curvedCylGroup.visible = coarse
    iCurvedOverhangCylinders.visible = coarse; iCurvedOverhangFullCylinders.visible = coarse; _curvedOvhgGroup.visible = coarse
    iLinkerBindingCylinders.visible = coarse; iLinkerBridgeCylinders.visible = coarse
  }
  // Effective rep at a duplex column (override wins; else the global rep). Hoisted
  // out of _applyRepOverrides so the curved-tube compositor can consult it too.
  function _effCol(helixId, bp) {
    const r = _repColumnRep.get(`${helixId}:${bp}`)
    return r ?? (_detailLevel === 2 ? 'cylinders' : 'full')
  }
  /** A domain cylinder shows only where EVERY column it spans resolves to
   *  'cylinders' — a region boundary cutting a domain falls back to beads rather
   *  than covering the full-rep half. Returns 1 when no override is active. */
  function _cylRepVis(dom) {
    if (!_repActive) return 1
    for (let bp = dom.bp_lo; bp <= dom.bp_hi; bp++) {
      if (_effCol(dom.helixId, bp) !== 'cylinders') return 0
    }
    return 1
  }
  /** The full alpha for one cylinder instance: ghosting x override x cluster. */
  function _cylFactor(dom) {
    return _refAlphaFor(dom.strandId) * _cylRepVis(dom) * _clusterAlphaForCyl(dom) * _hiddenAlphaForCyl(dom)
  }

  // ── Curved (deformed) tube compositor ───────────────────────────────────────
  // The curved tube meshes and their straight proxies cross-fade against each other
  // (`t` = 0 straight, 1 deformed), and that cross-fade used to write
  // `material.opacity` ABSOLUTELY — so any per-domain factor written there was
  // clobbered on the next lerp frame, which is why deformed designs showed no
  // cluster fade and no region override at cylinders rep. The cross-fade base is now
  // remembered per mesh and multiplied by the same three factors as everything else.
  //
  // Proxies are InstancedMeshes and carry the per-domain factor on their own
  // instanceAlpha channel, so their material only holds the base; the two multiply
  // in the shader. Only the non-instanced tube meshes need this.
  function _curvedTubeFactor(ud) {
    return _refAlphaFor(ud.strandId) * _cylRepVis(ud) *
      _clusterAlphaFor({ helix_id: ud.helixId, strand_id: ud.strandId, domain_index: ud.domainIndex }) *
      _hiddenAlphaForCyl(ud)
  }
  /** Set a curved TUBE's cross-fade base and re-apply base x per-domain factor. */
  function _fadeCurvedTube(mesh, base) {
    mesh.userData.crossfadeBase = base
    _fadeMat(mesh.material, base * _curvedTubeFactor(mesh.userData))
  }
  /** Set a curved PROXY material's cross-fade base. Keeps _fadeMat's depth contract
   *  (depthWrite only when opaque — an invisible occluder is LESSONS D8) but stays
   *  in the transparent queue whenever a per-instance factor is live, or the
   *  instanceAlpha multiply would have nothing to blend into. */
  function _fadeCurvedProxy(mat, base) {
    _fadeMat(mat, base)
    if (_anyAlpha()) mat.transparent = true
  }
  /** Re-apply every curved mesh's stored cross-fade base against current factors. */
  function _refreshCurvedAlpha() {
    for (const mesh of _curvedCylGroup.children)  _fadeCurvedTube(mesh, mesh.userData.crossfadeBase ?? 1)
    for (const mesh of _curvedOvhgGroup.children) _fadeCurvedTube(mesh, mesh.userData.crossfadeBase ?? 1)
    if (!_repAlphaReady) return
    for (const dom of _curvedDomainCylData) _setCylAlpha(iCurvedHelixCylinders, dom.cylIdx, _cylFactor(dom))
    for (const dom of _curvedOvhgCylData)   _setCylAlpha(_curvedOvhgCylMesh(dom), dom.cylIdx, _cylFactor(dom))
    for (const b of _bindingCylData)        _setCylAlpha(iLinkerBindingCylinders, b.cylIdx, _cylFactor(b))
    _fadeCurvedProxy(iCurvedHelixCylinders.material, iCurvedHelixCylinders.material.opacity)
    _fadeCurvedProxy(iCurvedOverhangCylinders.material, iCurvedOverhangCylinders.material.opacity)
    _fadeCurvedProxy(iCurvedOverhangFullCylinders.material, iCurvedOverhangFullCylinders.material.opacity)
  }

  function _applyRepOverrides() {
    if (!_repActive) {
      // Overrides off — hand the channel back to its other two factors.
      _applyAlphaChannel()
      _reapplyDetailVisibility()
      return
    }
    _ensureAlphaInstalled()
    // A bead (either strand) shows only where its column resolves to 'full'.
    const beadVis = (nuc) => (nuc && _effCol(nuc.helix_id, nuc.bp_index) === 'full' ? 1 : 0)
    for (const e of backboneEntries) _setEntryAlpha(e, _refAlphaFor(e.nuc?.strand_id) * beadVis(e.nuc) * _clusterAlphaFor(e.nuc) * _hiddenAlphaFor(e.nuc, e._copy ?? 0))
    for (const e of slabEntries)     _setEntryAlpha(e, _refAlphaFor(e.nuc?.strand_id) * beadVis(e.nuc) * _clusterAlphaFor(e.nuc) * _hiddenAlphaFor(e.nuc, e._copy ?? 0))
    for (const e of fluoroEntries)   _setEntryAlpha(e, _refAlphaFor(e.nuc?.strand_id) * beadVis(e.nuc) * _clusterAlphaFor(e.nuc) * _hiddenAlphaFor(e.nuc, e._copy ?? 0))
    for (const e of coneEntries) {
      const vis = e.isCrossHelix ? 1 : beadVis(e.fromNuc)
      _setEntryAlpha(e, _refAlphaFor(e.strandId) * vis * _clusterAlphaFor(e.fromNuc) * _hiddenAlphaFor(e.fromNuc))
    }
    for (const dom of _domainCylData)   _setCylAlpha(iHelixCylinders, dom.cylIdx, _cylFactor(dom))
    for (const dom of _overhangCylData) _setCylAlpha(_ovhgCylMesh(dom), dom.cylIdx, _cylFactor(dom))
    // ds-linker bridge cylinder: keyed on its own __lnk__ bridge helix span, so it
    // needs its own column test rather than _cylRepVis's helixId one.
    const bridgeVis = (br) => {
      for (let bp = br.bp_lo; bp <= br.bp_hi; bp++) {
        if (_effCol(br.bridgeHelixId, bp) !== 'cylinders') return 0
      }
      return 1
    }
    for (const br of _bridgeCylData) _setCylAlpha(iLinkerBridgeCylinders, br.cylIdx, bridgeVis(br))
    // Curved proxies + linker binding cylinders (2026-08-01). Binding cylinders are
    // still not column-driven — only the bridge was ever requested ("dsDNA only for
    // now") — so _cylRepVis contributes nothing new for them beyond the guard.
    _refreshCurvedAlpha()
    // Make every driven mesh renderable; alpha selects what actually shows.
    iSpheres.visible = iCubes.visible = iCones.visible = iSlabs.visible = iSlabConnectors.visible = iFluoros.visible = true
    iHelixCylinders.visible = iOverhangCylinders.visible = iOverhangFullCylinders.visible = iLinkerBridgeCylinders.visible = true
    // Re-gate axis lines per-region: only full-rendered columns keep their axis.
    if (_axisArrowsVisible) _applyShaftModeVisibility(_currentShaftMode)
  }

  // ── Public interface ───────────────────────────────────────────────────────

  return {
    root,
    backboneEntries,
    coneEntries,
    slabEntries,

    /** Source instance snapshots for a rigid, single-residue transform preview. */
    residueTransformInfo(target) {
      if (!target || target.helix_id === '__xb__') return null
      const key = `${target.helix_id}:${target.bp_index}:${target.direction}:${target.copy ?? 0}`
      const bead = _copyKeyToEntry.get(key)
      const slab = slabEntries.find(s => s.nuc === bead?.nuc && (s._copy ?? 0) === (target.copy ?? 0))
      if (!bead) return null
      const beadMatrix = new THREE.Matrix4()
      bead.instMesh.getMatrixAt(bead.id, beadMatrix)
      const slabMatrix = slab ? new THREE.Matrix4() : null
      if (slab) slab.instMesh.getMatrixAt(slab.id, slabMatrix)
      return {
        bead, slab, beadMatrix, slabMatrix,
        beadPosition: bead.pos.clone(),
        centroid: new THREE.Vector3().setFromMatrixPosition(beadMatrix),
      }
    },

    /** Apply one world delta to the bead and its slab as a single rigid element. */
    applyResidueTransformMatrix(info, matrix) {
      if (!info?.bead) return false
      info.bead.instMesh.setMatrixAt(info.bead.id, matrix.clone().multiply(info.beadMatrix))
      info.bead.instMesh.instanceMatrix.needsUpdate = true
      info.bead.pos.copy(info.beadPosition).applyMatrix4(matrix)
      const n = info.bead.nuc
      const beadKey = `${n.helix_id}:${n.bp_index}:${n.direction}`
      for (const cone of _keyToCones.get(beadKey) ?? []) _recomposeCone(cone)
      iCones.instanceMatrix.needsUpdate = true
      if (info.slab && info.slabMatrix) {
        info.slab.instMesh.setMatrixAt(info.slab.id, matrix.clone().multiply(info.slabMatrix))
        info.slab.instMesh.instanceMatrix.needsUpdate = true
      }
      _refreshSlabConnectors()
      return true
    },

    // Per-domain cylinder data — exposed so the shared assembly renderer's
    // sharedLodMid can build a per-helix colour texture from the
    // instance colors written into iHelixCylinders by applyColoring().
    // Each entry: { helixId, strandId, t0, t1, cylIdx, arrow, defaultColor, ... }
    domainCylData:   _domainCylData,
    overhangCylData: _overhangCylData,

    // Instance update helpers — used by selection_manager.js and design_renderer.js
    setEntryColor:  _setInstColor,
    setBeadScale:   _setBeadScale,
    setConeXZScale: _setConeXZScale,

    /** Mark which strand IDs are reference geometry (rendered translucent). */
    setReferenceStrands(idSet) {
      _refIdSet = idSet instanceof Set ? idSet : new Set(idSet)
      _applyAlphaChannel()
    },
    /** Hide (alpha→0, fragment-discarded) or show reference geometry. */
    setReferenceHidden(hidden) {
      _refHidden = !!hidden
      _applyAlphaChannel()
      if (_repActive) _applyRepOverrides()   // re-multiply override visibility over ref alpha
    },

    /**
     * Per-cluster opacity. `map` is nucKey → alpha (0..1), keyed exactly like
     * setHiddenNucs ('h:<helix_id>' / 'd:<strand_id>:<domain_index>'); keys absent
     * from the map are opaque. Built by scene/cluster_entries.js::clusterAlphaKeys.
     *
     * Multiplies with reference-ghost alpha and mixed-representation visibility on
     * the shared instanceAlpha channel — it does not replace them. design_renderer
     * re-pushes this after every rebuild, since a rebuild makes fresh meshes.
     *
     * Covers the design-view meshes (beads/cones/slabs/fluoros + the straight
     * cylinders). Curved/deformed tubes, impostor beads, crossover extra-base
     * meshes and the hull prism are NOT covered — same gap list as mixed
     * representation, see .claude/rules/rendering.md.
     */
    setClusterAlphas(map) {
      const next = map instanceof Map ? map : new Map(map ?? [])
      if (!next.size && !_clusterAlphaKeys.size) return   // nothing to do, install nothing
      _clusterAlphaKeys = next
      if (next.size) _ensureAlphaInstalled()
      if (_repActive) _applyRepOverrides(); else _applyAlphaChannel()
    },

    /**
     * Apply per-region representation overrides (mixed representation).
     * @param {Map<string,string>} columnRep  "helixId:bp" -> 'full' | 'cylinders'
     *   (overridden duplex columns only; both strands at a column share the rep).
     * Pass an empty map (or no args) to clear and hand visibility back to the LOD.
     */
    applyRepOverrides(columnRep) {
      _repColumnRep = columnRep instanceof Map ? columnRep : new Map()
      _repActive    = _repColumnRep.size > 0
      _applyRepOverrides()
      return { active: _repActive }
    },

    /** Three-state axis line visibility:
     *    'deformed' — curved shaft visible (TubeGeometry at deformed samples);
     *                 per-domain segments visible (at deformed positions).
     *    'straight' — straight cylinder placeholder visible (at the
     *                 lerped/final straight axis); per-domain segments visible.
     *    'hidden'   — everything axis-related hidden. Used during the
     *                 activate/deactivate lerp so the axis lines don't sweep
     *                 into position — they just disappear, beads animate,
     *                 then the destination axis appears at the end.
     *
     *  Uses `mesh.visible` (hard render skip) rather than opacity. The mode
     *  is cached on `_currentShaftMode` so setAxisArrowsVisible(true) can
     *  re-apply the correct mutually-exclusive visibility instead of turning
     *  both shaft and straightShaft on simultaneously. */
    setAxisShaftMode(mode) {
      _currentShaftMode = mode
      if (!_axisArrowsVisible) return  // cadnano has the global toggle off — defer.
      _applyShaftModeVisibility(mode)
    },

    /** Set the global bead display radius (nm).  Resets all backbone bead scales. */
    setBeadRadius(r) {
      _beadScale = r / BEAD_RADIUS
      for (const entry of backboneEntries) _setBeadScale(entry, _beadScale)
    },

    /** Set the base-pair slab PLATE THICKNESS in nm — `slabParams.width`, the
     *  smallest slab dimension (default 0.06); the in-plane footprint is left
     *  alone.  Mutates the live `slabParams` so every inline slab compose in this
     *  file (deform lerp, position lerp, cluster transform, MD/sim updates) picks
     *  the new value up on its next pass, then restretches the slabs that exist
     *  right now IN PLACE — keeping whatever position/orientation/in-plane size
     *  the active display overlay gave them, rather than snapping back to design
     *  geometry. */
    setSlabThickness(nm) {
      slabParams.width = nm
      for (const entry of slabEntries) {
        iSlabs.getMatrixAt(entry.id, _tMatrix)
        _tMatrix.decompose(_tPos, _slabRescaleQ, _tScale)
        // Zero scale = a hidden slab (fade-out / hide toggle) — leave it hidden.
        if (_tScale.lengthSq() < 1e-12) continue
        _tScale.y = nm
        _tMatrix.compose(_tPos, _slabRescaleQ, _tScale)
        iSlabs.setMatrixAt(entry.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()
    },

    /** Set the domain cylinder display radius (nm).  Rebuilds all cylinder matrices. */
    setCylinderRadius(r) {
      _cylRadiusScale = r / 1.125
      for (const dom of _domainCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iHelixCylinders.instanceMatrix.needsUpdate = true
      _refreshCylGlow()
      for (const dom of _overhangCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        _ovhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
      }
      _markOvhgCylMatricesDirty()

      // Curved-helix proxy matrices (straight proxy follows the same formula).
      for (const dom of _curvedDomainCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
      for (const dom of _curvedOvhgCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        _curvedOvhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
      }
      _markCurvedOvhgCylMatricesDirty()

      // Rebuild curved tube geometries at new radius.
      for (const mesh of [..._curvedCylGroup.children, ..._curvedOvhgGroup.children]) {
        const { helixId, t0, t1, isOvhg } = mesh.userData
        const arrow = _arrowByHelixId.get(helixId)
        if (!arrow?.samples) continue
        const openAngle = (isOvhg && !mesh.userData.fullCylinder) ? Math.PI : 2 * Math.PI
        const fullCurve = new THREE.CatmullRomCurve3(arrow.samples.map(s => new THREE.Vector3(s[0], s[1], s[2])))
        const nSamples = arrow.samples.length
        const nPts = Math.max(4, Math.ceil(nSamples * (t1 - t0)) + 2)
        const pts  = []
        for (let i = 0; i <= nPts; i++) pts.push(fullCurve.getPoint(t0 + (i / nPts) * (t1 - t0)))
        const segCurve  = new THREE.CatmullRomCurve3(pts)
        const radialSeg = openAngle < 2 * Math.PI ? 4 : 8
        mesh.geometry.dispose()
        mesh.geometry = new THREE.TubeGeometry(segCurve, Math.max(2, nPts), r, radialSeg, false)
      }
    },

    /** Palette colors assigned at build time, before any custom/group overrides.
     *  Used by design_renderer to revert strands to palette when removed from a group. */
    getPaletteColors() { return stapleColorMap },

    /**
     * In-place nucleotide metadata patch (Fix B part 2).
     *
     * Updates strand_id, strand_type, is_five_prime, is_three_prime, domain_index
     * for the supplied nucleotides without tearing down and rebuilding the whole scene.
     * New strand IDs from nicks are assigned the next palette slot.
     * After updating metadata, callers should invoke setMode() to re-apply mode colours.
     *
     * @param {Array}  partialNucs   — nucleotide objects from the partial geometry response
     * @param {object} customColors  — strandId → hex override (store.strandColors)
     * @param {Set}    loopSet       — strand IDs with circular topology
     */
    patchNucleotides(partialNucs, customColors, loopSet) {
      // Extend palette for any new strand IDs introduced by the operation.
      let paletteIdx = stapleColorMap.size
      for (const nuc of partialNucs) {
        if (nuc.strand_id && nuc.strand_type !== 'scaffold' && !stapleColorMap.has(nuc.strand_id)) {
          stapleColorMap.set(nuc.strand_id, STAPLE_PALETTE[paletteIdx % STAPLE_PALETTE.length])
          paletteIdx++
        }
      }
      // Update each entry's nuc metadata and defaultColor.
      for (const nuc of partialNucs) {
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const entry = _keyToEntry.get(key)
        if (!entry) continue
        entry.nuc.strand_id    = nuc.strand_id
        entry.nuc.strand_type  = nuc.strand_type
        entry.nuc.is_five_prime  = nuc.is_five_prime
        entry.nuc.is_three_prime = nuc.is_three_prime
        entry.nuc.domain_index   = nuc.domain_index
        const color = nucColor(nuc, stapleColorMap, customColors, loopSet)
        entry.defaultColor = color
        _setInstColor(entry, color)
      }
      // Also update cone entries that cross the changed helices (strand-ID changed).
      const helixSet = new Set(partialNucs.map(n => n.helix_id))
      for (const cone of coneEntries) {
        const fn = cone.fromNuc, tn = cone.toNuc
        if (!fn || !helixSet.has(fn.helix_id)) continue
        // Re-derive cone color from the (now-updated) fromNuc strand
        const color = nucColor(fn, stapleColorMap, customColors, loopSet)
        cone.defaultColor = color
        _setInstColor(cone, color)
      }
    },

    setStrandColor(strandId, hexColor) {
      for (const entry of backboneEntries) {
        if (entry.nuc.strand_id === strandId) {
          _setInstColor(entry, hexColor)
          entry.defaultColor = hexColor
        }
      }
      for (const entry of slabEntries) {
        if (entry.nuc.strand_id === strandId) {
          _setInstColor(entry, hexColor)
          entry.defaultColor = hexColor
        }
      }
      for (const entry of coneEntries) {
        if (entry.strandId === strandId) {
          _setInstColor(entry, hexColor)
          entry.defaultColor = hexColor
        }
      }
      let cylUpdated = false
      for (const dom of _domainCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          cylUpdated = true
        }
      }
      if (cylUpdated && iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true
      let ovhgUpdated = false
      for (const dom of _overhangCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          _ovhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          ovhgUpdated = true
        }
      }
      if (ovhgUpdated) _markOvhgCylColorsDirty()
      // Curved tube meshes.
      for (const mesh of _curvedCylGroup.children) {
        if (mesh.userData.strandId === strandId) mesh.material.color.setHex(hexColor)
      }
      let curvedUpdated = false
      for (const dom of _curvedDomainCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          curvedUpdated = true
        }
      }
      if (curvedUpdated && iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedOvhgGroup.children) {
        if (mesh.userData.strandId === strandId) mesh.material.color.setHex(hexColor)
      }
      let curvedOvhgUpd = false
      for (const dom of _curvedOvhgCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          _curvedOvhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          curvedOvhgUpd = true
        }
      }
      if (curvedOvhgUpd) _markCurvedOvhgCylColorsDirty()
    },

    /**
     * Apply a global coloring mode across backbone, slab, cone and cylinder
     * instances.  Re-derives every entry's defaultColor from scratch so that
     * subsequent dim/highlight restores land on the mode-correct colour.
     *
     *   'strand'  — palette/group/custom per strand (the build-time default)
     *   'base'    — A/T/G/C per nucleotide; nucs without a letter fall back to
     *               their strand colour.  Cylinders fall back entirely.
     *   'cluster' — palette per cluster_transforms entry; nucs/cylinders not
     *               covered by any cluster fall back to their strand colour.
     *
     * @param {'strand'|'base'|'cluster'} mode
     * @param {object} design       — current Design (for sequences + clusters)
     * @param {object} effectiveCols — strand_id → hex (strandColors+groups merged)
     * @param {Set<string>} loopSet — circular strand IDs (red overlay in strand)
     */
    applyColoring(mode, design, effectiveCols, loopIds) {
      const m = mode || 'strand'
      const eff = effectiveCols || customColors
      const loop = loopIds instanceof Set ? loopIds : new Set(loopIds ?? [])

      let perNuc = () => null
      let clusterColorFn = null

      if (m === 'base') {
        const allNucs = backboneEntries.map(e => e.nuc).filter(Boolean)
        const nucLetter = buildNucLetterMap(design, allNucs)
        perNuc = (nuc) => {
          const ch = nucLetter.get(nuc)
          return ch ? BASE_COLORS[ch] : null
        }
      } else if (m === 'cluster') {
        // A cluster's user-set colour overrides its auto palette slot; unstyled
        // clusters keep STAPLE_PALETTE[index % 12] exactly as before.
        clusterColorFn = buildClusterColorLookup(design)
        perNuc = (nuc) => clusterColorFn(nuc) ?? null
      } else if (m === 'overhang-only') {
        // Overhang nucs return null → fall through to strand color.
        // Everything else gets dim gray.
        perNuc = (nuc) => (nuc?.overhang_id != null ? null : C.dim_gray)
      }

      const strandHexFor = (sid) => {
        if (sid == null) return C.unassigned
        if (loop.has(sid)) return C.highlight_red
        if (eff[sid] != null) return eff[sid]
        return stapleColorMap.get(sid) ?? C.unassigned
      }
      const strandBeadColor  = (nuc) => {
        if (!nuc?.strand_id) return C.unassigned
        if (nuc.strand_type === 'scaffold') return C.scaffold_backbone
        return strandHexFor(nuc.strand_id)
      }
      const strandSlabColor2 = (nuc) => {
        if (!nuc?.strand_id) return C.unassigned
        if (nuc.strand_type === 'scaffold') return C.scaffold_slab
        return strandHexFor(nuc.strand_id)
      }
      const strandArrowCol2  = (nuc, sid) => {
        const sId = nuc?.strand_id ?? sid
        if (!sId) return C.unassigned
        if (nuc?.strand_type === 'scaffold') return C.scaffold_arrow
        return strandHexFor(sId)
      }

      for (const entry of backboneEntries) {
        const c = perNuc(entry.nuc) ?? strandBeadColor(entry.nuc)
        entry.defaultColor = c
        _setInstColor(entry, c)
      }
      for (const entry of slabEntries) {
        const c = perNuc(entry.nuc) ?? strandSlabColor2(entry.nuc)
        entry.defaultColor = c
        _setInstColor(entry, c)
      }
      for (const entry of coneEntries) {
        const fn = entry.fromNuc
        const c = (fn ? perNuc(fn) : null) ?? strandArrowCol2(fn, entry.strandId)
        entry.defaultColor = c
        _setInstColor(entry, c)
      }

      // Cylinders: skip 'base' (cylinders span multiple bps).  In 'cluster'
      // mode use the cluster lookup keyed by helix+domain; otherwise fall back
      // to the (effective) strand colour.  In 'overhang-only' mode regular
      // cylinders go dim gray; overhang cylinders keep their strand colour.
      const cylColorFor = (dom) => {
        if (clusterColorFn) {
          const c = clusterColorFn({
            helix_id:    dom.helixId,
            strand_id:   dom.strandId,
            domain_index: dom.domainIndex ?? 0,
          })
          if (c != null) return c
        }
        return strandHexFor(dom.strandId)
      }
      const isOvhgOnly = (m === 'overhang-only')

      for (const dom of _domainCylData) {
        const c = isOvhgOnly ? C.dim_gray : cylColorFor(dom)
        dom.defaultColor = c
        iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true

      for (const dom of _overhangCylData) {
        const c = cylColorFor(dom)
        dom.defaultColor = c
        _ovhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      _markOvhgCylColorsDirty()

      for (const mesh of _curvedCylGroup.children) {
        const ud = mesh.userData ?? {}
        const c = isOvhgOnly ? C.dim_gray
          : cylColorFor({ helixId: ud.helixId, strandId: ud.strandId, domainIndex: 0 })
        mesh.material.color.setHex(c)
        ud.defaultColor = c
      }
      for (const dom of _curvedDomainCylData) {
        const c = isOvhgOnly ? C.dim_gray : cylColorFor(dom)
        dom.defaultColor = c
        iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true

      for (const mesh of _curvedOvhgGroup.children) {
        const ud = mesh.userData ?? {}
        const c = cylColorFor({ helixId: ud.helixId, strandId: ud.strandId, domainIndex: 0 })
        mesh.material.color.setHex(c)
        ud.defaultColor = c
      }
      for (const dom of _curvedOvhgCylData) {
        const c = cylColorFor(dom)
        dom.defaultColor = c
        _curvedOvhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      _markCurvedOvhgCylColorsDirty()
    },

    /** Look up a backbone entry by "helix_id:bp_index:direction" key (for Fix B part 2). */
    lookupEntry(key) { return _keyToEntry.get(key) ?? null },

    getCylinderMesh() { return iHelixCylinders },
    getOverhangCylinderMesh() { return iOverhangCylinders },
    getOverhangFullCylinderMesh() { return iOverhangFullCylinders },
    getCylinderDomainData() { return _domainCylData },
    getOverhangCylinderDomainData() { return _overhangCylData },

    /** Return the _domainCylData entry for a given InstancedMesh instanceId. */
    getCylinderDomainAt(instanceId) { return _domainCylData[instanceId] ?? null },
    /** Return the _overhangCylData entry for a given InstancedMesh instanceId. */
    getOverhangCylinderDomainAt(instanceId) { return _overhangCylData.find(d => !d.fullCylinder && d.cylIdx === instanceId) ?? null },
    getOverhangFullCylinderDomainAt(instanceId) { return _overhangCylData.find(d => d.fullCylinder && d.cylIdx === instanceId) ?? null },
    /** The ds-linker bridge cylinder InstancedMesh (full cylinder per __lnk__ helix). */
    getLinkerBridgeCylinderMesh() { return iLinkerBridgeCylinders },
    /** Return {bridgeHelixId, strandId} for a bridge cylinder instanceId. */
    getLinkerBridgeCylinderAt(instanceId) { return _bridgeCylData[instanceId] ?? null },

    /** Additive glow outline on the cylinders of the given domains (selection feedback).
     *  domainRefs: [{strandId, domainIndex}]. Straight + overhang cylinders only. */
    glowCylinderDomains(domainRefs) {
      // Only glow domains that are ACTUALLY cylinder-rendered (skip bead-rendered
      // ones — they have a cyl record but the solid cylinder is hidden).
      _cylGlowRefs = (Array.isArray(domainRefs) ? domainRefs : [])
        .filter(r => _isDomainCyl(r.strandId, r.domainIndex))
      const { straight, overhang, overhangFull } = _refsToCylIdxSets(_cylGlowRefs)
      _writeCylGlow(iHelixCylGlow, iHelixCylinders, _domainCylData, straight)
      _writeCylGlow(iOverhangCylGlow, iOverhangCylinders, _overhangCylData.filter(d => !d.fullCylinder), overhang)
      _writeCylGlow(iOverhangFullCylGlow, iOverhangFullCylinders, _overhangCylData.filter(d => d.fullCylinder), overhangFull)
    },
    clearCylinderDomainGlow() {
      _cylGlowRefs = []
      iHelixCylGlow.count = 0; iOverhangCylGlow.count = 0; iOverhangFullCylGlow.count = 0
      iHelixCylGlow.instanceMatrix.needsUpdate = true
      iOverhangCylGlow.instanceMatrix.needsUpdate = true
      iOverhangFullCylGlow.instanceMatrix.needsUpdate = true
    },
    refreshCylinderDomainGlow() { _refreshCylGlow() },

    /** Effective rep at a duplex column right now: override wins, else the global LOD. */
    columnRepAt(helixId, bp) {
      const baseCyl = _detailLevel === 2
      return _repColumnRep.get(`${helixId}:${bp}`) ?? (baseCyl ? 'cylinders' : 'full')
    },
    /** Is the duplex column (helix_id, bp) rendered as a cylinder right now? */
    isColumnCylinder(helixId, bp) {
      const baseCyl = _detailLevel === 2
      return (_repColumnRep.get(`${helixId}:${bp}`) ?? (baseCyl ? 'cylinders' : 'full')) === 'cylinders'
    },
    /** Is this domain fully cylinder-rendered? (every column resolves to 'cylinders') */
    isDomainCylinder(strandId, domainIndex) { return _isDomainCyl(strandId, domainIndex) },

    /**
     * Highlight all cylinders whose strandId is in strandIds (string or array/Set);
     * all other cylinders are left at their defaultColor.
     */
    highlightCylinderStrands(strandIds) {
      const idSet = strandIds instanceof Set ? strandIds : new Set(Array.isArray(strandIds) ? strandIds : [strandIds])
      for (const dom of _domainCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true
      for (const dom of _overhangCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        _ovhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      _markOvhgCylColorsDirty()
      for (const mesh of _curvedCylGroup.children) {
        const c = idSet.has(mesh.userData.strandId) ? 0xffffff : mesh.material.color.getHex()
        mesh.material.color.setHex(c)
      }
      for (const dom of _curvedDomainCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedOvhgGroup.children) {
        const c = idSet.has(mesh.userData.strandId) ? 0xffffff : mesh.material.color.getHex()
        mesh.material.color.setHex(c)
      }
      for (const dom of _curvedOvhgCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        _curvedOvhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      _markCurvedOvhgCylColorsDirty()
    },

    /** Restore all cylinders to their default colors. */
    clearCylinderHighlight() {
      for (const dom of _domainCylData) {
        iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      if (iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true
      for (const dom of _overhangCylData) {
        _ovhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      _markOvhgCylColorsDirty()
      for (const mesh of _curvedCylGroup.children) mesh.material.color.setHex(mesh.userData.defaultColor ?? mesh.material.color.getHex())
      for (const dom of _curvedDomainCylData) {
        iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      if (iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedOvhgGroup.children) mesh.material.color.setHex(mesh.userData.defaultColor ?? mesh.material.color.getHex())
      for (const dom of _curvedOvhgCylData) {
        _curvedOvhgCylMesh(dom).setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      _markCurvedOvhgCylColorsDirty()
    },

    /**
     * Show or hide all staple (non-scaffold) geometry.
     * Uses scale=0 to hide instances without rebuilding.
     */
    setStapleVisibility(visible) {
      for (const entry of backboneEntries) {
        if (entry.nuc.strand_type === 'scaffold') continue
        _setBeadScale(entry, visible ? 1.0 : 0)
      }
      for (const entry of coneEntries) {
        if (entry.strandId === null) continue
        const isScaffold = backboneEntries.find(e => e.nuc.strand_id === entry.strandId)?.nuc?.strand_type === 'scaffold'
        if (isScaffold) continue
        const r = (!visible || entry.isCrossHelix) ? 0 : entry.coneRadius
        _setConeXZScale(entry, r)
      }
      for (const entry of slabEntries) {
        if (entry.nuc.strand_type === 'scaffold') continue
        const s = slabParams
        _slabAxisDir.set(...entry.nuc.axis_tangent).normalize()
        const center = _slabCenterAt(entry, _slabAxisDir, null, null, _slabCenterD)
        if (visible) {
          _tMatrix.compose(center, entry.quat, _tScale.set(s.length, s.width, s.thickness))
        } else {
          _tMatrix.compose(center, entry.quat, _tScale.set(0, 0, 0))
        }
        iSlabs.setMatrixAt(entry.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()
    },

    /**
     * Isolate a single staple strand: dim all other non-scaffold instances.
     * Pass null to un-isolate and restore default colours.
     */
    setIsolatedStrand(strandId) {
      if (strandId === null) {
        // Restore defaults
        for (const entry of backboneEntries) {
          if (entry.nuc.strand_type !== 'scaffold') _setInstColor(entry, entry.defaultColor)
        }
        for (const entry of coneEntries) {
          if (backboneEntries.find(e => e.nuc.strand_id === entry.strandId)?.nuc?.strand_type !== 'scaffold') {
            _setInstColor(entry, entry.defaultColor)
          }
        }
        for (const entry of slabEntries) {
          if (entry.nuc.strand_type !== 'scaffold') _setInstColor(entry, entry.defaultColor)
        }
      } else {
        const DIM = C.dim
        for (const entry of backboneEntries) {
          if (entry.nuc.strand_type === 'scaffold') continue
          _setInstColor(entry, entry.nuc.strand_id === strandId ? entry.defaultColor : DIM)
        }
        for (const entry of coneEntries) {
          const isScaff = backboneEntries.find(e => e.nuc.strand_id === entry.strandId)?.nuc?.strand_type === 'scaffold'
          if (isScaff) continue
          _setInstColor(entry, entry.strandId === strandId ? entry.defaultColor : DIM)
        }
        for (const entry of slabEntries) {
          if (entry.nuc.strand_type === 'scaffold') continue
          _setInstColor(entry, entry.nuc.strand_id === strandId ? entry.defaultColor : DIM)
        }
      }
    },

    setMode(mode) {
      switch (mode) {
        case 'normal': modeNormal(); break
        case 'V1.1':  modeV11();    break
        case 'V1.2':  modeV12();    break
        case 'V1.3':  modeV13();    break
        case 'V1.4':  modeV14();    break
        case 'V2.1':  modeV21();    break
        case 'V2.2':  modeV22();    break
        case 'V2.3':  modeV23();    break
        case 'V2.4':  modeV24();    break
      }
    },

    /**
     * Thicken/brighten axis arrows for the bend/twist deformation tool.
     * active=true  → fat cyan shafts (easy to click near)
     * active=false → restore thin grey shafts
     */
    setDeformMode(active) {
      const scaleXZ = active ? (0.18 / AXIS_SHAFT_R) : 1.0   // 0.18/0.05 = 3.6×
      const color   = active ? 0x88ccff : C.axis
      for (const arrow of axisArrows) {
        if (arrow.isCurved) {
          const m = arrow.shaft?.material
          if (m) { m.color.setHex(color); m.opacity = 1.0; m.transparent = false }
        } else {
          for (const seg of arrow.segments ?? []) {
            seg.mesh.scale.set(scaleXZ, 1, scaleXZ)
            const m = seg.mesh.material
            if (m) { m.color.setHex(color); m.opacity = 1.0; m.transparent = false }
          }
        }
      }
    },

    getDistLabelInfo() { return distLabelInfo },

    revertToGeometry,
    applyUnfoldOffsets,

    /**
     * Returns a snapshot of every backbone bead's current rendered position,
     * keyed by "helix_id:bp_index:direction".  Used by cadnano_view to capture
     * the unfold-layout positions before starting the cadnano lerp animation.
     * @returns {Map<string, THREE.Vector3>}
     */
    snapshotPositions() {
      const map = new Map()
      for (const entry of backboneEntries) {
        if (entry.nuc.helix_id.startsWith('__ext_')) continue
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        map.set(key, entry.pos.clone())
      }
      return map
    },

    /**
     * Lerp bead positions from unfold-layout positions toward cadnano flat
     * two-track positions.  Called by cadnano_view on each animation frame.
     *
     * @param {Map<string, THREE.Vector3>} cadnanoPosMap
     *   Target positions keyed by "helix_id:bp_index:direction".
     * @param {number} t  Lerp factor [0, 1]; 0 = unfold layout, 1 = cadnano flat.
     * @param {Map<string, THREE.Vector3>} unfoldPosMap
     *   Current positions at t=0 (unfold layout), same key format.
     *   Typically the cadnano_view's snapshot of entry.pos at unfold-activation time.
     */
    applyCadnanoPositions(cadnanoPosMap, t, unfoldPosMap) {
      // 1. Backbone beads.
      for (const entry of backboneEntries) {
        if (entry.nuc.helix_id.startsWith('__ext_')) continue
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const cp = cadnanoPosMap.get(key)
        const up = unfoldPosMap.get(key)
        if (!cp || !up) continue

        entry.pos.set(
          up.x + (cp.x - up.x) * t,
          up.y + (cp.y - up.y) * t,
          up.z + (cp.z - up.z) * t,
        )
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — cross-helix cones remain hidden (same as unfold mode).
      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue

        const isCrossHelix = cone.fromNuc.helix_id !== cone.toNuc.helix_id
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h

        const r = isCrossHelix ? 0 : cone.coneRadius
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — hide in cadnano mode (beads are flat, orientation meaningless).
      for (const slab of slabEntries) {
        _tMatrix.compose(_tPos.set(0, 0, 0), ID_QUAT, _tScale.set(0, 0, 0))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()
    },

    /**
     * Apply mrDNA-relaxed backbone positions as a scene overlay (moves the
     * instanced beads/cones/slabs in place; pass null to revert to geometry).
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    /**
     * Surgical per-bead override for a SMALL set of nucleotides — moves only
     * the named beads + their slabs, with no console logging and no full-scene
     * sweep. Safe to call every animation frame (unlike applyFemPositions,
     * which logs + rewrites every slab/cone). Used by the overhang/linker
     * unzip animation to splay just the overhang beads. Display-only.
     *
     * @param {Array<{helix_id, bp_index, direction, backbone_position:[x,y,z],
     *                nx?, ny?, nz?}>} updates  absolute positions; optional base
     *                normal (nx,ny,nz) reorients the slab, else slab keeps its
     *                build-time orientation and just follows the bead.
     */
    setBeadOverrides(updates) {
      // Display-only bead motion still uses the canonical slab contact solver below;
      // it does not invent a second slab offset or orientation convention.
      if (!updates?.length) return
      let touchedBead = false, touchedSlab = false
      for (let i = 0; i < updates.length; i++) {
        const u = updates[i]
        const key = `${u.helix_id}:${u.bp_index}:${u.direction}`
        const entry = _keyToEntry.get(key)
        if (entry) {
          const p = u.backbone_position
          entry.pos.set(p[0], p[1], p[2])
          _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
          entry.instMesh.setMatrixAt(entry.id, _tMatrix)
          touchedBead = true
        }
        const slab = _keyToSlab.get(key)
        if (slab) {
          if (entry) slab.bbPos.copy(entry.pos)
          let q = slab.quat, bn = slab.bnDir
          if (u.nx !== undefined) {
            _slabBnS.set(u.nx, u.ny, u.nz)
            _slabAxisDir.set(...slab.nuc.axis_tangent)
            _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
            _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
            _slabQuatS.setFromRotationMatrix(_slabBasis)
            q = _slabQuatS; bn = _slabBnS
          }
          _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
          const center = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
          _tMatrix.compose(center, q, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
          slab.instMesh.setMatrixAt(slab.id, _tMatrix)
          touchedSlab = true
        }
      }
      if (touchedBead) {
        iSpheres.instanceMatrix.needsUpdate = true; iCubes.instanceMatrix.needsUpdate = true
        // Recompose connector cones whose endpoints moved (dedup shared cones).
        const seenCones = new Set()
        for (let i = 0; i < updates.length; i++) {
          const u = updates[i]
          const cones = _keyToCones.get(`${u.helix_id}:${u.bp_index}:${u.direction}`)
          if (!cones) continue
          for (const cone of cones) {
            if (seenCones.has(cone.id)) continue
            seenCones.add(cone.id); _recomposeCone(cone)
          }
        }
        if (seenCones.size) iCones.instanceMatrix.needsUpdate = true
      }
      if (touchedSlab) {
        iSlabs.instanceMatrix.needsUpdate = true
        _refreshSlabConnectors()
      }
    },

    applyFemPositions(updates, amp = 1.0) {
      // DELETE PENDING REVIEW (non-authoritative geometry): FEM overlays carry
      // partial nucleotide coordinates and reconstruct the remaining slab pose.
      if (!updates) { revertToGeometry(); return }

      // 1. Backbone beads — optionally amplify displacement from equilibrium.
      // Build helix-endpoint sample map: first and last bp_index per helix, up to 3 helices.
      const _helixSamples = new Map()   // helix_id → {first, last} entries for logging
      const _samples = []
      let _maxDelta = 0

      for (let _i = 0; _i < updates.length; _i++) {
        const upd   = updates[_i]
        // Address the specific loop copy when the update carries one (copy defaults to
        // 0 → the plain bead, so non-loop designs and copy-less updates are unchanged).
        const _bk = `${upd.helix_id}:${upd.bp_index}:${upd.direction}`
        const entry = _copyKeyToEntry.get(`${_bk}:${upd.copy ?? 0}`) ?? _keyToEntry.get(_bk)
        if (!entry) continue
        const bp = upd.backbone_position
        const eq = entry.nuc.backbone_position
        if (amp === 1.0) {
          entry.pos.set(bp[0], bp[1], bp[2])
        } else {
          entry.pos.set(
            eq[0] + amp * (bp[0] - eq[0]),
            eq[1] + amp * (bp[1] - eq[1]),
            eq[2] + amp * (bp[2] - eq[2]),
          )
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)

        const dx = bp[0]-eq[0], dy = bp[1]-eq[1], dz = bp[2]-eq[2]
        const mag = Math.hypot(dx, dy, dz)
        if (mag > _maxDelta) _maxDelta = mag

        // Track first/last bead of each helix for up to 3 helices
        if (_helixSamples.size < 3 || _helixSamples.has(upd.helix_id)) {
          let hs = _helixSamples.get(upd.helix_id)
          if (!hs) { hs = { first: null, last: null }; _helixSamples.set(upd.helix_id, hs) }
          const snap = { hid: upd.helix_id, bp: upd.bp_index, dir: upd.direction.slice(0,3),
                         mdx: bp[0], mdy: bp[1], mdz: bp[2],
                         eqx: eq[0], eqy: eq[1], eqz: eq[2],
                         dx, dy, dz, mag }
          if (!hs.first) hs.first = snap
          hs.last = snap
        }
      }

      for (const [hid, hs] of _helixSamples) {
        const fmt = (s) => `bp${s.bp}:${s.dir}  md=(${s.mdx.toFixed(3)},${s.mdy.toFixed(3)},${s.mdz.toFixed(3)})  eq=(${s.eqx.toFixed(3)},${s.eqy.toFixed(3)},${s.eqz.toFixed(3)})  Δ=(${s.dx.toFixed(3)},${s.dy.toFixed(3)},${s.dz.toFixed(3)}) |Δ|=${s.mag.toFixed(3)} nm`
        _samples.push(`  ${hid}  ${fmt(hs.first)}`)
        if (hs.last !== hs.first) _samples.push(`  ${hid}  ${fmt(hs.last)}`)
      }
      console.log(`[applyFem] ${new Date().toLocaleTimeString()} amp=${amp}× maxΔ=${_maxDelta.toFixed(3)} nm\n` + _samples.join('\n'))
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — derived from updated backbone positions.
      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(cone.coneRadius, h, cone.coneRadius))
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — recompute bead contact; update orientation when base normals are provided.
      // Base normals come from the P→C1' intra-residue vector computed on the backend.
      // Uses module-level scratch: _slabBnS (MD bnDir), _slabAxisDir (tanDir), _slabTanS
      // (tangential = tanDir×bnDir), _slabBasis, _slabQuatS.  No heap allocation per frame.
      const hasNormals = updates.length > 0 && updates[0].nx !== undefined
      let normalMap = null
      if (hasNormals) {
        normalMap = new Map()
        for (const upd of updates) {
          if (upd.nx !== undefined)
            normalMap.set(`${upd.helix_id}:${upd.bp_index}:${upd.direction}:${upd.copy ?? 0}`, upd)
        }
      }
      // The unified slab path treats base_position as authoritative. An MD/FEM frame
      // does not send that position, so derive its live value by the SAME displacement
      // already applied to the nucleotide bead. Before this map existed the beads moved
      // to the MD frame while slabs stayed at equilibrium, making Full visibly disagree
      // with the atomistic view of that exact frame.
      const liveBaseMap = new Map()
      for (const slab of slabEntries) {
        const n = slab.nuc
        const entry = _nucToEntry.get(n)
        if (!entry || !n.base_position) continue
        const key = `${n.helix_id}:${n.bp_index}:${n.direction}`
        const upd = normalMap?.get(`${key}:${entry._copy ?? 0}`)
        liveBaseMap.set(key, upd?.base_position
          ? new THREE.Vector3(...upd.base_position)
          : translatedBasePosition(
            _tPos.set(...n.base_position),
            _slabBaseS.set(...n.backbone_position),
            entry.pos,
            new THREE.Vector3(),
          ))
      }
      for (const slab of slabEntries) {
        const entry = _nucToEntry.get(slab.nuc)
        if (!entry) continue
        slab.bbPos.copy(entry.pos)
        if (normalMap) {
          const key = `${slab.nuc.helix_id}:${slab.nuc.bp_index}:${slab.nuc.direction}:${slab._copy ?? 0}`
          const upd = normalMap.get(key)
          if (upd) {
            _slabBnS.set(upd.nx, upd.ny, upd.nz)
            // Prefer the WOUND axis-tangent (CanDo FEM display supplies tx/ty/tz so the slab
            // frame follows the wound backbone); fall back to the design tangent (mrDNA/oxDNA
            // overlays send only nx/ny/nz).
            if (upd.tx !== undefined) _slabAxisDir.set(upd.tx, upd.ty, upd.tz)
            else _slabAxisDir.set(...slab.nuc.axis_tangent)
            _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()  // tangential
            _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
            _slabQuatS.setFromRotationMatrix(_slabBasis)
            const center = _slabCenterAt(
              slab, _slabAxisDir.normalize(), liveBaseMap, null, _slabCenterD,
            )
            _tMatrix.compose(center, _slabQuatS, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
          } else {
            _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
            const center = _slabCenterAt(
              slab, _slabAxisDir, liveBaseMap, null, _slabCenterD,
            )
            _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
          }
        } else {
          _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
          const center = _slabCenterAt(
            slab, _slabAxisDir, liveBaseMap, null, _slabCenterD,
          )
          _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        }
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()
    },

    /**
     * Recolour by a per-base scalar (the oxDNA flexibility map): backbone beads
     * AND their base-pair slabs AND direction cones all take the colour of their
     * nucleotide, so the whole representation reads as one rigid→flexible map.
     * `colorByKey` maps "helix_id:bp_index:direction" → hex int.  The current
     * colour of every recoloured instance is captured once (keyed by
     * mesh-uuid:instance-id) so clearScalarColors() restores the prior colours
     * exactly — including any live strand/group overrides — with no rebuild.
     */
    applyScalarColors(colorByKey) {
      if (!colorByKey) return
      const get = colorByKey instanceof Map
        ? (k) => colorByKey.get(k)
        : (k) => colorByKey[k]
      if (!_savedScalarColors) _savedScalarColors = new Map()
      const recolor = (mesh, id, hex) => {
        const tok = `${mesh.uuid}:${id}`
        if (!_savedScalarColors.has(tok) && mesh.instanceColor) {
          mesh.getColorAt(id, _scalarColorScratch)
          _savedScalarColors.set(tok, { mesh, id, hex: _scalarColorScratch.getHex() })
        }
        mesh.setColorAt(id, _tColor.setHex(hex))
      }
      // colorByKey is keyed "helix:bp:dir:copy" so each loop copy recolours its own
      // bead/slab/cone (copy defaults 0 for plain nucleotides).
      for (const [key, entry] of _copyKeyToEntry) {
        const hex = get(key)
        if (hex === undefined || hex === null) continue
        recolor(entry.instMesh, entry.id, hex)
      }
      for (const cone of coneEntries) {
        const n = cone.fromNuc
        const c = _nucToEntry.get(n)?._copy ?? 0
        const hex = get(`${n.helix_id}:${n.bp_index}:${n.direction}:${c}`)
        if (hex === undefined || hex === null) continue
        recolor(cone.instMesh, cone.id, hex)
      }
      for (const slab of slabEntries) {
        const n = slab.nuc
        const hex = get(`${n.helix_id}:${n.bp_index}:${n.direction}:${slab._copy ?? 0}`)
        if (hex === undefined || hex === null) continue
        recolor(slab.instMesh, slab.id, hex)
        recolor(slab.connectorMesh, slab.connectorId, hex)
      }
      _flagScalarColorMeshes()
    },

    /** Restore the colours captured before the scalar-colour overlay. */
    clearScalarColors() {
      if (!_savedScalarColors) return
      for (const { mesh, id, hex } of _savedScalarColors.values()) {
        mesh.setColorAt(id, _tColor.setHex(hex))
      }
      _flagScalarColorMeshes()
      _savedScalarColors = null
    },

    /**
     * Switch rendering detail level for LOD (Level of Detail).
     *   0 = Full         — all geometry visible
     *   1 = Beads-only   — slabs hidden (cheaper)
     *   2 = Cylinders    — one cylinder per helix, all bead geometry hidden
     *
     * Returns `{ needsRebuild: boolean }`. When the renderer was built with
     * a cheap LOD (e.g. 'cylinders') and the caller asks to upgrade to a
     * level whose meshes weren't populated, `needsRebuild === true` — the
     * assembly renderer must call invalidateInstance + rebuild to actually
     * see the new meshes. Visibility flips alone won't help when the
     * underlying InstancedMesh buffers were never filled.
     */
    setDetailLevel(level) {
      if (level === _detailLevel) return { needsRebuild: false }
      // Detect "level requires meshes we didn't build". Level 0 needs
      // every mesh; level 1 needs beads + cones + fluoros; level 2 only
      // needs cylinders.
      const needsBeads   = level <= 1
      const needsSlabs   = level === 0
      const needsCones   = level <= 1
      const needsFluoros = level <= 1
      const needsRebuild = (
        (needsBeads   && !_builtFlags.beads)   ||
        (needsSlabs   && !_builtFlags.slabs)   ||
        (needsCones   && !_builtFlags.cones)   ||
        (needsFluoros && !_builtFlags.fluoros)
      )
      if (needsRebuild) return { needsRebuild: true }

      _detailLevel = level
      const coarse = level === 2
      iSpheres.visible        = !coarse
      iCubes.visible          = !coarse
      iCones.visible          = !coarse
      iSlabs.visible          = level === 0
      iSlabConnectors.visible = level === 0
      iFluoros.visible           = !coarse
      iHelixCylinders.visible          = coarse
      iOverhangCylinders.visible       = coarse
      iOverhangFullCylinders.visible   = coarse
      iCurvedHelixCylinders.visible    = coarse
      _curvedCylGroup.visible          = coarse
      iCurvedOverhangCylinders.visible = coarse
      iCurvedOverhangFullCylinders.visible = coarse
      _curvedOvhgGroup.visible         = coarse
      iLinkerBindingCylinders.visible  = coarse
      iLinkerBridgeCylinders.visible   = coarse
      const showArrows = !coarse && _axisArrowsVisible
      if (!showArrows) {
        for (const arrow of axisArrows) {
          if (arrow.shaft) arrow.shaft.visible = false
          if (arrow.straightShaft) arrow.straightShaft.visible = false
          for (const seg of arrow.segments ?? []) {
            if (seg.mesh)     seg.mesh.visible     = false
            if (seg.tubeMesh) seg.tubeMesh.visible = false
          }
        }
      } else {
        // Respect current shaft mode rather than flipping every mesh on,
        // otherwise single-segment curved helices show both deformed and
        // straight shafts simultaneously after switching LOD back to Full.
        _applyShaftModeVisibility(_currentShaftMode)
      }
      // Mixed representation: the override's visibility depends on the global
      // level (which way each unoverridden domain renders), so re-apply it.
      if (_repActive) _applyRepOverrides()
      return { needsRebuild: false }
    },

    /**
     * Lerp all geometry from straight positions to deformed positions.
     *
     * @param {Map<string, THREE.Vector3>} straightPosMap
     *   Key: "helix_id:bp_index:direction" → straight backbone position (t=0 anchor).
     * @param {Map<string, {start:THREE.Vector3, end:THREE.Vector3}>} straightAxesMap
     *   Key: helix_id → straight axis start/end (t=0 anchor for arrows).
     * @param {Map<string, THREE.Vector3>} straightBnMap
     *   Key: "helix_id:bp_index:direction" → straight base_normal (cross-strand unit vector).
     *   Used for slab orientation at t=0; avoids the 30° error from inward-radial approximation.
     * @param {number} t  lerp factor in [0, 1]; 0 = straight, 1 = deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, straightBaseMap, t) {
      // 1. Backbone beads
      for (const entry of backboneEntries) {
        const nuc = entry.nuc
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const sp  = straightPosMap.get(key)
        const dp  = nuc.backbone_position  // deformed [x, y, z]
        if (sp && dp) {
          entry.pos.set(
            sp.x + (dp[0] - sp.x) * t,
            sp.y + (dp[1] - sp.y) * t,
            sp.z + (dp[2] - sp.z) * t,
          )
        } else if (dp) {
          entry.pos.set(dp[0], dp[1], dp[2])
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 1b. Fluorophore / modification tip beads — the free end of a strand
      //     extension. These live in fluoroEntries (not backboneEntries), so
      //     without this loop they stay pinned at their deformed position and
      //     detach from the extension arc when the deform toggle is OFF (t=0).
      //     Same straight↔deformed lerp as the backbone beads, keyed identically
      //     (`__ext_{id}:bp_index:direction`).
      if (!_skipFluoros) {
        for (const entry of fluoroEntries) {
          const nuc = entry.nuc
          const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
          const sp  = straightPosMap.get(key)
          const dp  = nuc.backbone_position
          if (sp && dp) {
            entry.pos.set(
              sp.x + (dp[0] - sp.x) * t,
              sp.y + (dp[1] - sp.y) * t,
              sp.z + (dp[2] - sp.z) * t,
            )
          } else if (dp) {
            entry.pos.set(dp[0], dp[1], dp[2])
          }
          _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
          entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        }
        iFluoros.instanceMatrix.needsUpdate = true
      }

      // 2. Cones — direction from the current lerped bead positions (already updated in step 1).
      //    Using fe.pos/te.pos is correct for both cluster rotations (rigid body — all beads
      //    moved together, so bead-to-bead direction is accurate) and bend deformations
      //    (shows the actual bent path).  Mixing pre-rotation straight positions with
      //    post-rotation bead positions (the old approach) caused mismatched midPos at t=1.
      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(cone.coneRadius, cone.coneHeight, cone.coneRadius))
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — lerp both center and orientation between straight (t=0) and deformed (t=1)
      for (const slab of slabEntries) {
        const entry = _nucToEntry.get(slab.nuc)
        if (!entry) continue

        const nuc = slab.nuc
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const sp  = straightPosMap?.get(key)
        const sa  = straightAxesMap?.get(nuc.helix_id)

        let slabCenter_, slabQuat_
        if (sp && sa) {
          _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
          // Use the straight base_normal (cross-strand) from the straight geometry map when
          // available.  Falling back to the inward-radial (axis_projection − sp) is 30° wrong
          // for B-DNA with a 120° minor groove angle.
          const sbn = straightBnMap?.get(key)
          if (sbn) {
            _slabBnS.copy(sbn)
          } else {
            const axisProj = (sp.x - sa.start.x) * _slabAxisDir.x
                           + (sp.y - sa.start.y) * _slabAxisDir.y
                           + (sp.z - sa.start.z) * _slabAxisDir.z
            _slabProj.copy(sa.start).addScaledVector(_slabAxisDir, axisProj)
            _slabBnS.copy(_slabProj).sub(sp).normalize()
          }

          // Both endpoint frames must be orthonormal. Both endpoint centers come from
          // the paired coordinate abstraction; no legacy backbone offset is introduced.
          _slabQuatS.copy(slabQuaternion(_slabBnS, _slabAxisDir))
          _slabCenterAt(slab, _slabAxisDir, straightBaseMap, straightPosMap, _slabCenterS)

          const dp = nuc.backbone_position
          _slabAxisDir.set(...nuc.axis_tangent).normalize()
          _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)

          // Lerp center; slerp quaternion.
          _slabCenterL.lerpVectors(_slabCenterS, _slabCenterD, t)
          _slabQuatL.copy(_slabQuatS).slerp(slab.quat, t)

          slabCenter_ = _slabCenterL
          slabQuat_   = _slabQuatL
        } else {
          // No straight data available — stay at deformed orientation.
          slab.bbPos.copy(entry.pos)
          _slabAxisDir.set(...nuc.axis_tangent).normalize()
          slabCenter_ = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
          slabQuat_   = slab.quat
        }

        slab.bbPos.copy(entry.pos)  // keep in sync for non-deform-lerp methods
        _tMatrix.compose(slabCenter_, slabQuat_, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()

      // 4. Axis sticks — lerp from straight (sa) to deformed (arrow.aStart/aEnd).
      for (const arrow of axisArrows) {
        const sa  = straightAxesMap?.get(arrow.helixId)

        // Multi-segment curved helices: per-segment endpoint lerp so each
        // domain stays at its own position and the bp gaps stay empty.
        // Non-curved helices use the legacy single-line _layStraightSegments
        // (correct because the entire helix is rigid).
        if (arrow.useSegments && arrow.isCurved) {
          _lerpPerSegment(arrow, sa?.segments, t)
          continue
        }

        const sx0 = sa ? sa.start.x + (arrow.aStart.x - sa.start.x) * t : arrow.aStart.x
        const sy0 = sa ? sa.start.y + (arrow.aStart.y - sa.start.y) * t : arrow.aStart.y
        const sz0 = sa ? sa.start.z + (arrow.aStart.z - sa.start.z) * t : arrow.aStart.z
        const sx1 = sa ? sa.end.x   + (arrow.aEnd.x   - sa.end.x)   * t : arrow.aEnd.x
        const sy1 = sa ? sa.end.y   + (arrow.aEnd.y   - sa.end.y)   * t : arrow.aEnd.y
        const sz1 = sa ? sa.end.z   + (arrow.aEnd.z   - sa.end.z)   * t : arrow.aEnd.z

        if (arrow.isCurved) {
          // Shaft / straightShaft opacities are NOT lerped here — they're
          // a binary switch driven by deformView.setAxisShaftMode() at the
          // start of activate/deactivate. See setAxisShaftMode in the
          // controller below. Keep the straightShaft repositioned along
          // the lerped axis so when the user toggles off it's already in
          // the right place at t=1 and animates correctly to t=0.
          if (arrow.straightShaft && sa) {
            _physDir.set(sx1 - sx0, sy1 - sy0, sz1 - sz0)
            const sLen = _physDir.length()
            if (sLen > 0.001) {
              _physDir.divideScalar(sLen)
              arrow.straightShaft.position.set(
                (sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, (sz0 + sz1) * 0.5,
              )
              arrow.straightShaft.quaternion.setFromUnitVectors(Y_HAT, _physDir)
              arrow.straightShaft.scale.set(1, sLen, 1)
            }
          }
        } else {
          // Straight: lay segments along the lerped axis line.
          _physDir.set(sx0, sy0, sz0)
          _physDir2.set(sx1, sy1, sz1)
          _layStraightSegments(arrow, _physDir, _physDir2)
        }
      }

      // 5. Straight-helix domain cylinders (LOD) — follow lerped axis endpoints.
      for (const dom of _domainCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iHelixCylinders.instanceMatrix.needsUpdate = true
      _refreshCylGlow()

      // 5b. Straight-helix overhang cylinders (LOD) — same approach.
      for (const dom of _overhangCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        _ovhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
      }
      _markOvhgCylMatricesDirty()

      // 5c. Curved-helix domain cylinders — proxy follows lerped straight axis; tube opacity = t.
      for (const dom of _curvedDomainCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
      _fadeCurvedProxy(iCurvedHelixCylinders.material, 1 - t)
      for (const mesh of _curvedCylGroup.children)   _fadeCurvedTube(mesh, t)
      for (const dom of _curvedOvhgCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        _curvedOvhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
      }
      _markCurvedOvhgCylMatricesDirty()
      _fadeCurvedProxy(iCurvedOverhangCylinders.material, 1 - t)
      _fadeCurvedProxy(iCurvedOverhangFullCylinders.material, 1 - t)
      for (const mesh of _curvedOvhgGroup.children)  _fadeCurvedTube(mesh, t)
    },

    /**
     * Lerp all geometry between two arbitrary world-space position states.
     * Unlike applyDeformLerp, both endpoints are explicit Maps — no reference
     * to nuc.backbone_position or internal straight maps.  Used by the animation
     * player to smoothly transition between pre-baked keyframe geometry states.
     *
     * BakedGeometry shape (both fromBaked and toBaked):
     *   { posMap:  Map<"hid:bp:dir", THREE.Vector3>,
     *     axesMap: Map<helix_id, {start, end}>,
     *     bnMap:   Map<"hid:bp:dir", THREE.Vector3> }
     *
     * @param {object} fromBaked  — geometry state at t=0
     * @param {object} toBaked    — geometry state at t=1
     * @param {number} t          — lerp factor in [0, 1]
     */
    applyPositionLerp(fromBaked, toBaked, t, excludeHelixIds = null, fadeOpts = null) {
      // DELETE PENDING REVIEW (non-authoritative geometry): baked animation
      // states omit base_position and therefore synthesize slab transforms.
      if (!fromBaked || !toBaked) return
      const { posMap: fromPosMap, axesMap: fromAxesMap, bnMap: fromBnMap } = fromBaked
      const { posMap: toPosMap,   axesMap: toAxesMap,   bnMap: toBnMap   } = toBaked

      // Helper: returns true if this helix belongs to an excluded (rigid-body) cluster.
      // Handles both real helix IDs and __ext_ extension helices via _extToRealHelix.
      const _isExcluded = excludeHelixIds
        ? (hid) => {
            if (excludeHelixIds.has(hid)) return true
            if (hid.startsWith('__ext_')) {
              const parent = _extToRealHelix.get(hid.slice('__ext_'.length))
              if (parent && excludeHelixIds.has(parent)) return true
            }
            return false
          }
        : () => false

      // ── Per-element fade for "this is how I made this" reveal ────────────
      // fadeOpts: { revealInStrandIds, revealOutStrandIds, revealInHelixIds, revealOutHelixIds }
      // Returns scale-multiplier in [0, 1]:
      //   1.0 → element exists in BOTH from and to (full visible throughout)
      //     t → element only in to-state ("revealing in" — grows from 0 to 1)
      // 1 - t → element only in from-state ("fading out" — shrinks from 1 to 0)
      // Scale-based fade keeps positions intact; instance just shrinks to a
      // point when invisible. Cheap (no shader / per-instance opacity needed).
      const _strandFade = fadeOpts
        ? (sid) => {
            if (!sid) return 1
            if (fadeOpts.revealInStrandIds?.has(sid))  return t
            if (fadeOpts.revealOutStrandIds?.has(sid)) return 1 - t
            return 1
          }
        : () => 1
      const _helixFade = fadeOpts
        ? (hid) => {
            if (!hid) return 1
            if (fadeOpts.revealInHelixIds?.has(hid))  return t
            if (fadeOpts.revealOutHelixIds?.has(hid)) return 1 - t
            return 1
          }
        : () => 1

      // 1. Backbone beads
      // Position lerp is skipped for helices owned by rigid-body cluster
      // transforms (applyClusterTransform handles those). But the FADE scale
      // must still apply to those beads — otherwise default-cluster designs
      // (where every helix belongs to "Cluster 1") never see the fade.
      //
      // PER-NUCLEOTIDE fade granularity: a nucleotide is "new" iff its
      // (helix_id, bp_index, direction) key isn't in fromPosMap. This catches
      // extension-of-existing-strand cases (continuation extrudes) where the
      // strand_id stays the same but new bps appear — per-strand fade alone
      // would miss those and pop them in at t=0. Per-helix is similarly too
      // coarse: a helix that's extended in bp range stays the same helix_id.
      for (const entry of backboneEntries) {
        const isExcluded = _isExcluded(entry.nuc.helix_id)
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const fp  = fromPosMap?.get(key)
        const tp  = toPosMap?.get(key)

        if (!isExcluded) {
          if (fp && tp) {
            entry.pos.lerpVectors(fp, tp, t)
          } else if (tp) {
            entry.pos.copy(tp)
          } else if (fp) {
            entry.pos.copy(fp)
          }
        }
        // Per-nuc fade from posMap presence:
        //   both       → 1   (existed throughout)
        //   to-only    → t   (new in to-state, fade in)
        //   from-only  → 1-t (removed in to-state, fade out)
        let fade
        if (fp && tp)       fade = 1
        else if (tp)        fade = t
        else if (fp)        fade = 1 - t
        else                fade = 0   // defensive — bead exists in scene but neither baked
        if (isExcluded && fade === 1) continue   // applyClusterTransform already set the matrix
        const s = _beadScale * fade
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(s, s, s))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — per-nucleotide fade based on both endpoint nucs' presence
      // in fromPosMap / toPosMap. A cone exists iff both of its endpoint
      // nucleotides exist; if either endpoint is missing in a side, the cone
      // is missing on that side too. For cluster-owned helices,
      // applyClusterTransform already wrote the matrix; we re-write only
      // when fade != 1.
      for (const cone of coneEntries) {
        const isExcluded = _isExcluded(cone.fromNuc.helix_id) || _isExcluded(cone.toNuc.helix_id)
        const fromKey = `${cone.fromNuc.helix_id}:${cone.fromNuc.bp_index}:${cone.fromNuc.direction}`
        const toKey   = `${cone.toNuc.helix_id}:${cone.toNuc.bp_index}:${cone.toNuc.direction}`
        const fp_f    = fromPosMap?.get(fromKey)
        const fp_t    = fromPosMap?.get(toKey)
        const tp_f    = toPosMap?.get(fromKey)
        const tp_t    = toPosMap?.get(toKey)
        const existedBefore = !!(fp_f && fp_t)
        const existsAfter   = !!(tp_f && tp_t)
        let coneFade
        if (existedBefore && existsAfter)       coneFade = 1
        else if (existsAfter)                   coneFade = t
        else if (existedBefore)                 coneFade = 1 - t
        else                                    coneFade = 0
        if (isExcluded && coneFade === 1) continue   // cluster transform already wrote the matrix

        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue

        if (!isExcluded) {
          // Prefer fromPosMap endpoints when both exist (gives a smooth lerp
          // anchor); otherwise use entry.pos which already holds the lerped
          // or copied per-nuc position from the bead pass above.
          if (fp_f && fp_t) {
            _physDir.copy(fp_t).sub(fp_f)
          } else {
            _physDir.copy(te.pos).sub(fe.pos)
          }
          const dist = _physDir.length()
          const h    = Math.max(0.001, dist)
          _physDir.divideScalar(dist || 1)
          cone.quat.setFromUnitVectors(Y_HAT, _physDir)
          cone.coneHeight = h
          cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        }
        // For excluded entries, cone.midPos / cone.quat / cone.coneHeight
        // already reflect the cluster-transformed positions from
        // applyClusterTransform; we just override scale to apply the fade.
        _tMatrix.compose(
          cone.midPos, cone.quat,
          _tScale.set(cone.coneRadius * coneFade, cone.coneHeight * coneFade, cone.coneRadius * coneFade),
        )
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — per-nucleotide fade (same granularity as beads). Slab
      // presence in fromBnMap / toBnMap mirrors the bead's posMap presence.
      // For cluster-owned helices, applyClusterTransform already wrote the
      // matrix; we re-write only when fade != 1.
      for (const slab of slabEntries) {
        const isExcluded = _isExcluded(slab.nuc.helix_id)
        const key = `${slab.nuc.helix_id}:${slab.nuc.bp_index}:${slab.nuc.direction}`
        const fbn = fromBnMap?.get(key)
        const tbn = toBnMap?.get(key)
        let slabFade
        if (fbn && tbn)      slabFade = 1
        else if (tbn)        slabFade = t
        else if (fbn)        slabFade = 1 - t
        else                 slabFade = 0
        if (isExcluded && slabFade === 1) continue

        const entry = _nucToEntry.get(slab.nuc)
        if (!entry) continue
        slab.bbPos.copy(entry.pos)

        if (!isExcluded) {
          if (fbn && tbn) {
            _slabBnS.lerpVectors(fbn, tbn, t).normalize()
            // Approximate axis dir from lerped helix endpoints
            const fa = fromAxesMap?.get(slab.nuc.helix_id)
            const ta = toAxesMap?.get(slab.nuc.helix_id)
            if (fa && ta) {
              _physDir.lerpVectors(fa.end, ta.end, t)
              _physDir2.lerpVectors(fa.start, ta.start, t)
              _slabAxisDir.copy(_physDir).sub(_physDir2).normalize()
            } else {
              _slabAxisDir.set(0, 1, 0)
            }
            _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
            _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
            slab.bnDir.copy(_slabBnS)
            slab.quat.setFromRotationMatrix(_slabBasis)
          }
        }
        _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
        const center_ = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
        _tMatrix.compose(
          center_, slab.quat,
          _tScale.set(slabParams.length * slabFade, slabParams.width * slabFade, slabParams.thickness * slabFade),
        )
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()

      // 4. Axis sticks — lerp from "from" axes (fa) to "to" axes (ta).
      // Per-domain fade: each segment's bp range [bp_lo, bp_hi] is checked
      // against the from/to posMaps for its helix. A segment is "present"
      // on a side iff at least one bp in its range exists in that posMap.
      // This matches the bead/slab/cone treatment and lets a helix carrying
      // both a pre-existing and a freshly-extruded domain fade in only the
      // new domain's axis stick.
      const _bpSetByHelix = (posMap) => {
        const m = new Map()
        if (!posMap) return m
        for (const key of posMap.keys()) {
          const lastColon = key.lastIndexOf(':')
          const midColon  = key.lastIndexOf(':', lastColon - 1)
          if (midColon < 0) continue
          const hid = key.slice(0, midColon)
          const bp  = +key.slice(midColon + 1, lastColon)
          let s = m.get(hid)
          if (!s) { s = new Set(); m.set(hid, s) }
          s.add(bp)
        }
        return m
      }
      const _fromBpsByHelix = _bpSetByHelix(fromPosMap)
      const _toBpsByHelix   = _bpSetByHelix(toPosMap)
      const _segCovers = (bpSetByHelix, helixId, bp_lo, bp_hi) => {
        const s = bpSetByHelix.get(helixId)
        if (!s) return false
        for (let bp = bp_lo; bp <= bp_hi; bp++) if (s.has(bp)) return true
        return false
      }
      const _segFadeFor = (helixId, bp_lo, bp_hi) => {
        const before = _segCovers(_fromBpsByHelix, helixId, bp_lo, bp_hi)
        const after  = _segCovers(_toBpsByHelix,   helixId, bp_lo, bp_hi)
        if (before && after) return 1
        if (after)           return t
        if (before)          return 1 - t
        return 0
      }
      // Returns [lo, hi] of the actual covered bp subrange within [bp_lo, bp_hi]
      // on the given side, or null if no bp in that range is populated. Used
      // to shrink the visible axis stick to match where nucleotides actually
      // exist — finer-grained than per-domain when a single domain spans the
      // whole helix and a continuation extrude has populated only a subrange.
      const _coveredBpRange = (bpSet, bp_lo, bp_hi) => {
        if (!bpSet) return null
        let lo = -1, hi = -1
        for (let bp = bp_lo; bp <= bp_hi; bp++) {
          if (bpSet.has(bp)) {
            if (lo < 0) lo = bp
            hi = bp
          }
        }
        return lo < 0 ? null : [lo, hi]
      }
      // Helix-level presence (any bp in any posMap entry for this helix).
      // Used for curved helices, which have a single shaft tube and can't
      // be split per-domain.
      const _helixPresent = (bpSetByHelix, helixId) => bpSetByHelix.has(helixId)
      const _helixFadeFromBps = (helixId) => {
        const before = _helixPresent(_fromBpsByHelix, helixId)
        const after  = _helixPresent(_toBpsByHelix,   helixId)
        if (before && after) return 1
        if (after)           return t
        if (before)          return 1 - t
        return 0
      }

      for (const arrow of axisArrows) {
        const isExcluded = _isExcluded(arrow.helixId)
        if (!isExcluded) {
          const fa = fromAxesMap?.get(arrow.helixId)
          const ta = toAxesMap?.get(arrow.helixId)
          if (!fa && !ta) {
            // Skip position update; segment scale fade still applies below.
          } else if (!fa || !ta) {
            // Helix only in one of the two states — position from whichever
            // side's axis exists; per-segment scale fade below handles
            // grow/shrink.
            const lone = ta || fa
            arrow.aStart.copy(lone.start)
            arrow.aEnd.copy(lone.end)
            if (arrow.straightShaft) {
              const fadeLone = _helixFadeFromBps(arrow.helixId)
              _physDir.copy(lone.end).sub(lone.start)
              const sLen = _physDir.length()
              if (sLen > 0.001) {
                _physDir.divideScalar(sLen)
                arrow.straightShaft.position.set(
                  (lone.start.x + lone.end.x) * 0.5,
                  (lone.start.y + lone.end.y) * 0.5,
                  (lone.start.z + lone.end.z) * 0.5,
                )
                arrow.straightShaft.quaternion.setFromUnitVectors(Y_HAT, _physDir)
                arrow.straightShaft.scale.set(fadeLone, sLen * fadeLone, fadeLone)
              }
            } else {
              _layStraightSegments(arrow, lone.start, lone.end)
            }
          } else {
            const sx0 = fa.start.x + (ta.start.x - fa.start.x) * t
            const sy0 = fa.start.y + (ta.start.y - fa.start.y) * t
            const sz0 = fa.start.z + (ta.start.z - fa.start.z) * t
            const sx1 = fa.end.x   + (ta.end.x   - fa.end.x)   * t
            const sy1 = fa.end.y   + (ta.end.y   - fa.end.y)   * t
            const sz1 = fa.end.z   + (ta.end.z   - fa.end.z)   * t
            arrow.aStart.set(sx0, sy0, sz0)
            arrow.aEnd.set(sx1, sy1, sz1)
            if (arrow.isCurved) {
              const mat = arrow.shaft?.material
              if (mat) { mat.transparent = true; mat.opacity = t }
              if (arrow.straightShaft) {
                _physDir.set(sx1 - sx0, sy1 - sy0, sz1 - sz0)
                const sLen = _physDir.length()
                if (sLen > 0.001) {
                  _physDir.divideScalar(sLen)
                  arrow.straightShaft.position.set(
                    (sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, (sz0 + sz1) * 0.5,
                  )
                  arrow.straightShaft.quaternion.setFromUnitVectors(Y_HAT, _physDir)
                  arrow.straightShaft.scale.set(1, sLen, 1)
                  arrow.straightShaft.material.transparent = true
                  arrow.straightShaft.material.opacity = 1 - t
                }
              }
            } else {
              _physDir.set(sx0, sy0, sz0)
              _physDir2.set(sx1, sy1, sz1)
              _layStraightSegments(arrow, _physDir, _physDir2)
            }
          }
        }

        // Per-bp-range axis-segment recomputation (straight helices). Each
        // segment is positioned + scaled to span the actual covered bp
        // subrange on each side, with endpoints lerped between sides.
        //
        // SKIPPED for excluded (cluster-owned) helices: applyClusterTransform's
        // slerp already wrote the correct rotated segment positions, and
        // re-running this block would replace them with a linear (chord) lerp
        // of the segment endpoints — visibly diverging from the beads' slerp
        // arc whenever the keyframe transition spans multiple cluster_op
        // entries (FX → FX+2 with two rotations between).
        if (!arrow.isCurved && arrow.segments?.length && !_isExcluded(arrow.helixId)) {
          const fa = fromAxesMap?.get(arrow.helixId)
          const ta = toAxesMap?.get(arrow.helixId)
          const fromBpSet = _fromBpsByHelix.get(arrow.helixId)
          const toBpSet   = _toBpsByHelix.get(arrow.helixId)

          // Helper: project bp [lo, hi+1] onto the axis (start, end). Writes
          // to outStart/outEnd. Uses arrow.bpStart as the bp anchor (assumed
          // common across states; helices don't typically change bp_start).
          const _projectBpRange = (axStart, axEnd, lo, hi, outStart, outEnd) => {
            _physDir.set(axEnd.x - axStart.x, axEnd.y - axStart.y, axEnd.z - axStart.z)
            const aLen = _physDir.length()
            if (aLen < 0.001) { outStart.copy(axStart); outEnd.copy(axStart); return }
            _physDir.divideScalar(aLen)
            const tS = (lo - arrow.bpStart) * BDNA_RISE_PER_BP
            const tE = (hi - arrow.bpStart + 1) * BDNA_RISE_PER_BP
            outStart.copy(axStart).addScaledVector(_physDir, tS)
            outEnd.copy(axStart).addScaledVector(_physDir, tE)
          }

          for (const seg of arrow.segments) {
            const fromRange = _coveredBpRange(fromBpSet, seg.bp_lo, seg.bp_hi)
            const toRange   = _coveredBpRange(toBpSet,   seg.bp_lo, seg.bp_hi)

            if (!fromRange && !toRange) {
              seg.mesh.scale.set(0, 0, 0)
              continue
            }

            // World endpoints of covered subrange on each side (when available).
            let haveFrom = false, haveTo = false
            if (fa && fromRange) {
              _projectBpRange(fa.start, fa.end, fromRange[0], fromRange[1], _segS_from, _segE_from)
              haveFrom = true
            }
            if (ta && toRange) {
              _projectBpRange(ta.start, ta.end, toRange[0], toRange[1], _segS_to, _segE_to)
              haveTo = true
            }

            let segStart, segEnd, fadeXZ
            if (haveFrom && haveTo) {
              _segS.lerpVectors(_segS_from, _segS_to, t)
              _segE.lerpVectors(_segE_from, _segE_to, t)
              segStart = _segS; segEnd = _segE
              fadeXZ = 1
            } else if (haveTo) {
              segStart = _segS_to; segEnd = _segE_to
              fadeXZ = t
            } else if (haveFrom) {
              segStart = _segS_from; segEnd = _segE_from
              fadeXZ = 1 - t
            } else {
              // Coverage exists but no axis on that side — fall back to a
              // pure scale fade using whichever subrange is present, leaving
              // the segment at its current position.
              const f = haveFrom || haveTo ? 1 : 0
              seg.mesh.scale.set(f, f, f)
              continue
            }

            _physDir.set(segEnd.x - segStart.x, segEnd.y - segStart.y, segEnd.z - segStart.z)
            const segLen = _physDir.length()
            if (segLen < 0.001) {
              seg.mesh.scale.set(0, 0, 0)
              continue
            }
            _physDir.divideScalar(segLen)
            seg.mesh.position.set(
              (segStart.x + segEnd.x) * 0.5,
              (segStart.y + segEnd.y) * 0.5,
              (segStart.z + segEnd.z) * 0.5,
            )
            seg.mesh.quaternion.setFromUnitVectors(_AY, _physDir)
            const yScale = segLen / Math.max(0.001, seg.adjLen)
            seg.mesh.scale.set(fadeXZ, yScale * fadeXZ, fadeXZ)
          }
        }
      }

      // 5. Helix shaft cylinders — per-domain fade is more granular than
      // per-helix because a single helix can carry both a scaffold AND a
      // staple domain; an extrude that adds only the scaffold strand should
      // fade in just that domain's cylinder while a pre-existing staple
      // cylinder on the same helix stays solid.
      // For cluster-excluded helices: cluster transform already wrote the
      // matrix, so we only re-write when fade != 1.
      const _writeCylMatrix = (dom, mesh, fade) => {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        const r = _cylRadiusScale * fade
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(r, cylLen * fade, r))
        mesh.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      const _processCylArr = (arr, meshFor) => {
        let touched = false
        const touchedMeshes = new Set()
        for (const dom of arr) {
          const isExcluded = _isExcluded(dom.helixId)
          // Per-domain fade based on bp range coverage in fromPosMap/toPosMap.
          // Falls back to strand+helix fade only when bp_lo/bp_hi aren't
          // available (legacy code paths).
          const fade = (dom.bp_lo != null && dom.bp_hi != null)
            ? _segFadeFor(dom.helixId, dom.bp_lo, dom.bp_hi)
            : Math.min(_strandFade(dom.strandId), _helixFade(dom.helixId))
          if (isExcluded && fade === 1) continue   // cluster transform already wrote the matrix
          const mesh = typeof meshFor === 'function' ? meshFor(dom) : meshFor
          _writeCylMatrix(dom, mesh, fade)
          touched = true
          touchedMeshes.add(mesh)
        }
        if (touched) for (const mesh of touchedMeshes) mesh.instanceMatrix.needsUpdate = true
      }
      _processCylArr(_domainCylData,       iHelixCylinders)
      _processCylArr(_overhangCylData,     _ovhgCylMesh)
      _processCylArr(_curvedDomainCylData, iCurvedHelixCylinders)
      _processCylArr(_curvedOvhgCylData,   _curvedOvhgCylMesh)
    },

    /**
     * Return cross-helix backbone connections at their current world positions.
     * Used by unfold_view.js to build arc overlays for the 3D view.
     */
    getCrossHelixConnections() {
      const conns = []
      // Track cross-helix cone site keys so we can skip crossover records
      // that already have a strand-topology cone (e.g. scaffold routing imports).
      const coneSiteKeys = new Set()

      // Linker strand domain transitions (real OH helix ↔ virtual `__lnk__`
      // helix) are owned by overhang_link_arcs.js, which draws its own
      // anchor → bridge-boundary arc. Skipping them here avoids a duplicate
      // arc per linker side.
      const _isLinkerHelix = (hid) => typeof hid === 'string' && hid.startsWith('__lnk__')

      for (const cone of coneEntries) {
        if (!cone.isCrossHelix) continue
        const fn = cone.fromNuc
        const tn = cone.toNuc
        // Surface-capture strands are standalone appended oxDNA chains. They have no
        // design-topology crossover/ligation to the origami; never promote one of their
        // connector cones into the shared crossover-arc layer.
        if (fn?.is_surface_capture || tn?.is_surface_capture) continue
        if (_isLinkerHelix(fn.helix_id) || _isLinkerHelix(tn.helix_id)) continue
        // Also skip linker bridge strands themselves (`__lnk__*__a` / `__b` / `__s`).
        // For ss linkers we already filter the bridge nucs from byStrand, which
        // collapses the strand's nucs to just complement-A and complement-B on
        // real OH helices — without this check, the cross-helix "cone" between
        // them sneaks through `_isLinkerHelix` and unfold_view draws it as a
        // straight chord between the two anchors. The whole linker visualization
        // is owned by overhang_link_arcs.js; no crossover arc should be added.
        if (typeof cone.strandId === 'string' && cone.strandId.startsWith('__lnk__')) continue
        // Use backbone_position (the deformed geometry position) rather than
        // fe.pos (the current rendered position, which may be at straight
        // coordinates if deform view is off at the time this is called).
        // This ensures from3D/to3D in arc entries always represent the deformed
        // state so the deform lerp can interpolate correctly.
        const fp = fn.backbone_position
        const tp = tn.backbone_position
        conns.push({
          from:        new THREE.Vector3(fp[0], fp[1], fp[2]),
          to:          new THREE.Vector3(tp[0], tp[1], tp[2]),
          color:       cone.defaultColor,
          fromHelixId: fn.helix_id,
          toHelixId:   tn.helix_id,
          strandId:    cone.strandId,
          fromNuc:     fn,
          toNuc:       tn,
          isPeriodicSeam: !!cone.isPeriodicSeam,
        })
        const fk = `${fn.helix_id}:${fn.bp_index}:${fn.direction}`
        const tk = `${tn.helix_id}:${tn.bp_index}:${tn.direction}`
        coneSiteKeys.add(`${fk}|${tk}`)
        coneSiteKeys.add(`${tk}|${fk}`)
      }

      // Add connections for crossover records not already covered by strand
      // cones (i.e. crossovers placed without ligation).
      for (const xo of (design.crossovers ?? [])) {
        const ak = `${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`
        const bk = `${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`
        if (coneSiteKeys.has(`${ak}|${bk}`)) continue
        if (_isLinkerHelix(xo.half_a.helix_id) || _isLinkerHelix(xo.half_b.helix_id)) continue
        const entryA = _keyToEntry.get(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
        const entryB = _keyToEntry.get(`${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`)
        if (!entryA || !entryB) continue
        const fnuc = entryA.nuc
        const tnuc = entryB.nuc
        const fp = fnuc.backbone_position
        const tp = tnuc.backbone_position
        const color = fnuc.strand_type === 'scaffold'
          ? 0x0070bb
          : (stapleColorMap.get(fnuc.strand_id) ?? 0x445566)
        conns.push({
          from:        new THREE.Vector3(fp[0], fp[1], fp[2]),
          to:          new THREE.Vector3(tp[0], tp[1], tp[2]),
          color,
          fromHelixId: fnuc.helix_id,
          toHelixId:   tnuc.helix_id,
          strandId:    fnuc.strand_id,
          fromNuc:     fnuc,
          toNuc:       tnuc,
        })
      }

      return conns
    },

    /** Returns the raw axisArrows array for debug hit-testing. */
    getAxisArrows() { return axisArrows },

    /** Show or hide all axis sticks (per-domain segments + curved tube shaft). Persists across LOD changes.
     *
     *  When making visible, re-applies the current shaft mode (`_currentShaftMode`)
     *  rather than flipping every mesh to visible. This matters on cadnano exit:
     *  if the user toggled to straight view before entering cadnano, we want to
     *  restore straightShaft-only visibility on exit, not show BOTH the
     *  deformed curve and the straight chord for single-segment curved helices. */
    setAxisArrowsVisible(visible) {
      _axisArrowsVisible = visible
      if (!visible) {
        // Hide every axis mesh wholesale.
        for (const arrow of axisArrows) {
          if (arrow.shaft) arrow.shaft.visible = false
          if (arrow.straightShaft) arrow.straightShaft.visible = false
          for (const seg of arrow.segments ?? []) {
            if (seg.mesh)     seg.mesh.visible     = false
            if (seg.tubeMesh) seg.tubeMesh.visible = false
          }
        }
      } else {
        _applyShaftModeVisibility(_currentShaftMode)
      }
    },

    /**
     * Given a __ext_* synthetic helix ID, return its parent real helix ID.
     * Used by unfold_view.applyClusterArcUpdate to check cluster membership
     * for extension-arc endpoints.
     * Returns null for non-extension helix IDs.
     */
    getExtParentHelixId(extHelixId) {
      if (!extHelixId?.startsWith('__ext_')) return null
      return _extToRealHelix.get(extHelixId.slice('__ext_'.length)) ?? null
    },

    /**
     * Snapshot current rendered positions for the given cluster helices.
     * Must be called once at gizmo attach time, before any drag begins.
     * applyClusterTransform uses these snapshots as the base for incremental transforms,
     * avoiding double-application of already-baked cluster transforms.
     *
     * @param {string[]} helixIds
     */
    captureClusterBase(helixIds, domainIds = null, append = false, { forceAxes = false } = {}) {
      const helixSet = new Set(helixIds)
      const domainKeySet = domainIds?.length
        ? new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
        : null
      if (!append) {
        _cbEntries.clear()
        _cbSlabs.clear()
        _cbArrows.clear()
        _cbExtEntries.clear()
        _cbFluoEntries.clear()
        _cbOvhgCyls.clear()
        _cbSegments.clear()
      }
      for (const entry of backboneEntries) {
        if (!helixSet.has(entry.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${entry.nuc.strand_id}:${entry.nuc.domain_index}`)) continue
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        _cbEntries.set(key, entry.pos.clone())
      }
      for (const slab of slabEntries) {
        if (!helixSet.has(slab.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${slab.nuc.strand_id}:${slab.nuc.domain_index}`)) continue
        _cbSlabs.set(slab.nuc, { bnDir: slab.bnDir.clone(), quat: slab.quat.clone() })
      }
      // Helix-level axis snapshot (aStart/aEnd + curved-tube transforms). aStart/aEnd
      // are still consumed by overhang half-cylinder math; for partial-coverage clusters
      // they remain anchored to the build-time positions because no domainKeySet match
      // can identify "the helix's overall extent".
      if (!domainKeySet || forceAxes) {
        for (const arrow of axisArrows) {
          if (!helixSet.has(arrow.helixId)) continue
          _cbArrows.set(arrow.helixId, {
            aStart:    arrow.aStart.clone(),
            aEnd:      arrow.aEnd.clone(),
            shaftPos:  arrow.isCurved && arrow.shaft  ? arrow.shaft.position.clone()   : null,
            shaftQuat: arrow.isCurved && arrow.shaft  ? arrow.shaft.quaternion.clone()  : null,
            ssPos:     arrow.isCurved && arrow.straightShaft ? arrow.straightShaft.position.clone()   : null,
            ssQuat:    arrow.isCurved && arrow.straightShaft ? arrow.straightShaft.quaternion.clone()  : null,
          })
        }
      }
      // Extension and fluorophore beads are anchored at one strand terminus,
      // so we can snapshot/transform them per-extension regardless of whether
      // the cluster covers the whole helix or just one of its domains.
      // Sub-cluster mode: only snapshot if the extension's terminal domain
      // (5' → first domain, 3' → last domain) is in the moved set.
      const _extInScope = (nuc) => {
        const parentHelix = _extToRealHelix.get(nuc.extension_id)
        if (!parentHelix || !helixSet.has(parentHelix)) return false
        if (!domainKeySet || forceAxes) return true
        const termKey = _extToTerminalDomainKey.get(nuc.extension_id)
        return termKey != null && domainKeySet.has(termKey)
      }
      for (const entry of backboneEntries) {
        if (!entry.nuc.helix_id.startsWith('__ext_')) continue
        if (!_extInScope(entry.nuc)) continue
        _cbExtEntries.set(`${entry.nuc.helix_id}:${entry.nuc.bp_index}`, entry.pos.clone())
      }
      for (const entry of fluoroEntries) {
        if (!_extInScope(entry.nuc)) continue
        _cbFluoEntries.set(`${entry.nuc.helix_id}:${entry.nuc.bp_index}`, entry.pos.clone())
      }
      // Snapshot overhang cylinder world-space endpoints (shared-stub overhangs only).
      for (const dom of _overhangCylData) {
        if (!dom.wsStart) continue
        if (!helixSet.has(dom.helixId)) continue
        if (domainKeySet && !domainKeySet.has(`${dom.strandId}:${dom.domainIndex}`)) continue
        _cbOvhgCyls.set(dom, { wsStart: dom.wsStart.clone(), wsEnd: dom.wsEnd.clone() })
      }
      // Snapshot per-domain axis segments. Domain filter is enforced per segment so
      // a partial-coverage cluster only captures (and later transforms) segments that
      // belong to it; segments outside the cluster remain anchored to their build-time
      // world-space positions.
      for (const arrow of axisArrows) {
        if (!helixSet.has(arrow.helixId)) continue
        for (const seg of arrow.segments) {
          if (domainKeySet) {
            const k = `${seg.strandId}:${seg.domainIndex}`
            if (!domainKeySet.has(k)) continue
          }
          _cbSegments.set(seg, { wsStart: seg.wsStart.clone(), wsEnd: seg.wsEnd.clone() })
        }
      }
    },

    /**
     * Apply an incremental cluster transform directly to Three.js instance matrices.
     * Called on every gizmo drag event for zero-latency preview.
     *
     * Formula: pos' = R_incr*(base − center) + dummyPos
     * where base = position at captureClusterBase() time, center = dummy position at
     * attach time, dummyPos = current dummy position, R_incr = rotation since attach.
     *
     * This correctly handles re-activation after previous drags because backbone_position
     * in currentGeometry already has the old transform baked in; using the snapshot base
     * instead means the incremental formula never double-applies a prior transform.
     *
     * @param {string[]}         helixIds
     * @param {THREE.Vector3}    centerVec    dummy position at attach time
     * @param {THREE.Vector3}    dummyPosVec  current dummy position
     * @param {THREE.Quaternion} incrRotQuat  R_incr = current_quat * start_quat.invert()
     */
    applyClusterTransform(helixIds, centerVec, dummyPosVec, incrRotQuat, domainIds = null, { forceAxes = false } = {}) {
      // DELETE PENDING REVIEW (non-authoritative geometry): live drag mutates
      // renderer-local poses before the backend emits authoritative coordinates.
      const helixSet = new Set(helixIds)
      const domainKeySet = domainIds?.length
        ? new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
        : null

      // 1. Backbone beads — incremental transform from snapshot base
      for (const entry of backboneEntries) {
        if (!helixSet.has(entry.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${entry.nuc.strand_id}:${entry.nuc.domain_index}`)) continue
        const key  = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const base = _cbEntries.get(key)
        if (!base) continue
        _clusterV.copy(base).sub(centerVec).applyQuaternion(incrRotQuat)
        entry.pos.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }

      // 1b. Extension beads — must be updated before cone recompute so that
      //     cones connecting real terminal nucs to __ext_ beads are correct.
      //     Sub-cluster mode: an extension moves when its terminal domain
      //     (5' → first domain, 3' → last domain on its parent strand) is in
      //     the moved domain set. captureClusterBase already filtered the
      //     snapshot to those extensions, so the `_cbExtEntries.get` /
      //     `_cbFluoEntries.get` lookups double as the in-scope check here.
      let fluoroTouched = false
      for (const entry of backboneEntries) {
        const nuc = entry.nuc
        if (!nuc.helix_id.startsWith('__ext_')) continue
        const parentHelix = _extToRealHelix.get(nuc.extension_id)
        if (!parentHelix || !helixSet.has(parentHelix)) continue
        const base = _cbExtEntries.get(`${nuc.helix_id}:${nuc.bp_index}`)
        if (!base) continue   // not in the captured-base set → skipped by sub-cluster filter
        _clusterV.copy(base).sub(centerVec).applyQuaternion(incrRotQuat)
        entry.pos.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      for (const entry of fluoroEntries) {
        const nuc = entry.nuc
        const parentHelix = _extToRealHelix.get(nuc.extension_id)
        if (!parentHelix || !helixSet.has(parentHelix)) continue
        const base = _cbFluoEntries.get(`${nuc.helix_id}:${nuc.bp_index}`)
        if (!base) continue
        _clusterV.copy(base).sub(centerVec).applyQuaternion(incrRotQuat)
        entry.pos.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        fluoroTouched = true
      }
      if (fluoroTouched) iFluoros.instanceMatrix.needsUpdate = true

      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — recompute all from updated entry.pos (handles cross-cluster edges,
      //    including real→__ext_ and intra-__ext_ cones).
      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(cone.coneRadius, h, cone.coneRadius))
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — rotate the frame and recompute the center from the live bead position.
      for (const slab of slabEntries) {
        if (!helixSet.has(slab.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${slab.nuc.strand_id}:${slab.nuc.domain_index}`)) continue
        const entry    = _nucToEntry.get(slab.nuc)
        const baseData = _cbSlabs.get(slab.nuc)
        if (!entry || !baseData) continue
        slab.bbPos.copy(entry.pos)
        _clusterV.copy(baseData.bnDir).applyQuaternion(incrRotQuat)
        _clusterQ.multiplyQuaternions(incrRotQuat, baseData.quat)
        // Write back so captureClusterBase sees the current rendered orientation on the
        // next animation, not the stale original-geometry values (same reason
        // arrow.aStart/aEnd are written back in step 4).
        slab.bnDir.copy(_clusterV)
        slab.quat.copy(_clusterQ)
        _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
        const center_ = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
        _tMatrix.compose(center_, _clusterQ, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()

      // 4. Helix-level axis aStart/aEnd + curved tube transform.
      //    Partial-coverage clusters skip this (only individual segments move; aStart/aEnd
      //    can't represent the helix's overall extent under partial movement).
      if (!domainKeySet || forceAxes) for (const arrow of axisArrows) {
        if (!helixSet.has(arrow.helixId)) continue
        const baseData = _cbArrows.get(arrow.helixId)
        if (!baseData) continue
        _clusterV.copy(baseData.aStart).sub(centerVec).applyQuaternion(incrRotQuat)
        const sx0 = _clusterV.x + dummyPosVec.x, sy0 = _clusterV.y + dummyPosVec.y, sz0 = _clusterV.z + dummyPosVec.z
        _clusterV.copy(baseData.aEnd).sub(centerVec).applyQuaternion(incrRotQuat)
        const sx1 = _clusterV.x + dummyPosVec.x, sy1 = _clusterV.y + dummyPosVec.y, sz1 = _clusterV.z + dummyPosVec.z
        arrow.aStart.set(sx0, sy0, sz0)
        arrow.aEnd.set(sx1, sy1, sz1)

        if (arrow.isCurved) {
          // Rigidly transform the TubeGeometry shaft mesh + straight placeholder.
          if (arrow.shaft && baseData.shaftPos !== null) {
            _clusterV.copy(baseData.shaftPos).sub(centerVec).applyQuaternion(incrRotQuat)
            arrow.shaft.position.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
            _clusterQ.multiplyQuaternions(incrRotQuat, baseData.shaftQuat)
            arrow.shaft.quaternion.copy(_clusterQ)
          }
          if (arrow.straightShaft && baseData.ssPos !== null) {
            _clusterV.copy(baseData.ssPos).sub(centerVec).applyQuaternion(incrRotQuat)
            arrow.straightShaft.position.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
            _clusterQ.multiplyQuaternions(incrRotQuat, baseData.ssQuat)
            arrow.straightShaft.quaternion.copy(_clusterQ)
          }
        }
      }

      // 5. Overhang half-cylinders.
      //    Entries with wsStart use world-space snapshot/rotate (per-domain shared-stub fix).
      //    Entries without wsStart fall back to arrow.aStart/aEnd (extrude overhangs, forceAxes).
      {
        let anyOvhg = false
        for (const dom of _overhangCylData) {
          if (!helixSet.has(dom.helixId)) continue
          let d0x, d0y, d0z, d1x, d1y, d1z
          if (dom.wsStart) {
            const snap = _cbOvhgCyls.get(dom)
            if (!snap) continue
            if (domainKeySet && !domainKeySet.has(`${dom.strandId}:${dom.domainIndex}`)) continue
            const ns = _clusterV.copy(snap.wsStart).sub(centerVec).applyQuaternion(incrRotQuat)
            d0x = ns.x + dummyPosVec.x; d0y = ns.y + dummyPosVec.y; d0z = ns.z + dummyPosVec.z
            dom.wsStart.set(d0x, d0y, d0z)
            const ne = _clusterV.copy(snap.wsEnd).sub(centerVec).applyQuaternion(incrRotQuat)
            d1x = ne.x + dummyPosVec.x; d1y = ne.y + dummyPosVec.y; d1z = ne.z + dummyPosVec.z
            dom.wsEnd.set(d1x, d1y, d1z)
          } else {
            if (domainKeySet && !forceAxes) continue
            const s = dom.arrow.aStart, e = dom.arrow.aEnd
            d0x = s.x + (e.x - s.x) * dom.t0; d0y = s.y + (e.y - s.y) * dom.t0; d0z = s.z + (e.z - s.z) * dom.t0
            d1x = s.x + (e.x - s.x) * dom.t1; d1y = s.y + (e.y - s.y) * dom.t1; d1z = s.z + (e.z - s.z) * dom.t1
          }
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          _ovhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
          anyOvhg = true
        }
        if (anyOvhg) _markOvhgCylMatricesDirty()

        // 5b. Curved-helix proxy cylinders — same formula as overhang cylinders above.
        let anyCurved = false
        for (const dom of _curvedDomainCylData) {
          if (!helixSet.has(dom.helixId)) continue
          const s = dom.arrow.aStart, e = dom.arrow.aEnd
          const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
          const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
          anyCurved = true
        }
        for (const dom of _curvedOvhgCylData) {
          if (!helixSet.has(dom.helixId)) continue
          const s = dom.arrow.aStart, e = dom.arrow.aEnd
          const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
          const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          _curvedOvhgCylMesh(dom).setMatrixAt(dom.cylIdx, _tMatrix)
          anyCurved = true
        }
        if (anyCurved) {
          iCurvedHelixCylinders.instanceMatrix.needsUpdate   = true
          _markCurvedOvhgCylMatricesDirty()
        }

        // 5c. Per-domain axis segments (world-space cylinders, straight helices).
        //     Each segment moves independently based on its (strandId:domainIndex) match.
        for (const arrow of axisArrows) {
          if (!helixSet.has(arrow.helixId)) continue
          for (const seg of arrow.segments) {
            const snap = _cbSegments.get(seg)
            if (!snap) continue
            const ns = _clusterV.copy(snap.wsStart).sub(centerVec).applyQuaternion(incrRotQuat)
            const d0x = ns.x + dummyPosVec.x, d0y = ns.y + dummyPosVec.y, d0z = ns.z + dummyPosVec.z
            seg.wsStart.set(d0x, d0y, d0z)
            const ne = _clusterV.copy(snap.wsEnd).sub(centerVec).applyQuaternion(incrRotQuat)
            const d1x = ne.x + dummyPosVec.x, d1y = ne.y + dummyPosVec.y, d1z = ne.z + dummyPosVec.z
            seg.wsEnd.set(d1x, d1y, d1z)
            _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
            const segLen = _physDir.length()
            if (segLen > 0.001) {
              seg.mesh.position.copy(_clusterV.set(d0x, d0y, d0z).addScaledVector(_physDir, seg.adjLen * 0.5 / segLen))
              seg.mesh.quaternion.setFromUnitVectors(_AY, _physDir.divideScalar(segLen))
            }
          }
        }
      }
    },

    /**
     * Sync the in-memory geometry data (entry.nuc fields) to match the
     * currently rendered positions for the given helices. Used by Plan B's
     * cluster-transform commit path: after the gizmo's live drag has set
     * entry.pos / slab.bnDir to the new cluster-transformed values, we
     * reconcile nuc.backbone_position and nuc.base_normal so the store's
     * currentGeometry array stays consistent (entry.nuc is a shared
     * reference into currentGeometry items, so mutating it propagates).
     *
     * Without this sync, downstream consumers that read currentGeometry
     * (mrDNA relax / atomistic / surface mesh / save-to-disk / undo
     * round-trip) would see stale pre-cluster-transform positions even
     * though the on-screen visuals are correct.
     *
     * Note: nuc.base_position and nuc.axis_tangent are not updated here. Slab placement
     * uses base_position for the paired plane, backbone_position for bead contact, and
     * axis_tangent/base_normal for its frame. Consumers needing a fully authoritative
     * post-transform frame must trigger a fresh GET /design/geometry.
     */
    commitClusterPositions(helixIds) {
      const helixSet = new Set(helixIds)
      // Extensions (sequence beads on __ext_* helices and fluorophore beads)
      // inherit their parent helix's cluster transform — applyClusterTransform
      // step 1b moves them in lockstep with the parent. Sync their nuc data
      // so cross-helix arcs (rendered from nuc.backbone_position via
      // getCrossHelixConnections) and downstream consumers see post-transform
      // positions; otherwise the bead and the arc disagree.
      const _extParentInSet = (extId) => {
        const parent = _extToRealHelix.get(extId)
        return parent != null && helixSet.has(parent)
      }
      for (const entry of backboneEntries) {
        const hid = entry.nuc.helix_id
        const aff = hid.startsWith('__ext_')
          ? _extParentInSet(entry.nuc.extension_id)
          : helixSet.has(hid)
        if (!aff) continue
        if (!entry.nuc.backbone_position) continue
        entry.nuc.backbone_position[0] = entry.pos.x
        entry.nuc.backbone_position[1] = entry.pos.y
        entry.nuc.backbone_position[2] = entry.pos.z
      }
      for (const entry of fluoroEntries) {
        if (!_extParentInSet(entry.nuc.extension_id)) continue
        if (!entry.nuc.backbone_position) continue
        entry.nuc.backbone_position[0] = entry.pos.x
        entry.nuc.backbone_position[1] = entry.pos.y
        entry.nuc.backbone_position[2] = entry.pos.z
      }
      for (const slab of slabEntries) {
        if (!helixSet.has(slab.nuc.helix_id)) continue
        if (slab.nuc.helix_id.startsWith('__ext_')) continue
        if (!slab.nuc.base_normal) continue
        slab.nuc.base_normal[0] = slab.bnDir.x
        slab.nuc.base_normal[1] = slab.bnDir.y
        slab.nuc.base_normal[2] = slab.bnDir.z
      }
    },

    /**
     * Patch in-place the rendered positions of ds-linker bridge nucs.
     *
     * Called after a cluster commit (Plan B): the backend's
     * /design/refresh-bridges endpoint re-emits bridge nucs from the live OH
     * anchor positions and returns the updated dicts. We locate the matching
     * `backboneEntries` entry for each by `(helix_id, bp_index, direction)`,
     * mutate `entry.nuc.{backbone_position, base_position, base_normal,
     * axis_tangent}` (the shared reference into `currentGeometry`), update
     * `entry.pos`, and re-write the bead matrix. We then recompute slabs and
     * cones whose endpoints touch any updated bridge nuc — they need to track
     * the new positions/orientations so the bridge looks coherent.
     *
     * @param {Array<{helix_id: string, bp_index: number, direction: string,
     *                backbone_position: number[], base_position?: number[],
     *                base_normal?: number[], axis_tangent?: number[]}>} bridgeNucs
     */
    applyBridgeNucsUpdate(bridgeNucs) {
      if (!bridgeNucs?.length) return
      const updateByKey = new Map()
      for (const u of bridgeNucs) {
        updateByKey.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, u)
      }

      const updatedNucs = new Set()
      for (const entry of backboneEntries) {
        const n = entry.nuc
        const key = `${n.helix_id}:${n.bp_index}:${n.direction}`
        const u = updateByKey.get(key)
        if (!u) continue
        if (u.backbone_position && n.backbone_position) {
          n.backbone_position[0] = u.backbone_position[0]
          n.backbone_position[1] = u.backbone_position[1]
          n.backbone_position[2] = u.backbone_position[2]
        }
        if (u.base_position && n.base_position) {
          n.base_position[0] = u.base_position[0]
          n.base_position[1] = u.base_position[1]
          n.base_position[2] = u.base_position[2]
        }
        if (u.base_normal && n.base_normal) {
          n.base_normal[0] = u.base_normal[0]
          n.base_normal[1] = u.base_normal[1]
          n.base_normal[2] = u.base_normal[2]
        }
        if (u.axis_tangent && n.axis_tangent) {
          n.axis_tangent[0] = u.axis_tangent[0]
          n.axis_tangent[1] = u.axis_tangent[1]
          n.axis_tangent[2] = u.axis_tangent[2]
        }
        if (u.backbone_position) {
          entry.pos.set(u.backbone_position[0], u.backbone_position[1], u.backbone_position[2])
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        updatedNucs.add(n)
      }
      if (!updatedNucs.size) return

      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // Cones — recompute any cone with an updated endpoint (handles
      // bridge↔bridge intra-strand cones AND the bridge↔OH cross-helix cone
      // at each side). Cross-helix cones keep their radius-0 invisibility.
      let conesUpdated = false
      for (const cone of coneEntries) {
        if (!updatedNucs.has(cone.fromNuc) && !updatedNucs.has(cone.toNuc)) continue
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
        const r = cone.isCrossHelix ? 0 : cone.coneRadius
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
        iCones.setMatrixAt(cone.id, _tMatrix)
        conesUpdated = true
      }
      if (conesUpdated) iCones.instanceMatrix.needsUpdate = true

      // Slabs — recompute any slab whose nuc was updated, using the fresh
      // base_normal / axis_tangent / backbone_position from the response.
      let slabsUpdated = false
      const _slabBn  = new THREE.Vector3()
      const _slabTan = new THREE.Vector3()
      for (const slab of slabEntries) {
        if (!updatedNucs.has(slab.nuc)) continue
        const n = slab.nuc
        _slabBn.set(n.base_normal[0], n.base_normal[1], n.base_normal[2])
        _slabTan.set(n.axis_tangent[0], n.axis_tangent[1], n.axis_tangent[2])
        slab.bnDir.copy(_slabBn)
        slab.quat.copy(slabQuaternion(_slabBn, _slabTan))
        slab.bbPos.set(n.backbone_position[0], n.backbone_position[1], n.backbone_position[2])
        _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
        const center = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
        _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
        slabsUpdated = true
      }
      if (slabsUpdated) iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()
    },

    /**
     * Patch positions in place for an arbitrary set of helices. Used by the
     * `positions_only` diff path on seek / undo / redo: backend ships a
     * compact ``positions_by_helix`` payload (parallel arrays per helix &
     * direction) and this method walks the renderer state and updates
     * matrices without a full scene rebuild.
     *
     * @param {Object<string, Object<string, {bp:number[], bb:number[][],
     *                                         bs?:number[][], bn?:number[][],
     *                                         at?:number[][]}>>} positionsByHelix
     *   Per-helix, per-direction parallel arrays. ``bp`` is the bp_index
     *   list; ``bb`` / ``bs`` / ``bn`` / ``at`` are per-bp [x,y,z] arrays
     *   for backbone_position / base_position / base_normal / axis_tangent.
     * @param {Array<{helix_id, start, end, samples?, ovhg_axes?, segments?}>} helixAxes
     *   Updated per-helix axis endpoints; needed so axis cylinders track the
     *   new positions. Curved tubes' geometry is NOT rebuilt — the
     *   `_topology_unchanged` precondition guarantees no helix flipped
     *   between straight and curved, so existing tube shapes stay valid.
     */
    applyPositionsUpdate(positionsByHelix, helixAxes = null) {
      // ── 1. Build (helix:bp:dir) → position lookup ──────────────────────────
      const updateByKey = new Map()
      if (positionsByHelix) {
        for (const helixId of Object.keys(positionsByHelix)) {
          const byDir = positionsByHelix[helixId]
          for (const dir of Object.keys(byDir)) {
            const data = byDir[dir]
            if (!data || !Array.isArray(data.bp)) continue
            for (let i = 0; i < data.bp.length; i++) {
              updateByKey.set(`${helixId}:${data.bp[i]}:${dir}`, {
                bb: data.bb?.[i], bs: data.bs?.[i], bn: data.bn?.[i], at: data.at?.[i],
              })
            }
          }
        }
      }

      // ── 2. Update bead matrices (backbone + fluoro) ────────────────────────
      // entry.nuc was already mutated in client._syncPositionsOnlyDiff so the
      // nuc fields are fresh; here we copy positions into entry.pos and write
      // matrices. We track which nucs were touched so cones / slabs only
      // recompute for the affected ones.
      const updatedNucs = new Set()
      for (const entry of backboneEntries) {
        const n = entry.nuc
        const u = updateByKey.get(`${n.helix_id}:${n.bp_index}:${n.direction}`)
        if (!u || !u.bb) continue
        entry.pos.set(u.bb[0], u.bb[1], u.bb[2])
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        updatedNucs.add(n)
      }
      for (const entry of fluoroEntries) {
        const n = entry.nuc
        const u = updateByKey.get(`${n.helix_id}:${n.bp_index}:${n.direction}`)
        if (!u || !u.bb) continue
        entry.pos.set(u.bb[0], u.bb[1], u.bb[2])
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        updatedNucs.add(n)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true
      iFluoros.instanceMatrix.needsUpdate = true

      // ── 3. Recompute cones whose endpoints moved ───────────────────────────
      let conesUpdated = false
      for (const cone of coneEntries) {
        if (!updatedNucs.has(cone.fromNuc) && !updatedNucs.has(cone.toNuc)) continue
        const fe = _nucToEntry.get(cone.fromNuc) ?? _fluoroNucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)   ?? _fluoroNucToEntry.get(cone.toNuc)
        if (!fe || !te) continue
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
        const r = cone.isCrossHelix ? 0 : cone.coneRadius
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
        iCones.setMatrixAt(cone.id, _tMatrix)
        conesUpdated = true
      }
      if (conesUpdated) iCones.instanceMatrix.needsUpdate = true

      // ── 4. Recompute slabs for moved nucs ──────────────────────────────────
      let slabsUpdated = false
      const _slabBn  = new THREE.Vector3()
      const _slabTan = new THREE.Vector3()
      for (const slab of slabEntries) {
        if (!updatedNucs.has(slab.nuc)) continue
        const n = slab.nuc
        if (!n.base_normal || !n.axis_tangent || !n.backbone_position) continue
        _slabBn.set(n.base_normal[0], n.base_normal[1], n.base_normal[2])
        _slabTan.set(n.axis_tangent[0], n.axis_tangent[1], n.axis_tangent[2])
        slab.bnDir.copy(_slabBn)
        slab.quat.copy(slabQuaternion(_slabBn, _slabTan))
        slab.bbPos.set(n.backbone_position[0], n.backbone_position[1], n.backbone_position[2])
        _slabAxisDir.set(...slab.nuc.axis_tangent).normalize()
        const center = _slabCenterAt(slab, _slabAxisDir, null, null, _slabCenterD)
        _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
        slabsUpdated = true
      }
      if (slabsUpdated) iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()

      // ── 5. Update axis arrows (aStart/aEnd + per-domain segments) ──────────
      // For straight helices we use _layStraightSegments to translate per-domain
      // segment cylinders. Curved tubes are translated/rotated via their
      // existing meshes (.position/.quaternion); the geometry shape is fixed
      // by the topology_unchanged precondition.
      if (Array.isArray(helixAxes) && helixAxes.length) {
        const axesByHelix = new Map()
        for (const ax of helixAxes) axesByHelix.set(ax.helix_id, ax)
        for (const arrow of axisArrows) {
          const ax = axesByHelix.get(arrow.helixId)
          if (!ax) continue
          arrow.aStart.set(ax.start[0], ax.start[1], ax.start[2])
          arrow.aEnd.set(ax.end[0],   ax.end[1],   ax.end[2])
          if (!arrow.isCurved) {
            _layStraightSegments(arrow, arrow.aStart, arrow.aEnd)
          }
          // Curved tubes: positions/quaternions are computed on the fly by
          // applyClusterTransform during live drag; for positions_only we
          // accept the visible mesh staying at its prior orientation since
          // the topology_unchanged precondition forbids curvature flips.
          // (Improvement opportunity: ship shaft.position/quaternion in the
          // helix_axes payload and apply them here.)
        }
      }
    },

    /**
     * Lerp strand extension beads (sequence + fluorophore) toward their 2D unfold positions.
     *
     * @param {Map<string, Map<number, {x,y,z}>>} extArcMap
     *   Maps extension_id → Map<bp_index, target world position at full unfold>.
     * @param {number} unfoldT  Animation progress 0 (3D) → 1 (unfold).
     */
    applyUnfoldOffsetsExtensions(extArcMap, unfoldT, straightPosMap = null) {
      // Sequence beads (in backboneEntries, synthetic __ext_ helix).
      for (const entry of backboneEntries) {
        const nuc = entry.nuc
        if (!nuc.helix_id?.startsWith('__ext_')) continue
        const beadMap = extArcMap?.get(nuc.extension_id)
        const target  = beadMap?.get(nuc.bp_index)
        const sp = straightPosMap?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        const gx = sp ? sp.x : nuc.backbone_position[0]
        const gy = sp ? sp.y : nuc.backbone_position[1]
        const gz = sp ? sp.z : nuc.backbone_position[2]
        if (target) {
          entry.pos.set(
            gx + (target.x - gx) * unfoldT,
            gy + (target.y - gy) * unfoldT,
            gz + (target.z - gz) * unfoldT,
          )
        } else {
          entry.pos.set(gx, gy, gz)
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // Fluorophore beads.
      for (const entry of fluoroEntries) {
        const nuc     = entry.nuc
        const beadMap = extArcMap?.get(nuc.extension_id)
        const target  = beadMap?.get(nuc.bp_index)
        const sp = straightPosMap?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        const gx = sp ? sp.x : nuc.backbone_position[0]
        const gy = sp ? sp.y : nuc.backbone_position[1]
        const gz = sp ? sp.z : nuc.backbone_position[2]
        if (target) {
          entry.pos.set(
            gx + (target.x - gx) * unfoldT,
            gy + (target.y - gy) * unfoldT,
            gz + (target.z - gz) * unfoldT,
          )
        } else {
          entry.pos.set(gx, gy, gz)
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iFluoros.instanceMatrix.needsUpdate = true
    },

    /** Return fluorophore entries for raycasting and selection. */
    getFluoroEntries() { return fluoroEntries },

    /** Returns the live rendered position of a nucleotide entry, or null if not found.
     *  Used by unfold_view to update arc endpoints after cluster transforms.
     *  Falls back to fluoroEntries so cross-helix arcs to fluorophore beads
     *  track cluster transforms (the fluorophore bead is moved by
     *  applyClusterTransform step 1b but lives outside _nucToEntry). */
    getNucLivePos(nuc) {
      return (_nucToEntry.get(nuc) ?? _fluoroNucToEntry.get(nuc))?.pos ?? null
    },

    /**
     * Show or hide nucleotides by cluster membership.
     * Keys use two formats:
     *   'h:<helix_id>'                 — hide the whole helix (helix-level cluster)
     *   'd:<strand_id>:<domain_index>' — hide specific domain (domain-level cluster)
     * This lets two domain-level clusters sharing the same helix be toggled independently.
     * Hidden state survives resetAllToDefault because resetAllToDefault checks _isNucHidden.
     *
     * @param {Set<string>} keys
     */
    setHiddenNucs(keys) {
      _hiddenNucKeys = keys instanceof Set ? keys : new Set(keys)

      for (const entry of backboneEntries) {
        _setBeadScale(entry, _isNucHidden(entry.nuc, entry._copy ?? 0) ? 0 : _beadScale)
      }
      for (const entry of fluoroEntries) {
        _setBeadScale(entry, _isNucHidden(entry.nuc, entry._copy ?? 0) ? 0 : _beadScale)
      }
      for (const entry of coneEntries) {
        if (entry.isCrossHelix) continue
        _setConeXZScale(entry, _isNucHidden(entry.fromNuc) ? 0 : CONE_RADIUS)
      }
      for (const entry of slabEntries) {
        const hidden = _isNucHidden(entry.nuc, entry._copy ?? 0)
        _tMatrix.compose(
          entry.center, entry.quat,
          hidden
            ? _tScale.set(0, 0, 0)
            : _tScale.set(slabParams.length, slabParams.width, slabParams.thickness),
        )
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      if (slabEntries.length) iSlabs.instanceMatrix.needsUpdate = true
      _refreshSlabConnectors()
      _ensureAlphaInstalled()
      if (_repActive) _applyRepOverrides(); else _applyAlphaChannel()
    },

    /** Temporarily suppress complete helices while an authoritative structural
     * partial patch is rendered by a small overlay controller. Nucleotide
     * instances use the existing hidden-key machinery; axis meshes need an
     * explicit visibility gate because they are ordinary Mesh objects.
     * Passing an empty set restores the caller's normal hidden-nucleotide set
     * separately and reapplies the current shaft mode. */
    setStructuralHelicesSuppressed(ids) {
      const hidden = ids instanceof Set ? ids : new Set(ids ?? [])
      if (!hidden.size && _structuralCylSaved.length) {
        for (const { mesh, idx, matrix } of _structuralCylSaved) mesh.setMatrixAt(idx, matrix)
        for (const mesh of new Set(_structuralCylSaved.map(x => x.mesh))) {
          mesh.instanceMatrix.needsUpdate = true
        }
        _structuralCylSaved = []
      } else if (hidden.size && !_structuralCylSaved.length) {
        const suppress = (data, meshOf, helixOf = d => d.helixId) => {
          for (const d of data) {
            if (!hidden.has(helixOf(d))) continue
            const mesh = meshOf(d), idx = d.cylIdx
            if (!mesh || idx == null) continue
            const matrix = new THREE.Matrix4()
            mesh.getMatrixAt(idx, matrix)
            _structuralCylSaved.push({ mesh, idx, matrix })
            mesh.setMatrixAt(idx, new THREE.Matrix4().makeScale(0, 0, 0))
            mesh.instanceMatrix.needsUpdate = true
          }
        }
        suppress(_domainCylData, () => iHelixCylinders)
        suppress(_overhangCylData, d => _ovhgCylMesh(d))
        suppress(_bindingCylData, () => iLinkerBindingCylinders)
      }
      for (const arrow of axisArrows) {
        if (!hidden.has(arrow.helixId)) continue
        if (arrow.shaft) arrow.shaft.visible = false
        if (arrow.straightShaft) arrow.straightShaft.visible = false
        for (const seg of arrow.segments ?? []) {
          if (seg.mesh) seg.mesh.visible = false
          if (seg.tubeMesh) seg.tubeMesh.visible = false
        }
      }
      if (!hidden.size) _applyShaftModeVisibility(_currentShaftMode)
    },

    /**
     * Show or hide all extension beads and fluorophores.
     * Used by the extensionLocations toolFilter toggle.
     */
    setExtensionsVisible(visible) {
      const s = visible ? 1 : 0
      for (const entry of backboneEntries) {
        if (!entry.nuc.helix_id?.startsWith('__ext_')) continue
        _setBeadScale(entry, s)
      }
      for (const entry of fluoroEntries) {
        _setBeadScale(entry, s)
      }
    },

    /**
     * Log a comparison of each cone's rendered midpoint vs the midpoint
     * implied by its two backbone-bead entry.pos values.
     *
     * Call before and after a cluster rotation to see which cones drift.
     * Rows where err_nm > 0 indicate a stale cone matrix that doesn't match
     * the bead positions it's supposed to connect.
     *
     * @param {string} label  Prefix for the console group (e.g. "BEFORE", "AFTER-XB")
     */
    logConeDebug(label = '') {
      const _tmp = new THREE.Vector3()
      const rows = []
      let mismatchCount = 0

      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue

        _tmp.addVectors(fe.pos, te.pos).multiplyScalar(0.5)
        const err = cone.midPos.distanceTo(_tmp)

        const fromH = cone.fromNuc.helix_id
        const toH   = cone.toNuc.helix_id
        const isCross = fromH !== toH

        // Include cross-helix cones always; include intra-helix only if mismatch
        if (err > 5e-4 || isCross) {
          mismatchCount += err > 5e-4 ? 1 : 0
          rows.push({
            type:         isCross ? 'CROSS' : 'intra',
            from:         `${fromH.length > 16 ? fromH.slice(-12) : fromH}:${cone.fromNuc.bp_index}:${cone.fromNuc.direction[0]}`,
            to:           `${toH.length > 16 ? toH.slice(-12) : toH}:${cone.toNuc.bp_index}:${cone.toNuc.direction[0]}`,
            fromPos:      `(${fe.pos.x.toFixed(3)}, ${fe.pos.y.toFixed(3)}, ${fe.pos.z.toFixed(3)})`,
            toPos:        `(${te.pos.x.toFixed(3)}, ${te.pos.y.toFixed(3)}, ${te.pos.z.toFixed(3)})`,
            midExpected:  `(${_tmp.x.toFixed(3)}, ${_tmp.y.toFixed(3)}, ${_tmp.z.toFixed(3)})`,
            midActual:    `(${cone.midPos.x.toFixed(3)}, ${cone.midPos.y.toFixed(3)}, ${cone.midPos.z.toFixed(3)})`,
            err_nm:       err.toFixed(5),
          })
        }
      }

      const tag = label ? `[ConeDebug:${label}]` : '[ConeDebug]'
      console.group(`${tag}  ${mismatchCount} mismatches / ${coneEntries.length} total cones`)
      if (rows.length) console.table(rows)
      else console.log('No XB cones and no intra-helix mismatches.')
      console.groupEnd()
    },
  }
}
