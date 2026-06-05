// Flexible ssDNA-segment relax + "ssDNA constrained" pivot gating.
//
// Two user-facing behaviours, both display/pose-layer only (NEVER mutate
// topology — see the Three-Layer Law):
//   1. The move/rotate tool's "ssDNA constrained" pivot option (enabled only
//      when every inter-cluster connection from the selected cluster is a
//      flexible tether). Dragging is clamped per-frame so no tether exceeds its
//      contour length ("free until taut"). `buildSsdnaPayload` feeds the gizmo.
//   2. The right-click "Relax this segment" / "Relax all flexible segments"
//      command: pull the SMALLER cluster of each flexible-connected pair in
//      until no tether is overstretched, committed as ONE atomic feature-log
//      entry. `relaxFlexible` runs the headless PBD solve via clusterGizmo.
//
// See memory/project_ssdna_ball_joints.md.
import { flexTetherConnections } from './flex_tethers.js'
import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'

// nm — overstretch beyond contour that counts as "needs relax".
const _SS_RELAX_TOL = 0.05

/** Live world-position resolver for a 'helix:bp:DIR' anchor key, backed by the
 *  design renderer's backbone entries. Pure given the entries snapshot. */
export function makeWorldPosResolver(backboneEntries) {
  return (key) => {
    const [h, bp, dir] = key.split(':')
    const bpN = Number(bp)
    for (const e of (backboneEntries ?? [])) {
      const n = e.nuc
      if (n && n.helix_id === h && n.bp_index === bpN && n.direction === dir) return e.pos
    }
    return null
  }
}

/** Per-tether {movingKey, fixedKey, contour} for the given moving cluster over a
 *  subset of connections, plus a live world-position resolver. Pure. */
export function buildTetherPayload(conns, movingClusterId, design, backboneEntries) {
  const connections = flexTetherConnections(conns, movingClusterId, design)
  const resolveWorldPos = makeWorldPosResolver(backboneEntries)
  return { connections, resolveWorldPos }
}

/** Bead count of a cluster (its "size") — used to pick the smaller cluster to
 *  move. Pure given the design + backbone entries. */
export function clusterBeadCount(clusterId, design, backboneEntries) {
  const ct = design?.cluster_transforms?.find(c => c.id === clusterId)
  if (!ct) return 0
  const hids = new Set(ct.helix_ids ?? [])
  let n = 0
  for (const e of (backboneEntries ?? [])) {
    if (hids.has(e.nuc?.helix_id)) n++
  }
  return n
}

/**
 * Factory: flexible-segment relax + ssDNA-constraint gating.
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.api
 * @param {object} deps.designRenderer
 * @param {object} deps.clusterGizmo
 * @param {() => boolean} deps.isTranslateRotateActive
 */
