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
//   { kind: 'strand',   id }                        — a whole strand (e.g. an
//                                                     overhang-binding oligo)
//   { kind: 'base', helixId, bp, direction }        — one individual nucleotide
// Each resolves to backbone entries via designRenderer.getBackboneEntries() (every
// entry carries .pos + .nuc.{strand_id, domain_index, overhang_id, helix_id,
// bp_index, direction}); clusters reuse the same membership filter the
// selection/gizmo paths use.
//
// Display-layer only — never touches topology.  Factory:
//   initAnchorGlow({ designRenderer, store }) → { setAnchors, clear, refresh }

import { clusterMemberFilter, clusterNucKeys } from './cluster_entries.js'
import { anchorAtoms, hasAnchorAtoms } from './efield_math.js'

/**
 * Resolve anchor descriptors to the backbone entries they cover.
 * PURE — given the entries + design, returns the flat de-duplicated entry list.
 */
export function resolveAnchorEntries(anchors, backboneEntries, design) {
  if (!anchors?.length || !backboneEntries?.length) return []
  const seen = new Set()
  const out = []
  const push = (e) => { if (!seen.has(e)) { seen.add(e); out.push(e) } }

  // The shared scope format accepts BOTH spellings of every key — the backend resolver
  // documents `'helix_id'|'helixId'`, `'strand_id'|'strandId'`, `'domain_index'|
  // `'domainIndex'`, `'bp'|'bp_index'` — because scopes reach it from the camelCase UI and
  // from snake_case callers (headless scripts, the API, saved manifests). This resolver
  // read only the camelCase half, so an anchor set built anywhere but the picker rendered
  // its chips and highlighted NOTHING: the run was correctly anchored and the viewport
  // showed no halo, which reads as "the anchors were lost".
  const k = (a, ...names) => { for (const n of names) if (a[n] !== undefined) return a[n] }

  for (const a of anchors) {
    if (!a) continue
    if (a.kind === 'overhang') {
      const id = k(a, 'id', 'overhang_id', 'overhangId')
      for (const e of backboneEntries) if (e.nuc?.overhang_id === id) push(e)
    } else if (a.kind === 'domain') {
      const sid = k(a, 'strandId', 'strand_id')
      const di = k(a, 'domainIndex', 'domain_index')
      for (const e of backboneEntries) {
        if (e.nuc?.strand_id === sid && e.nuc?.domain_index === di) push(e)
      }
    } else if (a.kind === 'cluster') {
      const cluster = design?.cluster_transforms?.find((c) => c.id === a.id)
      const f = cluster ? clusterMemberFilter(cluster, design) : null
      if (f) for (const e of backboneEntries) if (f(e.nuc)) push(e)
    } else if (a.kind === 'strand') {
      const sid = k(a, 'id', 'strand_id', 'strandId')
      for (const e of backboneEntries) if (e.nuc?.strand_id === sid) push(e)
    } else if (a.kind === 'base') {
      const hid = k(a, 'helixId', 'helix_id')
      const bp = k(a, 'bp', 'bp_index')
      for (const e of backboneEntries) {
        if (e.nuc?.helix_id === hid && e.nuc?.bp_index === bp
            && e.nuc?.direction === a.direction) push(e)
      }
    }
  }
  return out
}

// ── Per-atom halo (NAMD anchors that name the atoms they hold) ───────────────
//
// A NAMD anchor can hold only SOME atoms of its bases — one phosphorus, one C1′, or all
// ~20 heavy atoms.  With an atomistic representation on, the halo should show exactly
// those atoms rather than one blob per nucleotide, so what you see is what the marker
// PDB pins.
//
// The index below is built from the DESIGN, not from geometry, for two reasons: at
// `cylinders` LOD `getBackboneEntries()` is EMPTY (helix_renderer skips the beads), so a
// geometry-derived index would inherit the long-standing "halo silently draws nothing"
// bug; and the atomistic renderer addresses atoms by `helix:bp:dir` anyway, which is a
// design-level fact.

const _dir = (d) => String(d ?? '').toUpperCase()
const _nucKey = (helixId, bp, direction) => `${helixId}:${bp}:${_dir(direction)}`

/** Merge two atom-name sets for one nucleotide. `null` is the TOP element (all heavy
 *  atoms) and absorbs everything — the same union rule
 *  `backend/core/namd_topology.py::_union_atom_names` applies to residue ordinals, so the
 *  halo cannot claim to hold less than the marker PDB does. */
function _union(a, b) {
  if (a === undefined) return b
  if (a === null || b === null) return null
  return new Set([...a, ...b])
}

/**
 * Anchor descriptors → `Map<'helix:bp:dir', Set<string>|null>`, the atoms each anchored
 * nucleotide holds (`null` = all heavy atoms).
 *
 * Only descriptors that STATE an opinion (`hasAnchorAtoms`) are indexed. An oxDNA anchor
 * or an occupancy-scope pick carries no `atoms` key, keeps the per-nucleotide halo, and
 * so this never changes what those cards draw.
 *
 * `extra_base` / `extension` scopes are skipped, matching `resolveAnchorEntries`, which
 * has no branch for them either.
 *
 * PURE — design in, map out, no geometry and no LOD dependency.
 */
