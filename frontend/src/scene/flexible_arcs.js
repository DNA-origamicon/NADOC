/**
 * Flexible ssDNA segment arcs.
 *
 * Draws each `design.flexible_connections` entry as a fixed-contour-length arc
 * between the two rigid cluster anchors. The marked ssDNA beads (excluded from
 * the rigid bead meshes in helix_renderer) are placed along this arc. The arc
 * conserves contour length: it bows more as the chord shortens and straightens
 * toward a line when the chord approaches the contour length ("free until
 * taut"). Pure visualisation — display layer only.
 *
 * Bow DIRECTION is chosen to point AWAY from the nearby helix-bundle cylinders
 * (repulsion from helix-axis centerlines), so a slack arc bulges outward rather
 * than diving through the structure. Recomputed live during a cluster drag (the
 * moving cluster's axes are transformed by the live drag transform), with
 * smoothing/hysteresis to avoid the bow flipping jarringly mid-drag.
 *
 *   const arcs = initFlexibleArcs(scene, designRenderer, () => store.currentHelixAxes)
 *   arcs.rebuild(design)
 *   arcs.applyLiveUpdate(helixIds, centerVec, dummyPos, incrQuat)   // per drag frame
 */
import * as THREE from 'three'
import { store } from '../state/store.js'
import { buildClusterColorLookup } from './helix_renderer/palette.js'
import { clusterAlphaForNuc, clusterAlphaKeys } from './cluster_entries.js'

const ARC_COLOR = 0xff33cc      // magenta — flexible ssDNA
const BEAD_RADIUS = 0.12
const TUBE_RADIUS = 0.06
const TUBE_SEGS = 32
const OBST_RADIUS = 12.0        // nm — only cylinders within this of the arc midpoint repel
const BOW_SMOOTH = 0.6          // hysteresis: keep this fraction of the previous bow
const Y_HAT = new THREE.Vector3(0, 1, 0)
const X_HAT = new THREE.Vector3(1, 0, 0)
const GEO_BEAD = new THREE.SphereGeometry(BEAD_RADIUS, 8, 6)
// Synthetic arc slabs keep the same visual dimensions, but their placement is
// independent of canonical duplex slabs. Box local axes: x=length (0.30),
// y=width (0.06), z=thickness (0.70).
const GEO_SLAB = new THREE.BoxGeometry(0.30, 0.06, 0.70)
// Synthetic ssDNA-arc decoration only. Canonical duplex slabs are positioned by
// helix_renderer.pairedSlabCenter; this fixed offset must not be reused there.
const SLAB_DISTANCE = 0.55

function _fallbackBow(dHat) {
  let b = new THREE.Vector3().crossVectors(dHat, Y_HAT)
  if (b.lengthSq() < 1e-6) b = new THREE.Vector3().crossVectors(dHat, X_HAT)
  return b.normalize()
}

/** Slab orientation, matching helix_renderer.js slabQuaternion: local x →
 *  tangential, y → tangent (stacking axis), z → base-normal (inward). */
function _slabQuaternion(bnDir, tanDir, out) {
  const tangential = new THREE.Vector3().crossVectors(tanDir, bnDir).normalize()
  const m = new THREE.Matrix4().makeBasis(tangential, tanDir, bnDir)
  return out.setFromRotationMatrix(m)
}

/** Closest point on segment [p0,p1] to point p. */
function _closestOnSeg(p, p0, p1, out) {
  const ab = new THREE.Vector3().subVectors(p1, p0)
  const t = THREE.MathUtils.clamp(new THREE.Vector3().subVectors(p, p0).dot(ab) / (ab.lengthSq() || 1), 0, 1)
  return out.copy(p0).addScaledVector(ab, t)
}

/** n interior points along a circular arc of arc-length `L` from a to b, bowing
 *  toward unit `bowDir` (perpendicular to the chord). */
