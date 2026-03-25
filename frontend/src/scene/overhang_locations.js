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

// ── Constants ─────────────────────────────────────────────────────────────────

// Honeycomb lattice geometry (must match backend/core/constants.py)
const LATTICE_R   = 1.125                        // nm
const HC_COL_PITCH  = LATTICE_R * Math.sqrt(3)  // ≈ 1.9486 nm
const HC_ROW_PITCH  = 2.0 * LATTICE_R           // = 2.25 nm
const HC_SPACING    = HC_ROW_PITCH               // = 2.25 nm
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

function _hcCellXY(row, col) {
  const x = col * HC_COL_PITCH
  const y = col % 2 === 0
    ? row * HC_ROW_PITCH + LATTICE_R
    : row * HC_ROW_PITCH
  return [x, y]
}

function _hcIsValid(row, col) {
  const colMod2 = ((col % 2) + 2) % 2
  return ((row + colMod2) % 3 + 3) % 3 !== 2
}

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
   * @param {Array|null}  geometry  nucleotide position list from store
   */
  function rebuild(design, geometry) {
    for (const child of [..._group.children]) _group.remove(child)
    _entries = []
    _coneMap.clear()
    if (!design || !geometry) return

    // Build helix lookup and per-cell Z-range map.
    // row/col are not serialised in the API response — parse them from the
    // helix ID, which has the form  h_{plane}_{row}_{col}  (e.g. h_XY_2_4).
    const sq       = _isSquareLattice(design)
    const cellXY   = sq ? _sqCellXY : _hcCellXY
    const helixMap  = new Map()   // id → { row, col, x, y, length_bp }
    const cellZMap  = new Map()   // "row,col" → [{zMin, zMax}]
    const _ID_RE = /^h_\w+_(-?\d+)_(-?\d+)$/

    for (const h of design.helices) {
      const m = _ID_RE.exec(h.id)
      if (!m) continue
      const row = parseInt(m[1], 10)
      const col = parseInt(m[2], 10)
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

      const vacants = _vacantNeighborsAtZ(helix.row, helix.col, cellZMap, pz, sq)
      if (!vacants.length) continue

      // Radial vector: direction the backbone bead points away from the helix
      // axis.  Use actual axis XY (helix.x/y = axis_start.x/y) so that the
      // dot-product test is correct for both native and caDNAno-imported designs.
      const rx = px - helix.x
      const ry = py - helix.y
      const rLen = Math.hypot(rx, ry)

      const origin = new THREE.Vector3(px, py, pz)

      for (const v of vacants) {
        // Arrow direction: XY only (from formula cell centre → vacant cell centre).
        // We use the formula-derived helix centre (helix.cx/cy) here so that the
        // direction is consistent with the neighbour coordinates returned by
        // _vacantNeighborsAtZ (which also uses the formula).
        const dx = v.x - helix.cx
        const dy = v.y - helix.cy
        const len = Math.hypot(dx, dy)
        if (len < 0.01) continue

        // Only emit an arrow if this backbone bead faces toward the vacant cell —
        // i.e. the bead is on the interface side, as required for a valid crossover.
        // Threshold 0.75 ≈ cos(41°), derived from backbone radius ~0.9 nm,
        // axis separation 2.25 nm, crossover reach 0.75 nm.
        if (rLen > 0.01) {
          const dot = (rx * dx + ry * dy) / (rLen * len)
          if (dot < 0.75) continue
        }

        const dir = new THREE.Vector3(dx / len, dy / len, 0)

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
          frac,
          pos3D: origin.clone(),
          arrow,
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

  function dispose() {
    for (const child of [..._group.children]) _group.remove(child)
    _coneMap.clear()
    scene.remove(_group)
  }

  return { rebuild, setVisible, isVisible, hitTest, applyDeformLerp, applyUnfoldOffsets, dispose }
}
