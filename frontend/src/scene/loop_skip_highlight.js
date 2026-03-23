/**
 * Loop/Skip highlight overlay.
 *
 * Renders coloured markers at every loop (+1) and skip (-1) position:
 *   Loop  (delta=+1) → orange ring around the two duplicate backbone beads
 *   Skip  (delta=-1) → red X cross at the axis point where the bead would be
 *
 * Positions follow the current view state:
 *   applyDeformLerp(straightPosMap, straightAxesMap, t)  — deform animation
 *   applyUnfoldOffsets(helixOffsets, t, straightAxesMap)  — unfold animation
 *
 * Usage:
 *   const lsh = initLoopSkipHighlight(scene)
 *   lsh.rebuild(design, geometry, helixAxes)  // helixAxes = store.currentHelixAxes
 *   lsh.setVisible(bool)
 *   lsh.applyDeformLerp(straightPosMap, straightAxesMap, t)
 *   lsh.applyUnfoldOffsets(helixOffsets, t, straightAxesMap)
 *   lsh.dispose()
 */

import * as THREE from 'three'

/**
 * Interpolate along a polyline (array of [x,y,z]) at a uniform parameter frac ∈ [0,1].
 * Treats each segment as having equal weight — appropriate when samples are at equal
 * bp-index steps (as produced by deformed_helix_axes with _AXIS_SAMPLE_STEP=7).
 */
function _samplePolyline(samples, frac) {
  if (!samples || samples.length === 0) return null
  if (samples.length === 1) return samples[0]
  const f = Math.max(0, Math.min(1, frac)) * (samples.length - 1)
  const i = Math.min(Math.floor(f), samples.length - 2)
  const u = f - i
  const a = samples[i], b = samples[i + 1]
  return [
    a[0] + (b[0] - a[0]) * u,
    a[1] + (b[1] - a[1]) * u,
    a[2] + (b[2] - a[2]) * u,
  ]
}

// Match helix_renderer.js BEAD_RADIUS = 0.10 nm
const LOOP_RING_R   = 0.20   // torus tube radius (nm)
const LOOP_TORUS_R  = 0.16   // torus major radius — wraps around the two beads
const SKIP_ARM      = 0.36   // half-length of each X arm (nm)
const SKIP_TUBE     = 0.08   // cylinder radius for X arms

const COL_LOOP = 0xff8800   // bright orange
const COL_SKIP = 0xff2222   // bright red

// Reusable geometries
const _GEO_TORUS  = new THREE.TorusGeometry(LOOP_TORUS_R, LOOP_RING_R, 8, 24)

// Skip X = two thin cylinders rotated ±45°
const _GEO_ARM = new THREE.CylinderGeometry(SKIP_TUBE, SKIP_TUBE, SKIP_ARM * 2, 6)
const _Q45A    = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0,  Math.PI / 4))
const _Q45B    = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, -Math.PI / 4))

function _makeMat(color) {
  return new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.85 })
}

