// cpd_weld_overlay.js — draws the designed extra-base UV weld in the 3D scene.
//
// For each intended weld pair (GET /api/md/jobs/{id}/cpd-pairs) this puts a marker on
// each thymine's C5=C6 bond midpoint and a bar between them, coloured by the KIMMDY
// propensity k: red = far from reactive, amber = approaching, green = in the reactive
// corner.  That is the whole point of the overlay — you can watch a trajectory and SEE
// whether the two extra bases ever get close enough to weld, instead of inferring it
// from a number afterwards.
//
// Positions come from the renderer's own atom placement (see initAtomisticRenderer's
// weld-overlay hook), so the markers cannot drift off the atoms they annotate.  This is
// deliberate: the MD display affine is handed over rather than re-derived
// (memory/project_md_viz_tools.md), so any independent coordinate path would be offset.
//
// DISPLAY LAYER ONLY — never touches topology, never writes back.
//
// Factory:
//   initCpdWeldOverlay({ scene, THREE }) →
//     { setPairs, update, setVisible, isVisible, getReadouts, dispose }

import { readWeldGeometryFrom, weldColor, formatWeldReadout, VDW_FLOOR_NM } from './cpd_geometry.js'

const MARKER_RADIUS_NM = 0.09
const BAR_RADIUS_NM = 0.035

/**
 * Build the per-pair render state a frame update needs.
 * PURE — no Three.js. Splits "which pairs can be drawn" from "draw them", so the
 * decision is testable without a scene.
 */
export function planWeldDraw (pairs, getPos) {
  const out = []
  for (const p of pairs || []) {
    const geom = readWeldGeometryFrom(p, getPos)
    if (!geom) continue
    out.push({
      id: geom.id,
      label: geom.label,
      midA: geom.midA,
      midB: geom.midB,
      dNm: geom.dNm,
      etaDeg: geom.etaDeg,
      k: geom.k,
      reactive: geom.reactive,
      color: weldColor(geom.k),
      // Below vdW contact a classical force field is being pushed past what it can
      // represent — flag it rather than drawing it as a normal happy state.
      belowVdw: geom.dNm < VDW_FLOOR_NM,
      readout: formatWeldReadout(geom),
    })
  }
  return out
}

/**
 * Where each umbrella window's centre sits, as a bead on the pair axis.
 * PURE.
 *
 * A window restrains |midB - midA|, so its true constraint surface is a SPHERE of that
 * radius around midA. Drawing thirteen nested spheres would bury the structure, so the
 * ladder is drawn as beads along the axis instead: same information (which separations
 * are sampled, how they're spaced, which are stiff) without occluding anything.
 *
 * `reached` marks windows the pair is currently at or inside — i.e. how far down the
 * ladder this frame has actually got.
 */
export function planWindowMarkers (geom, windows) {
  if (!geom || !windows?.length) return []
  const [ax, ay, az] = geom.midA
  const [bx, by, bz] = geom.midB
  const dx = bx - ax, dy = by - ay, dz = bz - az
  const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
  if (!(len > 0)) return []
  const ux = dx / len, uy = dy / len, uz = dz / len
  const dAng = geom.dNm * 10
  const ks = windows.map((w) => w.force_constant ?? 1)
  const kMin = Math.min(...ks), kMax = Math.max(...ks)
  return windows.map((w) => {
    const r = (w.center_ang ?? 0) / 10                       // Å → nm
    const stiffness = kMax > kMin ? ((w.force_constant ?? 1) - kMin) / (kMax - kMin) : 1
    return {
      centerAng: w.center_ang,
      forceConstant: w.force_constant,
      pos: [ax + ux * r, ay + uy * r, az + uz * r],
      stiffness,
      reached: dAng <= (w.center_ang ?? 0) + 1e-9,
      // null = seeding not measured yet; false = no frame near enough to start it.
      seeded: w.seeded === undefined ? null : !!w.seeded,
    }
  })
}