function _arcPoints(a, b, L, n, bowDir) {
  const pts = []
  if (n <= 0) return pts
  const d = new THREE.Vector3().subVectors(b, a)
  const c = d.length()
  if (c < 1e-6 || c >= L) {                 // taut / coincident → straight
    for (let i = 1; i <= n; i++) pts.push(new THREE.Vector3().lerpVectors(a, b, i / (n + 1)))
    return pts
  }
  // Solve θ ∈ (0,π): sin(θ)/θ = chord/contour. (Half-angle of the circular arc.)
  const ratio = c / L
  let lo = 1e-4, hi = Math.PI - 1e-4
  for (let it = 0; it < 40; it++) {
    const mid = (lo + hi) / 2
    if (Math.sin(mid) / mid > ratio) lo = mid
    else hi = mid
  }
  const theta = (lo + hi) / 2
  const R = L / (2 * theta)
  const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5)
  const O = mid.clone().addScaledVector(bowDir, -R * Math.cos(theta))   // arc centre
  const ua = new THREE.Vector3().subVectors(a, O).normalize()
  const ub = new THREE.Vector3().subVectors(b, O).normalize()
  let axis = new THREE.Vector3().crossVectors(ua, ub)
  if (axis.lengthSq() < 1e-9) axis = new THREE.Vector3().crossVectors(d.clone().normalize(), bowDir)
  axis.normalize()
  const ang = Math.acos(THREE.MathUtils.clamp(ua.dot(ub), -1, 1))
  const q = new THREE.Quaternion()
  for (let i = 1; i <= n; i++) {
    q.setFromAxisAngle(axis, ang * (i / (n + 1)))
    pts.push(ua.clone().applyQuaternion(q).multiplyScalar(R).add(O))
  }
  return pts
}

/**
 * FlexibleAnchor → the app-wide nucleotide key `helix:bp:dir`.
 *
 * An anchor addresses a base strand-relatively ({strand_id, domain_index, bp_index,
 * direction}); the rest of the app addresses it helix-relatively. This is the only walk
 * between the two, and `design.flexible_connections[].segment_bead_keys[i]` is the map
 * from a drawn bead instance to its real nucleotide — so base-level picking needs it too
 * (base_pick.js `flexCandidates`). Curried by design so the strand index is built once.
 *
 * @param {object} design
 * @returns {(anchor:object) => string|null}
 */
export function flexAnchorKey(design) {
  const byId = new Map((design?.strands ?? []).map(s => [s.id, s]))
  return (anc) => {
    if (!anc) return null
    const s = byId.get(anc.strand_id)
    const d = s?.domains?.[anc.domain_index]
    return d ? `${d.helix_id}:${anc.bp_index}:${anc.direction}` : null
  }
}