export function initLoopSkipHighlight(scene) {
  const _group = new THREE.Group()
  _group.renderOrder = 10   // render on top
  scene.add(_group)

  let _visible = false

  /**
   * Per-marker entries — stored so applyDeformLerp / applyUnfoldOffsets can
   * move them without a full rebuild.
   *
   * Loop entry:  { type:'loop', helixId, bpIndex, frac, pos3D, mesh }
   * Skip entry:  { type:'skip', helixId, frac, pos3D, arm1, arm2 }
   *
   * pos3D is the DEFORMED position at the time of rebuild.
   * frac  is bpIndex / helix.length_bp — used to interpolate along the axis.
   */
  let _entries = []

  const _loopMat = _makeMat(COL_LOOP)
  const _skipMat = _makeMat(COL_SKIP)

  // ── Build ──────────────────────────────────────────────────────────────────

  /**
   * Rebuild all markers from current design + geometry.
   *
   * @param {object|null} design
   * @param {Array|null}  geometry     nucleotide position list
   * @param {object|null} helixAxes    store.currentHelixAxes  (deformed axes)
   */
  function rebuild(design, geometry, helixAxes) {
    for (const child of [..._group.children]) _group.remove(child)
    _entries = []
    if (!design || !geometry) return

    // Index geometry: "helix_id:bp_index" → list of backbone positions
    const geoMap = new Map()
    for (const nuc of geometry) {
      const key = `${nuc.helix_id}:${nuc.bp_index}`
      let arr = geoMap.get(key)
      if (!arr) { arr = []; geoMap.set(key, arr) }
      arr.push(nuc.backbone_position)
    }

    for (const helix of design.helices) {
      if (!helix.loop_skips?.length) continue

      const as = helix.axis_start
      const ae = helix.axis_end
      const axLen = Math.sqrt(
        (ae.x - as.x) ** 2 + (ae.y - as.y) ** 2 + (ae.z - as.z) ** 2,
      )

      // Deformed axis endpoints from the geometry API (arrays [x,y,z]).
      const dAx = helixAxes?.[helix.id] ?? null

      for (const ls of helix.loop_skips) {
        const frac = helix.length_bp > 0 ? (ls.bp_index - helix.bp_start) / helix.length_bp : 0

        if (ls.delta >= 1) {
          // ── Loop: torus at deformed backbone midpoint ──────────────────────
          const key = `${helix.id}:${ls.bp_index}`
          const positions = geoMap.get(key)
          let cx, cy, cz
          if (positions && positions.length >= 2) {
            cx = 0; cy = 0; cz = 0
            for (const p of positions) { cx += p[0]; cy += p[1]; cz += p[2] }
            cx /= positions.length; cy /= positions.length; cz /= positions.length
          } else if (axLen > 0) {
            cx = as.x + (ae.x - as.x) * frac
            cy = as.y + (ae.y - as.y) * frac
            cz = as.z + (ae.z - as.z) * frac
          } else {
            continue
          }
          const mesh = new THREE.Mesh(_GEO_TORUS, _loopMat)
          mesh.position.set(cx, cy, cz)
          _group.add(mesh)
          _entries.push({
            type: 'loop', helixId: helix.id, bpIndex: ls.bp_index, frac,
            pos3D: new THREE.Vector3(cx, cy, cz), mesh,
          })

        } else if (ls.delta <= -1) {
          // ── Skip: X at deformed axis point ────────────────────────────────
          let px, py, pz
          if (dAx) {
            // Use curved samples (CatmullRom spine) when available — same axis the
            // tube shaft follows.  Fall back to linear interpolation for straight helices.
            const samps = dAx.samples
            if (samps && samps.length > 2) {
              const p = _samplePolyline(samps, frac)
              px = p[0]; py = p[1]; pz = p[2]
            } else {
              const ds = dAx.start, de = dAx.end
              px = ds[0] + (de[0] - ds[0]) * frac
              py = ds[1] + (de[1] - ds[1]) * frac
              pz = ds[2] + (de[2] - ds[2]) * frac
            }
          } else if (axLen > 0) {
            px = as.x + (ae.x - as.x) * frac
            py = as.y + (ae.y - as.y) * frac
            pz = as.z + (ae.z - as.z) * frac
          } else {
            continue
          }

          const arm1 = new THREE.Mesh(_GEO_ARM, _skipMat)
          arm1.position.set(px, py, pz)
          arm1.quaternion.copy(_Q45A)
          const arm2 = new THREE.Mesh(_GEO_ARM, _skipMat)
          arm2.position.set(px, py, pz)
          arm2.quaternion.copy(_Q45B)
          _group.add(arm1, arm2)
          _entries.push({
            type: 'skip', helixId: helix.id, bpIndex: ls.bp_index, frac,
            pos3D: new THREE.Vector3(px, py, pz), arm1, arm2,
          })
        }
      }
    }

    _group.visible = _visible
  }

  // ── Deform lerp ────────────────────────────────────────────────────────────

  /**
   * Lerp all marker positions between straight (t=0) and deformed (t=1).
   *
   * @param {Map<string,THREE.Vector3>}                straightPosMap   key "hid:bp:dir"
   * @param {Map<string,{start:THREE.Vector3,end:THREE.Vector3}>} straightAxesMap
   * @param {number} t  0=straight, 1=deformed
   */
  function applyDeformLerp(straightPosMap, straightAxesMap, t) {
    for (const e of _entries) {
      let lx, ly, lz

      if (e.type === 'loop') {
        // Straight position: average FORWARD + REVERSE backbone positions.
        const spF = straightPosMap?.get(`${e.helixId}:${e.bpIndex}:FORWARD`)
        const spR = straightPosMap?.get(`${e.helixId}:${e.bpIndex}:REVERSE`)
        let sx, sy, sz
        if (spF && spR) {
          sx = (spF.x + spR.x) * 0.5; sy = (spF.y + spR.y) * 0.5; sz = (spF.z + spR.z) * 0.5
        } else if (spF || spR) {
          const sp = spF ?? spR; sx = sp.x; sy = sp.y; sz = sp.z
        } else {
          sx = e.pos3D.x; sy = e.pos3D.y; sz = e.pos3D.z
        }
        lx = sx + (e.pos3D.x - sx) * t
        ly = sy + (e.pos3D.y - sy) * t
        lz = sz + (e.pos3D.z - sz) * t
        e.mesh.position.set(lx, ly, lz)

      } else {
        // Skip: straight axis point → deformed axis point.
        const sa = straightAxesMap?.get(e.helixId)
        let sx, sy, sz
        if (sa) {
          sx = sa.start.x + (sa.end.x - sa.start.x) * e.frac
          sy = sa.start.y + (sa.end.y - sa.start.y) * e.frac
          sz = sa.start.z + (sa.end.z - sa.start.z) * e.frac
        } else {
          sx = e.pos3D.x; sy = e.pos3D.y; sz = e.pos3D.z
        }
        lx = sx + (e.pos3D.x - sx) * t
        ly = sy + (e.pos3D.y - sy) * t
        lz = sz + (e.pos3D.z - sz) * t
        e.arm1.position.set(lx, ly, lz)
        e.arm2.position.set(lx, ly, lz)
      }
    }
  }

  // ── Unfold offsets ─────────────────────────────────────────────────────────

  /**
   * Translate all markers by their helix's unfold offset.
   * Uses straight axis positions as base (same convention as blunt_ends).
   *
   * @param {Map<string,THREE.Vector3>}                             helixOffsets
   * @param {number}                                                t  lerp 0→1
   * @param {Map<string,{start:THREE.Vector3,end:THREE.Vector3}>}   straightAxesMap
   */
  function applyUnfoldOffsets(helixOffsets, t, straightAxesMap) {
    for (const e of _entries) {
      const off = helixOffsets.get(e.helixId)
      const ox = off ? off.x * t : 0
      const oy = off ? off.y * t : 0
      const oz = off ? off.z * t : 0

      let bx, by, bz
      const sa = straightAxesMap?.get(e.helixId)
      if (sa) {
        bx = sa.start.x + (sa.end.x - sa.start.x) * e.frac
        by = sa.start.y + (sa.end.y - sa.start.y) * e.frac
        bz = sa.start.z + (sa.end.z - sa.start.z) * e.frac
      } else {
        bx = e.pos3D.x; by = e.pos3D.y; bz = e.pos3D.z
      }

      const fx = bx + ox, fy = by + oy, fz = bz + oz
      if (e.type === 'loop') {
        e.mesh.position.set(fx, fy, fz)
      } else {
        e.arm1.position.set(fx, fy, fz)
        e.arm2.position.set(fx, fy, fz)
      }
    }
  }

  // ── Physics positions ───────────────────────────────────────────────────────

  /**
   * Move markers to follow XPBD backbone positions.
   * Called every physics frame while physicsMode is active.
   *
   * Loops: average FORWARD + REVERSE physics positions at the loop's bp_index.
   * Skips: same average at bp_index ± 1 (skipped bps have no backbone particle).
   *
   * @param {Array<{helix_id,bp_index,direction,backbone_position}>} updates
   */
  function applyPhysicsPositions(updates) {
    // Build lookup: "helix_id:bp_index:direction" → [x,y,z]
    const posMap = new Map()
    for (const u of updates) {
      posMap.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, u.backbone_position)
    }

    for (const e of _entries) {
      let px, py, pz

      if (e.type === 'loop') {
        const f = posMap.get(`${e.helixId}:${e.bpIndex}:FORWARD`)
        const r = posMap.get(`${e.helixId}:${e.bpIndex}:REVERSE`)
        if (f && r) {
          px = (f[0] + r[0]) * 0.5; py = (f[1] + r[1]) * 0.5; pz = (f[2] + r[2]) * 0.5
        } else if (f || r) {
          const p = f ?? r; px = p[0]; py = p[1]; pz = p[2]
        } else {
          continue  // no physics particle for this bp — leave unchanged
        }
        e.mesh.position.set(px, py, pz)

      } else {
        // Skip: the bp was deleted so no particle exists. Interpolate from neighbours.
        const candidates = []
        for (const dir of ['FORWARD', 'REVERSE']) {
          const prev = posMap.get(`${e.helixId}:${e.bpIndex - 1}:${dir}`)
          const next = posMap.get(`${e.helixId}:${e.bpIndex + 1}:${dir}`)
          if (prev && next) {
            candidates.push([(prev[0] + next[0]) * 0.5, (prev[1] + next[1]) * 0.5, (prev[2] + next[2]) * 0.5])
          } else if (prev) {
            candidates.push(prev)
          } else if (next) {
            candidates.push(next)
          }
        }
        if (!candidates.length) continue
        px = 0; py = 0; pz = 0
        for (const c of candidates) { px += c[0]; py += c[1]; pz += c[2] }
        px /= candidates.length; py /= candidates.length; pz /= candidates.length
        e.arm1.position.set(px, py, pz)
        e.arm2.position.set(px, py, pz)
      }
    }
  }

  /**
   * Snap all markers back to their geometric positions (pos3D from last rebuild).
   * Called when physics is toggled off.
   */
  function revertPhysics() {
    for (const e of _entries) {
      if (e.type === 'loop') {
        e.mesh.position.copy(e.pos3D)
      } else {
        e.arm1.position.copy(e.pos3D)
        e.arm2.position.copy(e.pos3D)
      }
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  function setVisible(v) {
    _visible = v
    _group.visible = v
  }

  function dispose() {
    for (const child of [..._group.children]) _group.remove(child)
    scene.remove(_group)
  }

  return { rebuild, setVisible, isVisible: () => _visible, applyDeformLerp, applyUnfoldOffsets, applyPhysicsPositions, revertPhysics, dispose }
}
