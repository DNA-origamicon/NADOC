// Base-level pick candidates — the union of every individually-selectable bead.
//
// The `base` selection level picks ONE backbone bead. Those beads come from four
// different renderers and there is no existing aggregator: every other picker in the app
// does `[...new Set(backboneEntries.map(e => e.instMesh))].filter(m => m.visible)`, which
// reaches exactly one of them.
//
//   family          renderer                     identity
//   ─────────────── ──────────────────────────── ────────────────────────────────
//   backbone        helix_renderer iSpheres      real nuc → helix:bp:dir[:copy]
//   5′ cubes        helix_renderer iCubes        (same)
//   extension tails helix_renderer iSpheres      (same, synthetic __ext_ helix)
//   fluorophores    helix_renderer iFluoros      (same, is_modification tip bead)
//   extra xover     crossover_connections        __xb__:<xoId>:<k>
//   flexible ssDNA  flexible_arcs                design.flexible_connections[].segment_bead_keys[i]
//   ss-linker       overhang_link_arcs           __lnk__<connId>:<slot>:FORWARD
//
// A candidate is `{key, instMesh, id, family}` — `key` is the app-wide base key (see
// base_ref.js), `instMesh`/`id` locate the instance so a world position can be read.
//
// TESTABILITY: the two selection primitives (`nearestCandidate`, `candidatesInRect`) take
// an injected `project(cand) → {x,y}|null` that encapsulates BOTH the matrix read and the
// camera projection. That makes them pure and unit-testable with a fake projector — which
// matters because their only caller, selection_manager.js, is 4179 LOC with zero tests.
// `makeProjector()` builds the real one and is the only impure piece.
//
// NEVER MEMOIZE families 2–4 across pointer events: flexible_arcs disposes and rebuilds
// its meshes on every `_render()`, which fires on every cluster-drag frame.

import * as THREE from 'three'
import { baseKey, xbKey } from './base_ref.js'

/**
 * A leaf is pickable only if every ancestor up to the scene root is visible — Three's
 * renderer walks the parent chain, so checking the leaf's own `.visible` surfaces hits on
 * hidden subtrees.
 *
 * This matters more here than anywhere else: flexible_arcs and overhang_link_arcs add
 * their groups to the SCENE, not to the design root, so the usual
 * `.filter(m => m.visible)` idiom misses the group-level hide entirely. It is also wrong
 * for the backbone meshes — `iSpheres.visible` stays true while the design root is hidden
 * in atomistic/surface mode.
 */
export function isVisibleChain(obj) {
  let cur = obj
  while (cur) {
    if (cur.visible === false) return false
    cur = cur.parent
  }
  return true
}

// ── Per-family candidate builders ────────────────────────────────────────────

/**
 * Families 1–2: everything helix_renderer draws as a real nucleotide — backbone beads,
 * 5′ cubes, extension-tail sequence beads and fluorophore/modification tips.
 *
 * `scaffold`/`staples` are the app-wide selection gates; overhang beads are exempt from
 * them (they are their own exclusive filter), matching `_nearestBead`.
 */
export function backboneCandidates(backboneEntries = [], fluoroEntries = [], selectableTypes = {}) {
  const out = []
  for (const list of [backboneEntries, fluoroEntries]) {
    for (const e of list) {
      const nuc = e?.nuc
      if (!nuc?.strand_id || !isVisibleChain(e.instMesh)) continue
      if (!nuc.overhang_id) {
        const isScaf = nuc.strand_type === 'scaffold'
        if (!(isScaf ? selectableTypes.scaffold : selectableTypes.staples)) continue
      }
      const key = baseKey(nuc, e._copy)
      if (key) out.push({ key, instMesh: e.instMesh, id: e.id, family: 'backbone', nuc })
    }
  }
  return out
}

/**
 * Family 3: extra crossover bases.
 *
 * The entries come from `designRenderer.getXoverBeadEntries()`, which has already applied
 * the geometric-slot → simulation-insert flip (`simBeadIndex`). We key off `simK`, NOT the
 * raw slot: `__xb__:<xoId>:<k>` means the 5′→3′ insert index everywhere else in the app
 * (and in the backend), and on a B→A crossover those two run opposite ways.
 */
export function xoverCandidates(xoverBeadEntries = []) {
  const out = []
  for (const e of xoverBeadEntries) {
    if (!e?.instMesh || !isVisibleChain(e.instMesh)) continue
    const key = xbKey(e.xoId, e.simK)
    if (key) out.push({ key, instMesh: e.instMesh, id: e.id, family: 'xover', xoId: e.xoId, k: e.simK })
  }
  return out
}

/**
 * Family 4: flexible-ssDNA-segment beads.
 *
 * One InstancedMesh per connection, rebuilt every render. Instance `i` maps to
 * `design.flexible_connections[].segment_bead_keys[i]` — a FlexibleAnchor, which
 * `resolveAnchorKey` turns into a real `helix:bp:dir`. The backend builds
 * `segment_bead_keys` in the same anchor_a→anchor_b order the arc is drawn in
 * (backend/core/flexible_segments.py), and the sim path already indexes it that way.
 *
 * Beads whose anchor doesn't resolve are skipped rather than given a synthetic key —
 * a key that names nothing is worse than an unpickable bead.
 *
 * @param {THREE.Group|null} flexGroup   the `group` from initFlexibleArcs()
 * @param {object|null} design
 * @param {(anchor:object) => string|null} resolveAnchorKey  flexible_arcs' flexAnchorKey(design)
 */