export function initFlexibleArcs(scene, designRenderer, getHelixAxes = () => null) {
  const group = new THREE.Group()
  group.name = 'flexibleArcs'
  scene.add(group)
  let _design = null
  let _visible = true
  let _reprVisible = true
  // When an oxDNA/MD display overlay is active, the flexible run's beads are drawn
  // at their SIMULATED positions (keyed "helix:bp:dir" → {pos, n:a1}) instead of the
  // geometric arc. null = geometric-arc mode (the default).
  let _simByKey = null
  const _lastBow = new Map()   // connection id -> THREE.Vector3 (hysteresis)

  // ── Per-cluster display (colour + opacity) ────────────────────────────────
  // These materials used to be three module-level singletons shared by every
  // connection's meshes, which makes per-connection colour or fade impossible —
  // one write hits every arc. They are now created PER CONNECTION (and disposed
  // in _clear, which the shared ones deliberately were not). A flexible design
  // has a handful of connections, so the extra materials are free.
  //
  // A run bridges two anchors that may sit in different clusters: it takes the
  // A-side anchor's cluster colour (falling back to B) and fades to the LOWER of
  // the two alphas — the same owner rule as crossover arcs, extra bases and
  // overhang link arcs.
  let _clusterColorFn   = null    // non-null only while coloringMode === 'cluster'
  let _clusterAlphaKeys = new Map()

  /** Re-read the cluster colour/alpha lookups off a design. */
  function _syncClusterLookups(design) {
    _clusterColorFn = (store.getState().coloringMode === 'cluster')
      ? buildClusterColorLookup(design)
      : null
    _clusterAlphaKeys = clusterAlphaKeys(design)
  }

  /** Pseudo-nucleotide for an anchor, in the shape the cluster lookups expect. */
  function _anchorNuc(design, anc) {
    const s = (design?.strands ?? []).find(x => x.id === anc?.strand_id)
    const d = s?.domains?.[anc?.domain_index]
    return d ? { helix_id: d.helix_id, strand_id: anc.strand_id, domain_index: anc.domain_index } : null
  }

  function _connDisplay(design, c) {
    const nucA = _anchorNuc(design, c.anchor_a)
    const nucB = _anchorNuc(design, c.anchor_b)
    const color = _clusterColorFn
      ? (_clusterColorFn(nucA) ?? _clusterColorFn(nucB) ?? ARC_COLOR)
      : ARC_COLOR
    const alpha = _clusterAlphaKeys.size
      ? Math.min(clusterAlphaForNuc(_clusterAlphaKeys, nucA),
                 clusterAlphaForNuc(_clusterAlphaKeys, nucB))
      : 1
    return { color, alpha }
  }

  /** One fresh material set for a connection. */
  function _makeMats({ color, alpha }) {
    const opts = {
      color,
      transparent: alpha < 1,
      opacity: alpha,
      // Structural geometry, not an overlay — keep writing depth so a faded run
      // still occludes and still casts/receives the photo-mode key shadow.
      depthWrite: true,
    }
    const mats = {
      tube: new THREE.MeshPhongMaterial(opts),
      bead: new THREE.MeshPhongMaterial(opts),
      slab: new THREE.MeshPhongMaterial(opts),
    }
    for (const m of Object.values(mats)) m.userData.photoForceDepthWrite = true
    return mats
  }

  function _entryPosMap() {
    const m = new Map()
    for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
      const n = e.nuc
      if (n) m.set(`${n.helix_id}:${n.bp_index}:${n.direction}`, e.pos)
    }
    return m
  }

  const _helixResolver = flexAnchorKey

  // Build world-space helix-axis obstacle segments. `live` (when dragging) =
  // {helixIds:Set, centerVec, dummyPos, incrQuat} — transforms the moving
  // cluster's axes so obstacles share the arcs' live frame.
  function _obstacleSegments(live) {
    const axes = getHelixAxes() || {}
    const segs = []
    const xf = (p) => {
      const v = new THREE.Vector3(p[0], p[1], p[2])
      if (live) v.sub(live.centerVec).applyQuaternion(live.incrQuat).add(live.dummyPos)
      return v
    }
    for (const [hid, ax] of Object.entries(axes)) {
      if (!ax?.start || !ax?.end) continue
      const moving = live && live.helixIds?.has(hid)
      const p0 = moving ? xf(ax.start) : new THREE.Vector3(...ax.start)
      const p1 = moving ? xf(ax.end)   : new THREE.Vector3(...ax.end)
      segs.push([p0, p1])
    }
    return segs
  }

  function _bowDir(a, b, connId, obstacles) {
    const d = new THREE.Vector3().subVectors(b, a)
    const dHat = d.clone().normalize()
    const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5)
    // Repulsion from nearby cylinder centerlines.
    const rep = new THREE.Vector3()
    const cp = new THREE.Vector3()
    for (const [p0, p1] of obstacles) {
      _closestOnSeg(mid, p0, p1, cp)
      const v = new THREE.Vector3().subVectors(mid, cp)
      const dist = v.length()
      if (dist < 1e-3 || dist > OBST_RADIUS) continue
      rep.addScaledVector(v.multiplyScalar(1 / dist), 1 / (dist * dist))   // unit·(1/d²)
    }
    // Project onto the plane perpendicular to the chord.
    rep.addScaledVector(dHat, -rep.dot(dHat))
    let bow = (rep.lengthSq() > 1e-9) ? rep.normalize() : (_lastBow.get(connId)?.clone() ?? _fallbackBow(dHat))
    // Hysteresis: blend with the previous bow, then re-project + renormalise.
    const last = _lastBow.get(connId)
    if (last) {
      bow = last.clone().multiplyScalar(BOW_SMOOTH).addScaledVector(bow, 1 - BOW_SMOOTH)
      bow.addScaledVector(dHat, -bow.dot(dHat))
      if (bow.lengthSq() < 1e-9) bow = _fallbackBow(dHat)
      bow.normalize()
    }
    _lastBow.set(connId, bow.clone())
    return bow
  }

  function _clear() {
    for (const ch of [...group.children]) {
      group.remove(ch)
      ch.geometry?.dispose?.()
      // Materials are per-connection now (they used to be shared singletons that
      // must NOT be disposed) — dropping them here or they leak on every render.
      ch.material?.dispose?.()
    }
  }

  function _drawArc(pA, pB, beads, bow, connId, mats) {
    const pts = [pA, ...beads, pB]
    const curve = new THREE.CatmullRomCurve3(pts)
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, TUBE_SEGS, TUBE_RADIUS, 6, false), mats.tube)
    tube.userData.connectionId = connId
    group.add(tube)
    if (!beads.length) return
    const inst = new THREE.InstancedMesh(GEO_BEAD, mats.bead, beads.length)
    const m = new THREE.Matrix4()
    beads.forEach((p, i) => { m.makeTranslation(p.x, p.y, p.z); inst.setMatrixAt(i, m) })
    inst.instanceMatrix.needsUpdate = true
    inst.frustumCulled = false
    inst.userData.connectionId = connId
    inst.name = 'flexSegmentBeads'   // base-level picking finds beads by name (base_pick.js)
    group.add(inst)
    // Base slabs — base-normal faces inward toward the arc's centre of
    // curvature (same orientation curved dsDNA uses). The arc is planar with
    // plane normal `planeN`; the in-plane normal ⟂ tangent, flipped to oppose
    // the (outward) bow, points at the centre.
    const planeN = new THREE.Vector3().crossVectors(
      new THREE.Vector3().subVectors(pB, pA).normalize(), bow)
    if (planeN.lengthSq() < 1e-9) return
    planeN.normalize()
    const slabs = new THREE.InstancedMesh(GEO_SLAB, mats.slab, beads.length)
    const sm = new THREE.Matrix4(), q = new THREE.Quaternion()
    const tan = new THREE.Vector3(), bn = new THREE.Vector3(), center = new THREE.Vector3()
    const scl = new THREE.Vector3(1, 1, 1)
    for (let i = 0; i < beads.length; i++) {
      tan.subVectors(pts[i + 2], pts[i]).normalize()      // arc tangent (stacking axis)
      bn.crossVectors(planeN, tan).normalize()            // in-plane, ⟂ tangent
      if (bn.dot(bow) > 0) bn.negate()                    // face the centre of curvature
      center.copy(beads[i]).addScaledVector(bn, SLAB_DISTANCE)
      _slabQuaternion(bn, tan, q)
      sm.compose(center, q, scl)
      slabs.setMatrixAt(i, sm)
    }
    slabs.instanceMatrix.needsUpdate = true
    slabs.frustumCulled = false
    slabs.userData.connectionId = connId
    slabs.name = 'flexSegmentSlabs'  // named so it is NOT mistaken for the bead mesh
    group.add(slabs)
  }

  const _ray = new THREE.Raycaster()
  const _ndc = new THREE.Vector2()
  /** Raycast the flexible arcs; return the hit connection id, or null. */
  function hitTest(clientX, clientY, camera, canvas) {
    if (!_visible || !group.children.length) return null
    const rect = canvas.getBoundingClientRect()
    _ndc.set(((clientX - rect.left) / rect.width) * 2 - 1,
             -((clientY - rect.top) / rect.height) * 2 + 1)
    _ray.setFromCamera(_ndc, camera)
    const hits = _ray.intersectObjects(group.children, false)
    return hits.length ? (hits[0].object.userData.connectionId ?? null) : null
  }

  // Draw one connection's run at explicit SIMULATED bead positions (oxDNA/MD frame):
  // tube + beads through the sim points, slabs oriented from the sim base-normal.
  function _drawSimSegment(pA, entries, pB, connId, mats) {
    const beads = entries.map(e => e.pos)
    const pts = [pA, ...beads, pB]
    const curve = new THREE.CatmullRomCurve3(pts)
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, TUBE_SEGS, TUBE_RADIUS, 6, false), mats.tube)
    tube.userData.connectionId = connId
    group.add(tube)
    const inst = new THREE.InstancedMesh(GEO_BEAD, mats.bead, beads.length)
    const m = new THREE.Matrix4()
    beads.forEach((p, i) => { m.makeTranslation(p.x, p.y, p.z); inst.setMatrixAt(i, m) })
    inst.instanceMatrix.needsUpdate = true
    inst.frustumCulled = false
    inst.userData.connectionId = connId
    inst.name = 'flexSegmentBeads'   // sim-frame twin of _drawArc's mesh — same name, same picking
    group.add(inst)
    const slabs = new THREE.InstancedMesh(GEO_SLAB, mats.slab, beads.length)
    const sm = new THREE.Matrix4(), q = new THREE.Quaternion()
    const tan = new THREE.Vector3(), bn = new THREE.Vector3(), center = new THREE.Vector3()
    const scl = new THREE.Vector3(1, 1, 1)
    for (let i = 0; i < beads.length; i++) {
      tan.subVectors(pts[i + 2], pts[i]).normalize()      // local backbone tangent
      const a1 = entries[i].n
      if (a1 && a1.lengthSq() > 1e-9) {                    // sim base-normal, ⟂ tangent
        bn.copy(a1).addScaledVector(tan, -a1.dot(tan))
        if (bn.lengthSq() < 1e-9) bn.copy(_fallbackBow(tan))
      } else {
        bn.copy(_fallbackBow(tan))
      }
      bn.normalize()
      center.copy(beads[i]).addScaledVector(bn, SLAB_DISTANCE)
      _slabQuaternion(bn, tan, q)
      sm.compose(center, q, scl)
      slabs.setMatrixAt(i, sm)
    }
    slabs.instanceMatrix.needsUpdate = true
    slabs.frustumCulled = false
    slabs.userData.connectionId = connId
    slabs.name = 'flexSegmentSlabs'
    group.add(slabs)
  }

  function _render(live = null) {
    _clear()
    if (!_design || !_visible || !_reprVisible) return
    _syncClusterLookups(_design)
    const conns = _design.flexible_connections ?? []
    if (!conns.length) return
    const posMap = _entryPosMap()
    const helixOf = _helixResolver(_design)
    const obstacles = _simByKey ? [] : _obstacleSegments(live)
    for (const c of conns) {
      const pA = posMap.get(helixOf(c.anchor_a) ?? '')
      const pB = posMap.get(helixOf(c.anchor_b) ?? '')
      if (!pA || !pB) continue
      // oxDNA/MD active: place beads at simulated positions when every run bead is
      // present in the frame; otherwise fall through to the geometric arc.
      if (_simByKey) {
        const entries = (c.segment_bead_keys ?? []).map(k => _simByKey.get(helixOf(k) ?? ''))
        if (entries.length && entries.every(Boolean)) { _drawSimSegment(pA, entries, pB, c.id, _makeMats(_connDisplay(_design, c))); continue }
      }
      const bow = _bowDir(pA, pB, c.id, obstacles)
      _drawArc(pA, pB, _arcPoints(pA, pB, c.contour_length_nm, c.n_ss_bases, bow), bow, c.id,
               _makeMats(_connDisplay(_design, c)))
    }
  }

  function rebuild(design) { _design = design; if (!design?.flexible_connections?.length) _lastBow.clear(); _render(null) }
  function applyLiveUpdate(helixIds, centerVec, dummyPos, incrQuat) {
    const live = (helixIds && centerVec && dummyPos && incrQuat)
      ? { helixIds: new Set(helixIds), centerVec, dummyPos, incrQuat }
      : null
    _render(live)
  }
  function _syncVisibility() {
    group.visible = _visible && _reprVisible
    if (group.visible) _render()
    else _clear()
  }
  function setVisible(v) { _visible = v; _syncVisibility() }
  function setRepresentation(repr) {
    _reprVisible = (repr === 'full' || repr === 'beads')
    _syncVisibility()
  }
  /** Switch to SIMULATED-position mode from an oxDNA/MD frame's applyFemPositions
   *  updates (array of {helix_id,bp_index,direction,backbone_position,nx,ny,nz}), or
   *  pass null/empty to revert to the geometric arc.  Called by the oxDNA display
   *  controller's frame chokepoint so the flexible run tracks the relaxed ssDNA
   *  instead of leaving a stale geometric arc floating over the sim. */
  function applySimPositions(updates) {
    if (!Array.isArray(updates) || !updates.length) {
      _simByKey = null
    } else {
      const map = new Map()
      for (const u of updates) {
        const p = u.backbone_position
        if (!p) continue
        map.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, {
          pos: new THREE.Vector3(p[0], p[1], p[2]),
          n: Number.isFinite(u.nx) ? new THREE.Vector3(u.nx, u.ny, u.nz) : null,
        })
      }
      _simByKey = map.size ? map : null
    }
    _render()
  }
  function dispose() {
    // _clear() disposes the per-connection materials; only the shared geometries
    // are left to release here.
    _clear(); scene.remove(group)
    GEO_BEAD.dispose(); GEO_SLAB.dispose()
  }

  /**
   * Re-read per-cluster colour + opacity and repaint IN PLACE.
   *
   * Deliberately not a re-render: `_render` rebuilds a TubeGeometry per
   * connection, and this runs live while the sidebar swatch is dragged. Because
   * every mesh now owns its material and carries `userData.connectionId`, the
   * repaint is a handful of material writes. It also must not latch `_design` —
   * the preview design is transient and never reaches the store.
   *
   * @param {object} [design]  defaults to the last rendered design
   */
  function refreshClusterDisplay(design = null) {
    const d = design ?? _design
    _syncClusterLookups(d)
    const byId = new Map((d?.flexible_connections ?? []).map(c => [c.id, _connDisplay(d, c)]))
    for (const ch of group.children) {
      const disp = byId.get(ch.userData?.connectionId)
      const mat = ch.material
      if (!disp || !mat || Array.isArray(mat)) continue
      mat.color.setHex(disp.color)
      mat.opacity = disp.alpha
      mat.transparent = disp.alpha < 1
      mat.needsUpdate = true
    }
  }

  // Entering or leaving cluster-coloring mode changes nothing about the design, so
  // the design subscriber that drives rebuild() never fires for it.
  store.subscribe((newState, prevState) => {
    if (newState.coloringMode === prevState.coloringMode) return
    if (!group.children.length) return
    refreshClusterDisplay(newState.currentDesign)
  })

  return { rebuild, applyLiveUpdate, setVisible, setRepresentation, applySimPositions, dispose, hitTest, group, refreshClusterDisplay }
}
