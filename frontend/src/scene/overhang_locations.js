/**
 * Overhang Locations overlay.
 *
 * For each staple 5′/3′ end (nick), finds all honeycomb-neighboring cells
 * that are unoccupied (no helix placed there) and draws an arrow pointing
 * from the nick's backbone bead toward the vacant cell's XY centre.
 *
 * These arrows show the user where overhangs can be extruded without
 * clashing with the existing structure.
 *
 * Usage:
 *   const ol = initOverhangLocations(scene)
 *   ol.rebuild(design, geometry)
 *   ol.setVisible(bool)
 *   ol.applyDeformLerp(straightPosMap, straightAxesMap, t)
 *   ol.applyUnfoldOffsets(helixOffsets, t, straightAxesMap)
 *   ol.dispose()
 */

import * as THREE from 'three'
import { SQUARE_HELIX_SPACING, SQUARE_TWIST_PER_BP_RAD } from '../constants.js'

// Module-level scratch for cluster transform updates (avoid per-frame allocation).
const _olV = new THREE.Vector3()

// ── Constants ─────────────────────────────────────────────────────────────────

// Honeycomb lattice geometry (must match backend/core/constants.py)
const LATTICE_R   = 1.125                        // nm
const HC_COL_PITCH  = LATTICE_R * Math.sqrt(3)  // ≈ 1.9486 nm
const HC_ROW_PITCH  = 3.0 * LATTICE_R           // = 3.375 nm (cadnano2: 3 × radius)
const HC_SPACING    = 2.0 * LATTICE_R           // = 2.25 nm (helix centre-to-centre distance)
const SPACING_EPS   = 0.12                       // tolerance for distance match

// Arrow appearance
const ARROW_COLOR     = 0x00e5ff   // bright cyan
const ARROW_LENGTH    = 2.2        // nm — total arrow length (~1× helix spacing)
const ARROW_HEAD_LEN  = 0.7        // nm — cone portion
const ARROW_HEAD_W    = 0.3        // nm — cone base radius

// ── Lattice detection ─────────────────────────────────────────────────────────

function _isSquareLattice(design) {
  const h = design?.helices?.[0]
  return h ? Math.abs(h.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-4 : false
}

// ── Honeycomb geometry helpers ────────────────────────────────────────────────

// cadnano2: x = col × COL_PITCH, y = row × ROW_PITCH + (R if (row+col) odd else 0)
function _hcCellXY(row, col) {
  const x   = col * HC_COL_PITCH
  const odd = (((row + col) % 2) + 2) % 2   // 1 if odd parity, 0 if even
  const y   = row * HC_ROW_PITCH + (odd ? LATTICE_R : 0)
  return [x, y]
}

// cadnano2: all cells are valid (no holes)
function _hcIsValid(_row, _col) { return true }

// ── Square lattice geometry helpers ──────────────────────────────────────────

function _sqCellXY(row, col) {
  return [col * SQUARE_HELIX_SPACING, row * SQUARE_HELIX_SPACING]
}

// ── Neighbor search ───────────────────────────────────────────────────────────

const _Z_EPS = 0.2   // nm — half a base-pair tolerance

/**
 * Return all vacant neighbors of (row, col) that have no helix covering z_nick.
 * Uses the appropriate geometry for the given lattice type.
 */
function _vacantNeighborsAtZ(row, col, cellZMap, z_nick, sq) {
  const cellXY   = sq ? _sqCellXY   : _hcCellXY
  const isValid  = sq ? () => true   : _hcIsValid
  const spacing  = sq ? SQUARE_HELIX_SPACING : HC_SPACING
  const [x0, y0] = cellXY(row, col)

  // Square lattice: 4 cardinal neighbors only.
  // Honeycomb: full 3×3 neighborhood (diagonal cells are also direct neighbors).
  const deltas = sq
    ? [[-1, 0], [1, 0], [0, -1], [0, 1]]
    : [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]]

  const result = []
  for (const [dr, dc] of deltas) {
    const nr = row + dr, nc = col + dc
    if (!isValid(nr, nc)) continue

    const ranges = cellZMap.get(`${nr},${nc}`)
    if (ranges) {
      const blocked = ranges.some(r => z_nick >= r.zMin - _Z_EPS && z_nick <= r.zMax + _Z_EPS)
      if (blocked) continue
    }

    const [x1, y1] = cellXY(nr, nc)
    const dist = Math.hypot(x1 - x0, y1 - y0)
    if (Math.abs(dist - spacing) < SPACING_EPS) {
      result.push({ row: nr, col: nc, x: x1, y: y1 })
    }
  }
  return result
}

