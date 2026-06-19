// anchor_glow.js — purple glow over the design's oxDNA anchor (fixed) elements.
//
// When a user configures an E-field run with anchors (Dynamics tab), the anchored
// strands/clusters are pinned in place — this module highlights exactly those beads
// in a purple halo so it's obvious what's fixed (vs the green selection glow).
//
// Anchors come from ui/oxdna_anchors_setup.js as descriptors:
//   { kind: 'overhang', id }                       — an overhang strand
//   { kind: 'domain',   strandId, domainIndex }    — one domain of a strand
//   { kind: 'cluster',  id }                        — a cluster of helices
// Each resolves to backbone entries via designRenderer.getBackboneEntries() (every
// entry carries .pos + .nuc.{strand_id, domain_index, overhang_id}); clusters reuse
// the same membership filter the selection/gizmo paths use.
//
// Display-layer only — never touches topology.  Factory:
//   initAnchorGlow({ designRenderer, store }) → { setAnchors, clear, refresh }

import { clusterMemberFilter } from './cluster_gizmo.js'

/**
 * Resolve anchor descriptors to the backbone entries they cover.
 * PURE — given the entries + design, returns the flat de-duplicated entry list.
 */
export function resolveAnchorEntries(anchors, backboneEntries, design) {
  if (!anchors?.length || !backboneEntries?.length) return []
  const seen = new Set()
  const out = []
  const push = (e) => { if (!seen.has(e)) { seen.add(e); out.push(e) } }

  for (const a of anchors) {
    if (!a) continue
    if (a.kind === 'overhang') {
      for (const e of backboneEntries) if (e.nuc?.overhang_id === a.id) push(e)
    } else if (a.kind === 'domain') {
      for (const e of backboneEntries) {
        if (e.nuc?.strand_id === a.strandId && e.nuc?.domain_index === a.domainIndex) push(e)
      }
    } else if (a.kind === 'cluster') {
      const cluster = design?.cluster_transforms?.find((c) => c.id === a.id)
      const f = cluster ? clusterMemberFilter(cluster, design) : null
      if (f) for (const e of backboneEntries) if (f(e.nuc)) push(e)
    }
  }
  return out
}

export function initAnchorGlow({ designRenderer, store } = {}) {
  let _anchors = []
  let _lastGeometry = null

  function _apply() {
    const entries = resolveAnchorEntries(
      _anchors, designRenderer?.getBackboneEntries?.() || [], store?.getState?.().currentDesign)
    if (entries.length) designRenderer?.setAnchorGlow?.(entries)
    else designRenderer?.clearAnchorGlow?.()
  }

  /** Replace the highlighted anchor set (pass [] to clear). */
  function setAnchors(anchors) {
    _anchors = Array.isArray(anchors) ? anchors : []
    _apply()
  }

  function clear() { _anchors = []; designRenderer?.clearAnchorGlow?.() }

  /** Re-resolve against the current backbone entries (after a geometry rebuild). */
  function refresh() { if (_anchors.length) _apply() }

  // A geometry rebuild replaces the backbone entries (and clears the glow layer);
  // re-resolve so the purple halo tracks the new beads.  Registered after the
  // designRenderer subscriber, so getBackboneEntries() is already fresh here.
  store?.subscribe?.(() => {
    const geo = store.getState().currentGeometry
    if (geo !== _lastGeometry) { _lastGeometry = geo; refresh() }
  })

  return { setAnchors, clear, refresh }
}
