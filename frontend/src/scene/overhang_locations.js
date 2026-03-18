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

// ── Constants ─────────────────────────────────────────────────────────────────

// Honeycomb lattice geometry (must match backend/core/constants.py)
const LATTICE_R   = 1.125                        // nm
const COL_PITCH   = LATTICE_R * Math.sqrt(3)     // ≈ 1.9486 nm
const ROW_PITCH   = 2.0 * LATTICE_R             // = 2.25 nm
const HELIX_SPACING = ROW_PITCH                  // = 2.25 nm
const SPACING_EPS   = 0.12                       // tolerance for distance match

// Arrow appearance
const ARROW_COLOR     = 0x00e5ff   // bright cyan
const ARROW_LENGTH    = 0.72       // nm — total arrow length
const ARROW_HEAD_LEN  = 0.26       // nm — cone portion
const ARROW_HEAD_W    = 0.11       // nm — cone base radius

// ── Geometry helpers ──────────────────────────────────────────────────────────

/** XY centre of a honeycomb cell in nm (matches backend honeycomb_position). */
function _cellXY(row, col) {
  const x = col * COL_PITCH
  const y = col % 2 === 0
    ? row * ROW_PITCH + LATTICE_R
    : row * ROW_PITCH
  return [x, y]
}

/** True if (row, col) is a valid (non-HOLE) honeycomb cell. */
function _isValid(row, col) {
  const colMod2 = ((col % 2) + 2) % 2          // safe for negative col
  return ((row + colMod2) % 3 + 3) % 3 !== 2
}

/**
 * Return all honeycomb neighbors of (row, col) that are:
 *   1. Valid (non-HOLE) cells
 *   2. At approximately HELIX_SPACING distance
 *   3. NOT in occupiedSet
 */
function _vacantNeighbors(row, col, occupiedSet) {
  const [x0, y0] = _cellXY(row, col)
  const result = []
  for (let dr = -1; dr <= 1; dr++) {
    for (let dc = -1; dc <= 1; dc++) {
      if (dr === 0 && dc === 0) continue
      const nr = row + dr, nc = col + dc
      if (!_isValid(nr, nc)) continue
      if (occupiedSet.has(`${nr},${nc}`)) continue
      const [x1, y1] = _cellXY(nr, nc)
      const dist = Math.hypot(x1 - x0, y1 - y0)
      if (Math.abs(dist - HELIX_SPACING) < SPACING_EPS) {
        result.push({ row: nr, col: nc, x: x1, y: y1 })
      }
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
   *   { helixId, bpIndex, direction, frac, pos3D, arrow }
   *
   * pos3D is the backbone position at rebuild time (deformed / geometric).
   * frac  is bpIndex / helix.length_bp — used for deform lerp fallback.
   */
  let _entries = []

  // ── Rebuild ────────────────────────────────────────────────────────────────

  /**
   * @param {object|null} design
   * @param {Array|null}  geometry  nucleotide position list from store
   */
  function rebuild(design, geometry) {
    for (const child of [..._group.children]) _group.remove(child)
    _entries = []
    if (!design || !geometry) return

    // Build helix lookup and occupied set
    const helixMap  = new Map()   // id → { row, col, x, y, length_bp }
    const occupied  = new Set()   // "row,col"

    for (const h of design.helices) {
      const [x, y] = _cellXY(h.row, h.col)
      helixMap.set(h.id, { row: h.row, col: h.col, x, y, length_bp: h.length_bp })
      occupied.add(`${h.row},${h.col}`)
    }

    // Iterate over all staple 5′/3′ nuc positions
    for (const nuc of geometry) {
      if (nuc.strand_type !== 'staple') continue
      if (!nuc.is_five_prime && !nuc.is_three_prime) continue

      const helix = helixMap.get(nuc.helix_id)
      if (!helix) continue

      const vacants = _vacantNeighbors(helix.row, helix.col, occupied)
      if (!vacants.length) continue

      const [px, py, pz] = nuc.backbone_position
      const origin = new THREE.Vector3(px, py, pz)

      for (const v of vacants) {
        // Arrow direction: XY only (from helix centre → vacant cell centre)
        const dx = v.x - helix.x
        const dy = v.y - helix.y
        const len = Math.hypot(dx, dy)
        if (len < 0.01) continue
        const dir = new THREE.Vector3(dx / len, dy / len, 0)

        const arrow = _makeArrow(origin, dir)
        _group.add(arrow)

        const frac = helix.length_bp > 0 ? nuc.bp_index / helix.length_bp : 0
        _entries.push({
          helixId:   nuc.helix_id,
          bpIndex:   nuc.bp_index,
          direction: nuc.direction,
          frac,
          pos3D:  origin.clone(),
          arrow,
        })
      }
    }

    _group.visible = _visible
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

  function dispose() {
    for (const child of [..._group.children]) _group.remove(child)
    scene.remove(_group)
  }

  return { rebuild, setVisible, isVisible, applyDeformLerp, applyUnfoldOffsets, dispose }
}