/** Create a THREE.ArrowHelper pointing in direction dir from origin. */
function _makeArrow(origin, dir) {
  const arrow = new THREE.ArrowHelper(dir, origin, ARROW_LENGTH, ARROW_COLOR, ARROW_HEAD_LEN, ARROW_HEAD_W)
  arrow.line.material.depthTest = false
  arrow.line.material.transparent = true
  arrow.line.material.opacity = 0.88
  arrow.cone.material.depthTest = false
  arrow.cone.material.transparent = true
  arrow.cone.material.opacity = 0.88
  arrow.renderOrder = 11
  return arrow
}

// ── Main export ───────────────────────────────────────────────────────────────

export function initOverhangLocations(scene) {
  const _group = new THREE.Group()
  _group.renderOrder = 11
  scene.add(_group)

  let _visible = false

  /**
   * Per-arrow entry:
   *   { helixId, bpIndex, direction, isFivePrime, neighborRow, neighborCol,
   *     frac, pos3D, arrow }
   *
   * pos3D       is the backbone position at rebuild time (deformed / geometric).
   * frac        is bpIndex / helix.length_bp — used for deform lerp fallback.
   * isFivePrime / neighborRow / neighborCol are passed to the extrude API.
   */
  let _entries = []

  // Map from ArrowHelper cone mesh → entry, for raycasting.
  const _coneMap = new Map()

  // ── Rebuild ────────────────────────────────────────────────────────────────

  /**
   * @param {object|null} design
   * @param {Array|null}  geometry   nucleotide position list (design-local frame)
   * @param {object}      [opts]
   * @param {object|null} [opts.parentGroup]  Three.Group to attach arrows to.
   *   In design mode pass null/omit → arrows are parented to the top-level
   *   scene. In assembly mode pass the active PartInstance's group → arrows
   *   inherit the instance transform and are rendered in world space without
   *   per-arrow transform math.
   * @param {string|null} [opts.instanceId]   Tag stamped onto each entry. Click
   *   handlers branch on this to route the extrude to the right backend route.
   */
  function rebuild(design, geometry, opts = {}) {
    const parentGroup = opts.parentGroup ?? null
    const instanceId  = opts.instanceId  ?? null
    // Re-parent _group to the correct parent (instance group in assembly mode,
    // scene in design mode). Three.js handles removing-from-old-parent in add().
    const desiredParent = parentGroup ?? scene
    if (_group.parent !== desiredParent) desiredParent.add(_group)

    for (const child of [..._group.children]) _group.remove(child)
    _entries = []
    _coneMap.clear()
    if (!design || !geometry) return

    // Build helix lookup and per-cell Z-range map.
    // Row/col live on helix.grid_pos for every helix that has lattice context:
    // native, caDNAno, and scadnano importers all populate it; legacy native
    // files get it back-filled from the h_XY_{r}_{c} ID pattern by the Helix
    // model validator. We only parse the ID as a last-resort fallback.
    const sq       = _isSquareLattice(design)
    const cellXY   = sq ? _sqCellXY : _hcCellXY
    const helixMap  = new Map()   // id → { row, col, x, y, length_bp }
    const cellZMap  = new Map()   // "row,col" → [{zMin, zMax}]
    const _ID_RE = /^h_\w+_(-?\d+)_(-?\d+)$/

    function _rowColForHelix(h) {
      if (Array.isArray(h.grid_pos) && h.grid_pos.length === 2) {
        return [h.grid_pos[0], h.grid_pos[1]]
      }
      const m = _ID_RE.exec(h.id)
      return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null
    }

    // Cluster transform map: helix_id → { q, invQ, pivot, trans }
    //   q    — forward quaternion (local → world)
    //   invQ — inverse quaternion (world → local)
    //   pivot, trans — as THREE.Vector3
    // Used to: (a) un-transform backbone positions to the local frame for lattice
    // calculations (vacant-neighbor Z check, radial dot-product threshold) and
    // (b) rotate the resulting direction to world space.
    // rotation stored as [qx, qy, qz, qw] (Three.js convention).
    const clusterXfMap = new Map()
    for (const ct of (design.cluster_transforms ?? [])) {
      const q    = new THREE.Quaternion(ct.rotation[0], ct.rotation[1], ct.rotation[2], ct.rotation[3])
      const invQ = q.clone().invert()
      const pivot = new THREE.Vector3(ct.pivot[0], ct.pivot[1], ct.pivot[2])
      const trans = new THREE.Vector3(ct.translation[0], ct.translation[1], ct.translation[2])
      for (const hid of ct.helix_ids) clusterXfMap.set(hid, { q, invQ, pivot, trans })
    }

    for (const h of design.helices) {
      const rc = _rowColForHelix(h)
      if (!rc) continue
      const [row, col] = rc
      // Use the actual axis XY centre from the design response rather than
      // recomputing from row/col.  This keeps native and caDNAno-imported
      // designs consistent (caDNAno negates the X axis).
      const x = h.axis_start.x
      const y = h.axis_start.y
      // Formula-derived cell centre — used only to compute neighbor directions
      // for _vacantNeighborsAtZ (which needs consistent XY for both helix and
      // candidate cell).  Stored separately so the radial test uses real coords.
      const [cx, cy] = cellXY(row, col)
      helixMap.set(h.id, { row, col, x, y, cx, cy, length_bp: h.length_bp })
      const key  = `${row},${col}`
      const zMin = Math.min(h.axis_start.z, h.axis_end.z)
      const zMax = Math.max(h.axis_start.z, h.axis_end.z)
      if (!cellZMap.has(key)) cellZMap.set(key, [])
      cellZMap.get(key).push({ zMin, zMax })
    }

    // Iterate over all staple 5′/3′ nuc positions
    for (const nuc of geometry) {
      if (nuc.strand_type !== 'staple') continue
      if (!nuc.is_five_prime && !nuc.is_three_prime) continue

      const helix = helixMap.get(nuc.helix_id)
      if (!helix) continue

      const [px, py, pz] = nuc.backbone_position

      // For cluster-transformed helices, un-transform the backbone position back to
      // the pre-rotation local frame before all lattice-based calculations.
      // Formula: p_local = R^{-1} * (p_world − pivot − trans) + pivot
      // This ensures the Z-range check, radial dot-product, and neighbor direction are
      // all computed in the lattice frame, giving the correct arrow count and base direction.
      const xf = clusterXfMap.get(nuc.helix_id)
      let lx = px, ly = py, lz = pz
      if (xf) {
        _olV.set(px - xf.pivot.x - xf.trans.x, py - xf.pivot.y - xf.trans.y, pz - xf.pivot.z - xf.trans.z)
              .applyQuaternion(xf.invQ)
        lx = _olV.x + xf.pivot.x
        ly = _olV.y + xf.pivot.y
        lz = _olV.z + xf.pivot.z
      }

      const vacants = _vacantNeighborsAtZ(helix.row, helix.col, cellZMap, lz, sq)
      if (!vacants.length) continue

      // Radial vector in local frame — compare local backbone XY against pre-rotation axis.
      const rx = lx - helix.x
      const ry = ly - helix.y
      const rLen = Math.hypot(rx, ry)

      const origin = new THREE.Vector3(px, py, pz)  // world-space arrow origin

      for (const v of vacants) {
        // Arrow direction in local frame (from formula cell centre → vacant cell centre).
        const dx = v.x - helix.cx
        const dy = v.y - helix.cy
        const len = Math.hypot(dx, dy)
        if (len < 0.01) continue

        // Dot-product test in local frame — bead must face toward the vacant cell.
        // Threshold 0.75 ≈ cos(41°).
        if (rLen > 0.01) {
          const dot = (rx * dx + ry * dy) / (rLen * len)
          if (dot < 0.75) continue
        }

        const localDir = new THREE.Vector3(dx / len, dy / len, 0)  // pre-rotation direction
        const dir = localDir.clone()
        // Rotate local-frame direction to world space via the committed cluster quaternion.
        if (xf) dir.applyQuaternion(xf.q).normalize()

        const arrow = _makeArrow(origin, dir)
        _group.add(arrow)

        const frac  = helix.length_bp > 0 ? (nuc.bp_index - helix.bp_start) / helix.length_bp : 0
        const entry = {
          helixId:      nuc.helix_id,
          bpIndex:      nuc.bp_index,
          direction:    nuc.direction,
          isFivePrime:  nuc.is_five_prime,
          neighborRow:  v.row,
          neighborCol:  v.col,
          instanceId,
          frac,
          pos3D: origin.clone(),
          dir:   dir.clone(),   // current world-space direction (rotated with cluster)
          cbPos: null,          // snapshot set by captureClusterBase
          cbDir: null,
          arrow,
          // ── Debug fields (set at rebuild, frozen) ──────────────────────────
          _worldPos:  origin.clone(),          // world-space backbone position
          _localPos:  new THREE.Vector3(lx, ly, lz), // un-transformed local-frame position
          _localDir:  localDir.clone(),        // direction in local (lattice) frame
          _dot:       rLen > 0.01 ? (rx * dx + ry * dy) / (rLen * len) : null,
          _inCluster: !!xf,
          _xfQ:       xf ? { x: xf.q.x, y: xf.q.y, z: xf.q.z, w: xf.q.w } : null,
          _xfPivot:   xf ? xf.pivot.clone() : null,
          _xfTrans:   xf ? xf.trans.clone() : null,
        }
        _entries.push(entry)
        _coneMap.set(arrow.cone, entry)
      }
    }

    _group.visible = _visible
    console.log(`[OverhangLocations] rebuilt: ${_entries.length} arrows`)
  }

  // ── Deform lerp ────────────────────────────────────────────────────────────

  /**
   * Lerp arrow origins between straight (t=0) and deformed (t=1) geometry.
   * Arrow directions are always XY and don't change with deformation.
   *
   * @param {Map<string,THREE.Vector3>} straightPosMap  key "hid:bp:dir"
   * @param {Map}                       _straightAxesMap  (unused — reserved)
   * @param {number}                    t  0=straight, 1=deformed
   */
  function applyDeformLerp(straightPosMap, _straightAxesMap, t) {
    for (const e of _entries) {
      const sp = straightPosMap?.get(`${e.helixId}:${e.bpIndex}:${e.direction}`)
      if (!sp) continue
      const lx = sp.x + (e.pos3D.x - sp.x) * t
      const ly = sp.y + (e.pos3D.y - sp.y) * t
      const lz = sp.z + (e.pos3D.z - sp.z) * t
      e.arrow.position.set(lx, ly, lz)
    }
  }

  // ── Unfold offsets ──────────────────────────────────────────────────────────

  /**
   * Translate arrows by their helix's unfold offset.
   *
   * @param {Map<string,THREE.Vector3>} helixOffsets
   * @param {number}                    t  lerp 0→1
   * @param {Map}                       _straightAxesMap  (unused)
   */
  function applyUnfoldOffsets(helixOffsets, t, _straightAxesMap) {
    for (const e of _entries) {
      const off = helixOffsets.get(e.helixId)
      const ox = off ? off.x * t : 0
      const oy = off ? off.y * t : 0
      const oz = off ? off.z * t : 0
      e.arrow.position.set(e.pos3D.x + ox, e.pos3D.y + oy, e.pos3D.z + oz)
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  function setVisible(v) {
    _visible = v
    _group.visible = v
  }

  function isVisible() { return _visible }

  /**
   * Raycast against overhang arrow cones.
   * @param {THREE.Raycaster} raycaster
   * @returns {object|null} The matching entry, or null if none hit.
   */
  function hitTest(raycaster) {
    if (!_visible || _entries.length === 0) return null
    const cones = [..._coneMap.keys()]
    const hits  = raycaster.intersectObjects(cones)
    if (!hits.length) return null
    return _coneMap.get(hits[0].object) ?? null
  }

  /**
   * Log current arrow state to the console for debugging.
   * Call via  window.nadocOverhangSnap('label')  from the browser console.
   *
   * Columns:
   *   helix     — last 16 chars of helix_id
   *   bp        — bp_index
   *   5p        — is_five_prime
   *   inCluster — whether a cluster transform was applied
   *   wPos      — world-space arrow origin (x,y,z at time of call)
   *   localPos  — un-transformed local-frame position used for lattice checks (at rebuild)
   *   dot       — dot-product used for the 0.75 threshold (at rebuild)
   *   localDir  — direction in lattice frame (at rebuild)
   *   worldDir  — direction in world frame (current)
   *   q         — cluster quaternion applied (at rebuild), or "—"
   *   cbPos     — drag-start snapshot position, or "—"
   *   cbDir     — drag-start snapshot direction, or "—"
   */
  function logOverhangDebug(label = '') {
    const tag = `[OverhangDebug:${label}]`
    const fmt = v => v != null ? v.toFixed(3) : '—'
    const fmtV = v => v ? `(${v.x.toFixed(3)}, ${v.y.toFixed(3)}, ${v.z.toFixed(3)})` : '—'
    const fmtQ = q => q ? `[${q.x.toFixed(3)},${q.y.toFixed(3)},${q.z.toFixed(3)},${q.w.toFixed(3)}]` : '—'
    const rows = _entries.map(e => ({
      helix:     e.helixId.slice(-16),
      bp:        e.bpIndex,
      '5p':      e.isFivePrime,
      inCluster: e._inCluster,
      wPos:      fmtV(e.arrow.position),
      localPos:  fmtV(e._localPos),
      dot:       fmt(e._dot),
      localDir:  fmtV(e._localDir),
      worldDir:  fmtV(e.dir),
      q:         fmtQ(e._xfQ),
      pivot:     fmtV(e._xfPivot),
      trans:     fmtV(e._xfTrans),
      cbPos:     fmtV(e.cbPos),
      cbDir:     fmtV(e.cbDir),
    }))
    const clusterCount = _entries.filter(e => e._inCluster).length
    console.group(`${tag}  ${_entries.length} arrows  (${clusterCount} in cluster)`)
    if (rows.length) console.table(rows)
    else console.log('No arrows.')
    console.groupEnd()
  }

  /**
   * Snapshot arrow positions and directions for the given cluster helices.
   * Must be called once at gizmo attach time before any drag begins.
   */
  function captureClusterBase(helixIds) {
    const helixSet = new Set(helixIds)
    for (const e of _entries) {
      if (!helixSet.has(e.helixId)) continue
      e.cbPos = e.arrow.position.clone()
      e.cbDir = e.dir.clone()
    }
    logOverhangDebug('DRAG-START')
  }

  /**
   * Apply an incremental cluster transform to arrow positions and directions.
   * Formula: pos' = R_incr*(cbPos − center) + dummyPos
   *          dir' = R_incr * cbDir  (normalised)
   *
   * @param {string[]}         helixIds
   * @param {THREE.Vector3}    centerVec    pivot at attach time
   * @param {THREE.Vector3}    dummyPosVec  current dummy position
   * @param {THREE.Quaternion} incrRotQuat  rotation since attach
   */
  function applyClusterTransform(helixIds, centerVec, dummyPosVec, incrRotQuat) {
    const helixSet = new Set(helixIds)
    for (const e of _entries) {
      if (!helixSet.has(e.helixId) || !e.cbPos || !e.cbDir) continue
      // Position
      _olV.copy(e.cbPos).sub(centerVec).applyQuaternion(incrRotQuat)
      e.arrow.position.set(_olV.x + dummyPosVec.x, _olV.y + dummyPosVec.y, _olV.z + dummyPosVec.z)
      // Direction
      _olV.copy(e.cbDir).applyQuaternion(incrRotQuat).normalize()
      e.dir.copy(_olV)
      e.arrow.setDirection(_olV)
    }
    logOverhangDebug('AFTER-TRANSFORM')
  }

  function clear() {
    for (const child of [..._group.children]) _group.remove(child)
    _entries = []
    _coneMap.clear()
  }

  function dispose() {
    clear()
    if (_group.parent) _group.parent.remove(_group)
  }

  return { rebuild, clear, setVisible, isVisible, hitTest, applyDeformLerp, applyUnfoldOffsets, captureClusterBase, applyClusterTransform, logOverhangDebug, dispose }
}