export function initFlexRelax({ store, api, designRenderer, clusterGizmo, isTranslateRotateActive }) {
  // Flexible-segment gate cache (refreshed when the move/rotate tool opens /
  // switches cluster). Drives the "ssDNA constrained" dropdown option.
  let _flexGates = {}
  let _flexConnections = []

  async function refreshFlexGates() {
    try {
      const info = await api.getFlexibleConnections()
      _flexGates = info?.gates ?? {}
      _flexConnections = info?.connections ?? []
    } catch { _flexGates = {}; _flexConnections = [] }
  }

  /** True when the cluster's "ssDNA constrained" pivot gate is open. */
  function hasGate(clusterId) {
    return !!(clusterId && _flexGates[clusterId]?.gate)
  }

  /** Build the gizmo ssDNA-constraint payload for a cluster: per-tether moving/
   *  fixed anchor keys + a live world-position resolver from backboneEntries. */
  function buildSsdnaPayload(clusterId) {
    const design = store.getState().currentDesign
    return buildTetherPayload(_flexConnections, clusterId, design, designRenderer.getBackboneEntries?.() ?? [])
  }

  // Relax overstretched flexible ssDNA segments: move the smaller cluster of each
  // flexible-connected pair so no tether exceeds its contour length (= taut at the
  // ssDNA per-base rise). A pair joined by a single flexible region translates only;
  // multiple regions translate + rotate (emergent from the PBD solve). scope='one'
  // relaxes just the clicked connection's pair; 'all' sweeps every pair to settle.
  async function relaxFlexible(scope, connId = null) {
    if (store.getState().assemblyActive) return
    if (isTranslateRotateActive()) { showToast('Finish the current move first', { severity: 'error' }); return }
    const allConns = store.getState().currentDesign?.flexible_connections ?? []
    if (!allConns.length) { showToast('No flexible segments to relax'); return }

    const pairKey = (a, b) => [a, b].sort().join(' ')
    let pairs
    if (scope === 'one') {
      const conn = allConns.find(c => c.id === connId)
      if (!conn) { showToast('Flexible connection not found', { severity: 'error' }); return }
      pairs = [pairKey(conn.cluster_a_id, conn.cluster_b_id)]
    } else {
      pairs = [...new Set(allConns.map(c => pairKey(c.cluster_a_id, c.cluster_b_id)))]
    }

    // Solve headlessly: accumulate one net pending transform per moved cluster
    // (the gizmo's pending map overwrites per cluster, so sweeps never double-count).
    clusterGizmo.discardPendingTransforms?.()
    const maxSweeps = scope === 'all' ? 8 : 2
    let residualRemains = false
    for (let sweep = 0; sweep < maxSweeps; sweep++) {
      let progressed = false
      for (const pk of pairs) {
        const design = store.getState().currentDesign
        const conns = (design?.flexible_connections ?? [])
          .filter(c => pairKey(c.cluster_a_id, c.cluster_b_id) === pk)
        if (!conns.length) continue
        const [ca, cb] = pk.split(' ')
        const entries = designRenderer.getBackboneEntries?.() ?? []
        const movingId = (clusterBeadCount(ca, design, entries) <= clusterBeadCount(cb, design, entries)) ? ca : cb
        const translateOnly = conns.length === 1
        const payload = buildTetherPayload(conns, movingId, design, entries)
        if (!payload.connections.length) continue
        // Skip if nothing in this pair is overstretched.
        const overstretched = payload.connections.some(c => {
          const pM = payload.resolveWorldPos(c.movingKey), pF = payload.resolveWorldPos(c.fixedKey)
          return pM && pF && pM.distanceTo(pF) > c.contour + _SS_RELAX_TOL
        })
        if (!overstretched) continue

        const res = clusterGizmo.relaxClusterHeadless(movingId, { ...payload, translateOnly })
        if (res.moved) progressed = true
        if (res.residual > _SS_RELAX_TOL) residualRemains = true
      }
      if (!progressed) break
    }

    const pending = clusterGizmo.getAllPendingTransforms?.() ?? []
    if (!pending.length) {
      clusterGizmo.discardPendingTransforms?.()
      clusterGizmo.detach()
      showToast('Flexible segments already relaxed')
      return
    }

    // Commit all moved clusters atomically — ONE feature-log entry (revertable +
    // deletable), ONE undo step, for both 'relax one' and 'relax all'.
    showOpProgress('Relaxing', 'Settling flexible segments…', { indeterminate: true })
    try {
      const label = scope === 'all' ? 'Relax all flexible segments' : 'Relax flexible segment'
      await api.relaxFlexibleSegments(
        pending.map(p => ({ cluster_id: p.clusterId, pivot: p.pivot, translation: p.translation, rotation: p.rotation })),
        label,
      )
    } catch (err) {
      showToast(err?.message || String(err), { severity: 'error' })
      return
    } finally {
      clusterGizmo.discardPendingTransforms?.()
      clusterGizmo.detach()
      hideOpProgress()
    }

    if (residualRemains) showToast('Relaxed — some tethers still overstretched; try Relax all again', { severity: 'warning' })
    else showToast('Relaxed flexible segments')
  }

  return { refreshFlexGates, hasGate, buildSsdnaPayload, relaxFlexible }
}
