/**
 * physics/displayState.js — fast-mode helix-segment particle overlay.
 *
 * Responsibilities:
 *  - Build/dispose an InstancedMesh of segment spheres + LineSegments backbone
 *    for the fast-mode XPBD particle system.
 *  - Dim canonical geometry to 25% opacity while fast physics is active;
 *    restore on deactivate.
 *  - Per-frame lerp: currentPos → targetPos at LERP_RATE per frame.
 *  - Color-code particles:
 *      normal dsDNA segment  → steel blue  #4682B4
 *      skip-affected segment → orange      #FF8C00  (not yet tracked; placeholder)
 *      loop joint particle   → bright green #00FF7F
 *      high-strain segment   → red         #FF2020  (residual > 0.5 nm)
 *
 * Usage:
 *   const fastDisplay = initFastPhysicsDisplay(scene, designRenderer)
 *   fastDisplay.start(particles)          // build mesh from initial particle list
 *   fastDisplay.onUpdate(frame, conv, particles, residuals) // called per WS frame
 *   fastDisplay.tick()                    // call every animation frame
 *   fastDisplay.stop()                    // dispose mesh, restore opacity
 */

import * as THREE from 'three'

const LERP_RATE     = 0.10   // fraction of gap closed per animation frame
const GHOST_OPACITY = 0.25   // canonical geometry opacity while fast physics is on
const STRAIN_CUTOFF = 0.5    // nm residual above which segment is "high-strain"
const SPHERE_RADIUS = 0.8    // nm — roughly DNA helix cross-section (2 nm diameter)

// Particle colours
const _COL_NORMAL = new THREE.Color(0x4682B4)  // steel blue
const _COL_SKIP   = new THREE.Color(0xFF8C00)  // orange  (reserved)
const _COL_LOOP   = new THREE.Color(0x00FF7F)  // bright green
const _COL_STRAIN = new THREE.Color(0xFF2020)  // red     (reserved)

// Shared geometry (created once; re-used across start/stop cycles)
const _GEO = new THREE.SphereGeometry(SPHERE_RADIUS, 8, 6)

// Backbone line material (semi-transparent light blue)
const _LINE_MAT = new THREE.LineBasicMaterial({
  color: 0x88aacc,
  transparent: true,
  opacity: 0.6,
})

/**
 * Parse a particle ID into [helix_id, sort_key] for ordering within a helix.
 * IDs:  "{helix_id}_s{N}"  or  "{helix_id}_loop_{N}_{M}"
 */
function _parseParticle(id) {
  let m = id.match(/^(.+)_s(\d+)$/)
  if (m) return [m[1], parseInt(m[2]) * 2]
  m = id.match(/^(.+)_loop_(\d+)_\d+$/)
  if (m) return [m[1], parseInt(m[2]) * 2 + 1]
  return [id, 0]
}

/**
 * Build a sorted list of [idA, idB] backbone connection pairs from a particle list.
 * Adjacent particles within the same helix are connected.
 */
function _buildBackbonePairs(particles) {
  const byHelix = new Map()
  for (const p of particles) {
    const [hid, key] = _parseParticle(p.id)
    if (!byHelix.has(hid)) byHelix.set(hid, [])
    byHelix.get(hid).push({ id: p.id, key })
  }
  const pairs = []
  for (const ps of byHelix.values()) {
    ps.sort((a, b) => a.key - b.key)
    for (let k = 0; k + 1 < ps.length; k++) {
      pairs.push([ps[k].id, ps[k + 1].id])
    }
  }
  return pairs
}

/**
 * Initialise the fast-physics display overlay.
 *
 * @param {THREE.Scene}  scene
 * @param {{ setToolOpacity: function }} designRenderer
 * @returns {{ start, stop, onUpdate, tick, isActive: boolean }}
 */
