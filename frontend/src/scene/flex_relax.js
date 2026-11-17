// Flexible ssDNA-segment relax + "ssDNA constrained" pivot gating.
//
// Two user-facing behaviours, both display/pose-layer only (NEVER mutate
// topology — see the Three-Layer Law):
//   1. The move/rotate tool's "ssDNA constrained" pivot option (enabled only
//      when every inter-cluster connection from the selected cluster is a
//      flexible tether). Dragging is clamped per-frame so no tether exceeds its
//      contour length ("free until taut"). `buildSsdnaPayload` feeds the gizmo.
//   2. The right-click "Relax this segment" / "Relax all flexible segments"
//      command: solve the connected rigid-body network with the largest body
//      fixed, committed as ONE atomic feature-log entry by the server.
//
// See memory/project_ssdna_ball_joints.md.
import { flexTetherConnections } from './flex_tethers.js'
import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'


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

/**
 * Factory: flexible-segment relax + ssDNA-constraint gating.
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.api
 * @param {object} deps.designRenderer
 * @param {() => boolean} deps.isTranslateRotateActive
 */
export function initFlexRelax({ store, api, designRenderer, isTranslateRotateActive }) {
  // Flexible-segment gate cache (refreshed when the move/rotate tool opens /
  // switches cluster). Drives the "ssDNA constrained" dropdown option.
  let _flexGates = {}
  let _flexConnections = []
  // Clusters constrained by an applied overhang CONNECTION (direct duplex / ss-ds linker) —
  // they get the "Constrained (tethers)" option even with no ssDNA flexible-segment marks.
  let _connTetherClusters = []

  async function refreshFlexGates() {
    try {
      const info = await api.getFlexibleConnections()
      _flexGates = info?.gates ?? {}
      _flexConnections = info?.connections ?? []
      _connTetherClusters = info?.connection_tether_clusters ?? []
    } catch { _flexGates = {}; _flexConnections = []; _connTetherClusters = [] }
  }

  /** True when the cluster's ssDNA flexible-segment gate is open. */
  function hasGate(clusterId) {
    return !!(clusterId && _flexGates[clusterId]?.gate)
  }

  /** True when the "Constrained (tethers)" option should be offered — either an open ssDNA
   *  gate OR an applied overhang connection (direct duplex / linker) constrains this cluster. */
  function hasTetherOption(clusterId) {
    return hasGate(clusterId) || _connTetherClusters.includes(clusterId)
  }

  /** Combined free-until-taut payload for a REGULAR cluster: ssDNA flexible-segment tethers
   *  MERGED with the cluster's applied overhang-connection tethers (direct duplex + ss/ds
   *  linker). Async (one GET for the connection tethers). Returns null if nothing constrains it. */
  async function buildTethersPayload(clusterId) {
    const ssd = buildSsdnaPayload(clusterId)   // { connections, resolveWorldPos }
    const [tethers, links] = await Promise.all([
      api.getClusterConnectionTethers(clusterId).catch(() => []),
      api.getClusterMovableLinks(clusterId).catch(() => []),
    ])
    const key = a => `${a.helix_id}:${a.bp}:${a.direction}`
    const connConnections = (tethers ?? []).map(t => ({
      movingKey: key(t.moving), fixedKey: key(t.fixed), contour: t.contour_nm, rigid: !!t.rigid,
    }))
    const connections = [...(ssd?.connections ?? []), ...connConnections]
    // Movable links (duplex bodies) → the gizmo solves + paints them as intermediate bodies.
    const linkDescs = (links ?? []).map(L => ({
      linkClusterId: L.link_cluster_id,
      helixIds: L.helix_ids,
      domainIds: (L.domain_ids?.length ? L.domain_ids : null),
      tethers: (L.tethers ?? []).map(t => ({
        linkKey: key(t.l), partKey: key(t.part), contour: t.contour_nm, partDragged: !!t.part_dragged,
      })),
    }))
    if (!connections.length && !linkDescs.length) return null
    return {
      connections,
      links: linkDescs,
      resolveWorldPos: makeWorldPosResolver(designRenderer.getBackboneEntries?.() ?? []),
    }
  }

  /** Build the gizmo ssDNA-constraint payload for a cluster: per-tether moving/
   *  fixed anchor keys + a live world-position resolver from backboneEntries. */
  function buildSsdnaPayload(clusterId) {
    const design = store.getState().currentDesign
    return buildTetherPayload(_flexConnections, clusterId, design, designRenderer.getBackboneEntries?.() ?? [])
  }

  /** Build the gizmo ssDNA-constraint payload for a DUPLEX cluster's free-until-taut drag
   *  ([[overhang-duplex-cluster]] P3): fetch the connection-bond tethers from the backend and
   *  render them as {movingKey,fixedKey,contour} + a live world-position resolver. Async (one
   *  GET). Returns null if the cluster has no resolvable tethers (nothing to constrain). */
  async function buildDuplexTautPayload(clusterId) {
    const tethers = await api.getClusterDuplexTethers(clusterId).catch(() => [])
    const key = a => `${a.helix_id}:${a.bp}:${a.direction}`
    const connections = (tethers ?? []).map(t => ({
      movingKey: key(t.moving), fixedKey: key(t.fixed), contour: t.contour_nm,
    }))
    if (!connections.length) return null
    return { connections, resolveWorldPos: makeWorldPosResolver(designRenderer.getBackboneEntries?.() ?? []) }
  }

  // Solve the whole connected network on the server; fix its largest rigid
  // cluster and commit only a globally verified result as one undoable feature.
  async function relaxFlexible(scope, connId = null) {
    if (store.getState().assemblyActive) return
    if (isTranslateRotateActive()) { showToast('Finish the current move first', { severity: 'error' }); return }
    const allConns = store.getState().currentDesign?.flexible_connections ?? []
    if (!allConns.length) { showToast('No flexible segments to relax'); return }

    showOpProgress('Relaxing', 'Solving all connected flexible tethers…', { indeterminate: true })
    try {
      const result = await api.solveFlexibleSegments(scope, connId)
      if (!result?.converged) {
        showToast('Flexible relaxation did not converge', { severity: 'error' })
      } else if (!result.transforms.length) {
        showToast('Flexible segments already relaxed')
      } else {
        const n = result.connections.length
        showToast(`Relaxed ${n} flexible segment${n === 1 ? '' : 's'}; maximum overstretch ${result.max_excess_nm.toFixed(3)} nm`)
      }
    } catch (err) {
      showToast(err?.message || String(err), { severity: 'error' })
    } finally {
      hideOpProgress()
    }
  }

  return { refreshFlexGates, hasGate, hasTetherOption, buildSsdnaPayload, buildTethersPayload, buildDuplexTautPayload, relaxFlexible }
}