export function buildAnchorAtomIndex(anchors, design) {
  const out = new Map()
  const scoped = (anchors || []).filter(hasAnchorAtoms)
  if (!scoped.length) return out

  const named = scoped.map((a) => {
    const names = anchorAtoms(a)
    return { a, names: names ? new Set(names) : null }
  })
  const add = (key, names) => out.set(key, _union(out.get(key), names))

  // Individual bases need no walk — the descriptor IS the key.
  const domainScoped = []
  for (const entry of named) {
    const a = entry.a
    if (a.kind === 'base') {
      const hid = a.helixId ?? a.helix_id
      const bp = a.bp ?? a.bp_index
      if (hid != null && bp != null) add(_nucKey(hid, bp, a.direction), entry.names)
    } else if (a.kind !== 'extra_base' && a.kind !== 'extension') {
      domainScoped.push(entry)
    }
  }
  if (!domainScoped.length) return out

  // Cluster membership is resolved through the SAME helper the bead halo and the cluster
  // fade use, so a cluster anchor cannot cover a different set of domains here.
  const clusterKeys = new Map()
  for (const { a } of domainScoped) {
    if (a.kind !== 'cluster' || clusterKeys.has(a.id)) continue
    const cluster = design?.cluster_transforms?.find((c) => c.id === a.id)
    clusterKeys.set(a.id, cluster ? clusterNucKeys(cluster, design) : new Set())
  }

  const covers = ({ a }, strand, di, dom) => {
    if (a.kind === 'strand') return strand.id === (a.id ?? a.strand_id ?? a.strandId)
    if (a.kind === 'domain') {
      return strand.id === (a.strandId ?? a.strand_id)
          && di === (a.domainIndex ?? a.domain_index)
    }
    if (a.kind === 'overhang') return dom.overhang_id === (a.id ?? a.overhang_id ?? a.overhangId)
    if (a.kind === 'cluster') {
      const keys = clusterKeys.get(a.id)
      return !!keys && (keys.has(`d:${strand.id}:${di}`) || keys.has(`h:${dom.helix_id}`))
    }
    return false
  }

  for (const strand of design?.strands ?? []) {
    const doms = strand.domains ?? []
    for (let di = 0; di < doms.length; di++) {
      const dom = doms[di]
      if (!dom?.helix_id) continue
      for (const entry of domainScoped) {
        if (!covers(entry, strand, di, dom)) continue
        // REVERSE domains store start_bp > end_bp.
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        for (let bp = lo; bp <= hi; bp++) add(_nucKey(dom.helix_id, bp, dom.direction), entry.names)
      }
    }
  }
  return out
}

/**
 * Halo radius multiple for a per-ATOM purple sphere, by atomistic mode.
 *
 * The coarse-grained halo is 3.6 × the 0.10 nm bead radius = 0.36 nm, which around the
 * ~20 heavy atoms of a base merges into one blob and defeats the point. Ball-and-stick
 * atoms are ~0.07 nm and VdW atoms 0.15–0.18 nm, so each wants a shell that reads as a
 * ring around ONE atom.  Anything that is not an atomistic mode gets the CG value.
 * PURE.
 */
export function anchorAtomGlowScale(mode) {
  if (mode === 'vdw') return 2.6
  if (mode === 'ballstick') return 1.4
  return 3.6
}

export function initAnchorGlow({ designRenderer, store, atomisticRenderer = null } = {}) {
  let _anchors = []
  let _lastGeometry = null

  function _apply() {
    const design = store?.getState?.().currentDesign
    // Anchors that name their atoms get the per-atom halo when an atomistic rep can
    // serve it; everything else keeps the per-nucleotide bead halo. Splitting rather
    // than switching wholesale is what lets a NAMD anchor set and an occupancy scope
    // coexist without one changing how the other draws.
    const withAtoms = _anchors.filter(hasAnchorAtoms)
    let atomEntries = null
    if (withAtoms.length && atomisticRenderer?.anchorAtomEntries) {
      const index = buildAnchorAtomIndex(withAtoms, design)
      if (index.size) {
        atomEntries = atomisticRenderer.anchorAtomEntries(index, {
          scale: anchorAtomGlowScale(atomisticRenderer.getMode?.()),
        })
      }
    }
    // null = the renderer cannot serve this (rep off, atoms not loaded, or a payload
    // with no atom names) — fall back to the coarse halo for ALL anchors rather than
    // dropping the ones that asked for atoms.
    const beadAnchors = atomEntries ? _anchors.filter(a => !hasAnchorAtoms(a)) : _anchors
    const entries = [
      ...(atomEntries ?? []),
      ...resolveAnchorEntries(beadAnchors, designRenderer?.getBackboneEntries?.() || [], design),
    ]
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

  // Entering/leaving an atomistic rep, and the atom fetch landing, both change which
  // halo we can draw. Listening to `nadoc:representation-change` would be too early —
  // it fires before the async atom load resolves, when the atom count is still 0 — so
  // the renderer itself reports when its (mode, atom set) actually changed.
  atomisticRenderer?.onAtomsChanged?.(() => refresh())

  return { setAnchors, clear, refresh }
}