export function initFastPhysicsDisplay(scene, designRenderer) {
  let _mesh     = null   // THREE.InstancedMesh  — spheres
  let _lines    = null   // THREE.LineSegments   — backbone connections
  let _pairs    = []     // Array<[idA, idB]>    — connection pairs
  let _N        = 0
  let _active   = false

  // Maps: particle id → flat index / current pos / target pos
  const _idx = new Map()
  const _cur = new Map()   // id → [x,y,z]  (lerped, used for rendering)
  const _tgt = new Map()   // id → [x,y,z]  (latest from solver)

  // Sets for special particle types
  const _isJoint = new Set()

  // Working dummy for matrix updates
  const _dummy = new THREE.Object3D()

  // Crossover residuals (most recent frame)
  let _residuals = {}

  // ── Internal helpers ──────────────────────────────────────────────────────

  function _colorFor(id) {
    if (_isJoint.has(id)) return _COL_LOOP
    return _COL_NORMAL
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Build sphere mesh + backbone line mesh from an initial particle list.
   *
   * @param {Array<{id: string, pos: [x,y,z], orient: [qx,qy,qz,qw]}>} particles
   */
  function start(particles) {
    stop()   // clean up any previous state

    _N = particles.length
    if (_N === 0) return

    _active = true
    _idx.clear(); _cur.clear(); _tgt.clear(); _isJoint.clear()

    // ── Sphere instanced mesh ─────────────────────────────────────────────
    const mat = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.88 })
    _mesh = new THREE.InstancedMesh(_GEO, mat, _N)
    _mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)

    for (let i = 0; i < _N; i++) {
      const p = particles[i]
      _idx.set(p.id, i)

      const pos = p.pos.slice()
      _cur.set(p.id, pos)
      _tgt.set(p.id, pos.slice())

      if (p.id.includes('_loop_')) _isJoint.add(p.id)

      _dummy.position.set(pos[0], pos[1], pos[2])
      _dummy.scale.setScalar(_isJoint.has(p.id) ? 0.65 : 1.0)
      _dummy.updateMatrix()
      _mesh.setMatrixAt(i, _dummy.matrix)

      // Use the documented setColorAt API for reliable per-instance color
      _mesh.setColorAt(i, _colorFor(p.id))
    }

    _mesh.instanceMatrix.needsUpdate = true
    if (_mesh.instanceColor) _mesh.instanceColor.needsUpdate = true
    scene.add(_mesh)

    // ── Backbone line segments ────────────────────────────────────────────
    _pairs = _buildBackbonePairs(particles)
    const linePos = new Float32Array(_pairs.length * 6)  // 2 verts × 3 floats per pair

    for (let k = 0; k < _pairs.length; k++) {
      const [idA, idB] = _pairs[k]
      const a = _cur.get(idA)
      const b = _cur.get(idB)
      if (a && b) {
        linePos[k * 6]     = a[0]; linePos[k * 6 + 1] = a[1]; linePos[k * 6 + 2] = a[2]
        linePos[k * 6 + 3] = b[0]; linePos[k * 6 + 4] = b[1]; linePos[k * 6 + 5] = b[2]
      }
    }

    const lineGeo = new THREE.BufferGeometry()
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePos, 3))
    _lines = new THREE.LineSegments(lineGeo, _LINE_MAT)
    scene.add(_lines)

    // Dim canonical geometry
    designRenderer.setToolOpacity(GHOST_OPACITY)
  }

  /**
   * Called each time a `physics_update` frame arrives from the WebSocket.
   *
   * @param {number}  frame
   * @param {boolean} converged
   * @param {Array<{id, pos, orient}>} particles
   * @param {Object<string, number>}   residuals  xo_N → nm residual
   */
  function onUpdate(frame, converged, particles, residuals) {
    _residuals = residuals ?? {}

    for (const p of particles) {
      const t = _tgt.get(p.id)
      if (t) {
        t[0] = p.pos[0]; t[1] = p.pos[1]; t[2] = p.pos[2]
      }
    }
  }

  /**
   * Called every animation frame.  Lerps current → target and updates meshes.
   */
  function tick() {
    if (!_mesh || !_active || _N === 0) return

    for (const [id, tgt] of _tgt) {
      const cur = _cur.get(id)
      if (!cur) continue
      cur[0] += (tgt[0] - cur[0]) * LERP_RATE
      cur[1] += (tgt[1] - cur[1]) * LERP_RATE
      cur[2] += (tgt[2] - cur[2]) * LERP_RATE

      const i = _idx.get(id)
      if (i !== undefined) {
        _dummy.position.set(cur[0], cur[1], cur[2])
        _dummy.scale.setScalar(_isJoint.has(id) ? 0.65 : 1.0)
        _dummy.updateMatrix()
        _mesh.setMatrixAt(i, _dummy.matrix)
      }
    }
    _mesh.instanceMatrix.needsUpdate = true

    // Update line segment endpoints
    if (_lines && _pairs.length > 0) {
      const posAttr = _lines.geometry.attributes.position
      for (let k = 0; k < _pairs.length; k++) {
        const [idA, idB] = _pairs[k]
        const a = _cur.get(idA)
        const b = _cur.get(idB)
        if (a && b) {
          posAttr.setXYZ(k * 2,     a[0], a[1], a[2])
          posAttr.setXYZ(k * 2 + 1, b[0], b[1], b[2])
        }
      }
      posAttr.needsUpdate = true
    }
  }

  /**
   * Remove the overlay meshes and restore canonical geometry opacity.
   */
  function stop() {
    if (_mesh) {
      _mesh.material.dispose()
      scene.remove(_mesh)
      _mesh.dispose()
      _mesh = null
    }
    if (_lines) {
      _lines.geometry.dispose()
      scene.remove(_lines)
      _lines = null
    }
    _active    = false
    _N         = 0
    _pairs     = []
    _residuals = {}
    designRenderer.setToolOpacity(1.0)
  }

  return {
    start,
    stop,
    onUpdate,
    tick,
    get isActive() { return _active },
  }
}