export function initCpdWeldOverlay ({ scene, THREE } = {}) {
  let _pairs = []
  let _visible = false
  let _plans = []
  let _windows = []
  let _windowMeshes = []
  let _group = null
  const _nodes = new Map() // pair id → { markerA, markerB, bar }

  function _ensureGroup () {
    if (_group || !scene || !THREE) return _group
    _group = new THREE.Group()
    _group.name = 'cpdWeldOverlay'
    _group.renderOrder = 999
    scene.add(_group)
    return _group
  }

  function _makeNode (color) {
    const sphere = new THREE.SphereGeometry(MARKER_RADIUS_NM, 16, 12)
    const cyl = new THREE.CylinderGeometry(BAR_RADIUS_NM, BAR_RADIUS_NM, 1, 12)
    const mat = () => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthTest: false })
    const markerA = new THREE.Mesh(sphere, mat())
    const markerB = new THREE.Mesh(sphere, mat())
    const bar = new THREE.Mesh(cyl, mat())
    for (const m of [markerA, markerB, bar]) { m.renderOrder = 999; _group.add(m) }
    return { markerA, markerB, bar }
  }

  function _placeBar (bar, a, b) {
    const ax = a[0], ay = a[1], az = a[2]
    const dx = b[0] - ax, dy = b[1] - ay, dz = b[2] - az
    const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
    if (!(len > 0)) { bar.visible = false; return }
    bar.visible = true
    bar.position.set(ax + dx / 2, ay + dy / 2, az + dz / 2)
    // The cylinder's own axis is +Y; aim it along the pair vector.
    bar.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(dx / len, dy / len, dz / len))
    bar.scale.set(1, len, 1)
  }

  /** Replace the pair set (from /cpd-pairs). Pass [] to clear. */
  function setPairs (pairs) {
    _pairs = Array.isArray(pairs) ? pairs.filter((p) => p && p.serials_resolved !== false) : []
    // Any node whose pair is gone must go with it.
    for (const [id, node] of _nodes) {
      if (!_pairs.some((p) => p.id === id)) {
        for (const m of Object.values(node)) { m.geometry?.dispose?.(); m.material?.dispose?.(); _group?.remove(m) }
        _nodes.delete(id)
      }
    }
  }

  /**
   * Recompute + redraw from the current frame.
   * `getPos(serial) → [x,y,z]|null` must be the renderer's own atom placement.
   */
  function update (getPos) {
    _plans = _visible && _pairs.length ? planWeldDraw(_pairs, getPos) : []
    if (!_visible || !_plans.length) {
      for (const node of _nodes.values()) for (const m of Object.values(node)) m.visible = false
      return _plans
    }
    if (!_ensureGroup()) return _plans
    const alive = new Set()
    for (const plan of _plans) {
      alive.add(plan.id)
      let node = _nodes.get(plan.id)
      if (!node) { node = _makeNode(plan.color); _nodes.set(plan.id, node) }
      node.markerA.position.set(...plan.midA)
      node.markerB.position.set(...plan.midB)
      _placeBar(node.bar, plan.midA, plan.midB)
      for (const m of Object.values(node)) {
        m.visible = true
        m.material.color.setHex(plan.color)
        m.material.opacity = plan.belowVdw ? 1.0 : 0.9
      }
    }
    for (const [id, node] of _nodes) {
      if (!alive.has(id)) for (const m of Object.values(node)) m.visible = false
    }
    _drawWindows(_plans[0])
    return _plans
  }

  /** Umbrella-window beads along the first pair's axis. */
  function _drawWindows (plan) {
    const marks = plan ? planWindowMarkers(plan, _windows) : []
    if (!_group || !THREE) return marks
    while (_windowMeshes.length < marks.length) {
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(0.045, 10, 8),
        new THREE.MeshBasicMaterial({ color: 0x8b949e, transparent: true, opacity: 0.55, depthTest: false }))
      m.renderOrder = 998
      _group.add(m)
      _windowMeshes.push(m)
    }
    _windowMeshes.forEach((m, i) => {
      const w = marks[i]
      if (!w) { m.visible = false; return }
      m.visible = true
      m.position.set(...w.pos)
      // Seeding, once measured, outranks everything else a bead could say: an unseeded
      // window cannot be run at all, so it reads amber regardless of stiffness or reach.
      const hex = w.seeded === false ? 0xd29922 : (w.reached ? 0x58a6ff : 0x6e7681)
      m.material.color.setHex(hex)
      m.material.opacity = (w.seeded === false ? 0.85 : 0.35) + 0.35 * w.stiffness
    })
    return marks
  }

  /** Ladder to preview (from /cpd-colvars). Pass [] to clear. */
  function setWindows (windows) {
    _windows = Array.isArray(windows) ? windows : []
    if (!_windows.length) _windowMeshes.forEach((m) => { m.visible = false })
  }

  function setVisible (v) {
    _visible = !!v
    if (_group) _group.visible = _visible
    if (!_visible) for (const node of _nodes.values()) for (const m of Object.values(node)) m.visible = false
  }

  /**
   * Fetch a job's designed weld pairs and switch the overlay on.
   * Lives here rather than in main.js so the composition root gains only an import + a
   * factory init (module-first law). Returns { ready, pairs, reason }.
   */
  async function loadForJob (api, jobId) {
    if (!api?.getMdCpdPairs || !jobId) return { ready: false, pairs: [], reason: 'no job' }
    const resp = await api.getMdCpdPairs(jobId)
    if (!resp) return { ready: false, pairs: [], reason: 'request failed' }
    setPairs(resp.pairs || [])
    setVisible(_pairs.length > 0)
    return { ready: !!resp.ready, pairs: _pairs, reason: resp.reason || null }
  }

  const isVisible = () => _visible
  /** Latest per-pair readouts, for a HUD line. */
  const getReadouts = () => _plans.map((p) => ({ id: p.id, label: p.label, readout: p.readout, k: p.k, reactive: p.reactive }))

  function dispose () {
    for (const node of _nodes.values()) {
      for (const m of Object.values(node)) { m.geometry?.dispose?.(); m.material?.dispose?.(); _group?.remove(m) }
    }
    _nodes.clear()
    for (const m of _windowMeshes) { m.geometry?.dispose?.(); m.material?.dispose?.(); _group?.remove(m) }
    _windowMeshes = []
    if (_group && scene) scene.remove(_group)
    _group = null
    _plans = []
  }

  return { setPairs, setWindows, loadForJob, update, setVisible, isVisible, getReadouts, dispose }
}