export function flexCandidates(flexGroup, design, resolveAnchorKey) {
  if (!flexGroup || !design || typeof resolveAnchorKey !== 'function') return []
  const byConn = new Map((design.flexible_connections ?? []).map(c => [c.id, c]))
  const out = []
  for (const child of flexGroup.children ?? []) {
    if (child.name !== 'flexSegmentBeads' || !child.isInstancedMesh) continue
    if (!isVisibleChain(child)) continue
    const conn = byConn.get(child.userData?.connectionId)
    const anchors = conn?.segment_bead_keys ?? []
    for (let i = 0; i < child.count; i++) {
      const anchor = anchors[i]
      if (!anchor) continue
      const key = resolveAnchorKey(anchor)
      if (key) out.push({ key, instMesh: child, id: i, family: 'flex', connectionId: conn.id, i })
    }
  }
  return out
}

/**
 * Family 5: ss-linker bridge beads.
 *
 * CAVEAT — the slot is a DISPLAY slot, believed but NOT verified to equal the bridge
 * nucleotide's bp_index. The bridge nucs are real (`__lnk__<connId>__s` on helix
 * `__lnk__<connId>`, excluded from iSpheres at helix_renderer.js so the arc can draw them
 * instead), and the backend reports side "a" reaching the minimum bp — so slot 0 ↔ bp 0 is
 * the expected case. But the mesh is SIZED by `linkerLengthToBases(conn)`, derived from
 * `conn.length_value`, entirely independently of the geometry, so the two can disagree.
 * Keying by slot is therefore addressed-but-unproven; see the topic file.
 */
export function ssLinkCandidates(linkGroup) {
  if (!linkGroup) return []
  const out = []
  linkGroup.traverse?.((obj) => {
    if (obj.name !== 'overhangSsLinkerBeads' || !obj.isInstancedMesh) return
    if (!isVisibleChain(obj)) return
    const connId = obj.parent?.userData?.connId
    if (!connId) return
    for (let i = 0; i < obj.count; i++) {
      out.push({
        key: baseKey({ helix_id: `__lnk__${connId}`, bp_index: i, direction: 'FORWARD' }),
        instMesh: obj, id: i, family: 'sslink', connectionId: connId, i,
      })
    }
  })
  return out
}

// ── Pure selection primitives ────────────────────────────────────────────────

/**
 * The hover magnet: nearest candidate within `radiusPx` of canvas-relative (sx, sy).
 * Same 80 px "large but non-infinite" snap the end/xover/strand levels use, so base
 * level needs no pixel-precise aiming either.
 *
 * @param {(cand:object) => {x:number,y:number}|null} project  null = off-screen/behind camera
 */
export function nearestCandidate(cands = [], sx, sy, radiusPx, project) {
  let best = null, bestD = radiusPx
  for (const c of cands) {
    const sp = project(c)
    if (!sp) continue
    const d = Math.hypot(sp.x - sx, sp.y - sy)
    if (d < bestD) { bestD = d; best = c }
  }
  return best
}

/**
 * Lasso capture: every candidate whose projected center falls inside the rect.
 * Bounds are INCLUSIVE, matching the existing lasso loops.
 *
 * @param {{x1:number,y1:number,x2:number,y2:number}} rect  canvas-relative, normalized
 */
export function candidatesInRect(cands = [], rect, project) {
  const out = []
  if (!rect) return out
  const { x1, y1, x2, y2 } = rect
  for (const c of cands) {
    const sp = project(c)
    if (!sp) continue
    if (sp.x < x1 || sp.x > x2 || sp.y < y1 || sp.y > y2) continue
    out.push(c)
  }
  return out
}

// ── The real projector (impure) ──────────────────────────────────────────────

const _m4 = new THREE.Matrix4()
const _v3 = new THREE.Vector3()

/** World position of a candidate's instance. Writes into `out` and returns it. */
export function worldPosOf(cand, out = new THREE.Vector3()) {
  cand.instMesh.getMatrixAt(cand.id, _m4)
  return out.setFromMatrixPosition(_m4)
}

/**
 * Build the candidate → canvas-pixel projector.
 *
 * NDC comes from `canvas.getBoundingClientRect()`, never `window.innerWidth` — the
 * app-wide rule (see `_setNdc`). Returns null for anything behind the camera.
 */
export function makeProjector(camera, canvas) {
  const rect = canvas.getBoundingClientRect()
  return (cand) => {
    cand.instMesh.getMatrixAt(cand.id, _m4)
    _v3.setFromMatrixPosition(_m4).project(camera)
    if (_v3.z > 1) return null                       // behind the camera
    return {
      x: (_v3.x *  0.5 + 0.5) * rect.width,
      y: (_v3.y * -0.5 + 0.5) * rect.height,
    }
  }
}
