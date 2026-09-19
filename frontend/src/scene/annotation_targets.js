/**
 * Resolve an annotation's target refs to live backbone entries, an anchor
 * point, and a human label. Pure: entries/design in, data out.
 *
 * `entries` are design_renderer backbone entries `{ nuc, pos }`; `pos` is the
 * live THREE.Vector3 (kept current by unfold / cluster / cadnano overlays), so
 * callers cache the matched entries and read `.pos` every frame.
 */
import { baseKey } from './base_ref.js'
import { ovhgDomainIds } from './design_queries.js'

const KIND_LABELS = {
  base: 'Base', end: 'End', domain: 'Domain', strand: 'Strand', cluster: 'Cluster',
  crossover: 'Crossover', bond: 'Bond', overhang: 'Overhang', extension: 'Extension',
  protein: 'Protein', nanoparticle: 'Nanoparticle',
}

const domainKey = (strandId, index) => `${strandId}:${index}`
const nucKey = (helixId, bp, direction) => `${helixId}:${bp}:${direction}`

/** Sets of identities the refs select; one pass over entries then tests membership. */
export function buildTargetMatcher(refs, design) {
  const m = { strands: new Set(), domains: new Set(), helices: new Set(), bases: new Set(), extHelices: new Set() }
  for (const ref of refs ?? []) {
    switch (ref.kind) {
      case 'strand': m.strands.add(ref.id); break
      case 'domain': m.domains.add(domainKey(ref.strandId, ref.domainIndex)); break
      case 'base': case 'end': m.bases.add(ref.key); break
      case 'bond': m.bases.add(ref.fromKey); m.bases.add(ref.toKey); break
      case 'extension': m.extHelices.add(`__ext_${ref.id}`); break
      case 'cluster': {
        const cluster = design?.cluster_transforms?.find(c => c.id === ref.id)
        if (!cluster) break
        if (cluster.domain_ids?.length) for (const d of cluster.domain_ids) m.domains.add(domainKey(d.strand_id, d.domain_index))
        else for (const h of cluster.helix_ids ?? []) m.helices.add(h)
        break
      }
      case 'overhang':
        for (const d of ovhgDomainIds(ref.id, design) ?? []) m.domains.add(domainKey(d.strand_id, d.domain_index))
        break
      case 'crossover': {
        if (ref.subtype === 'forced_ligation') {
          const fl = design?.forced_ligations?.find(x => x.id === ref.id)
          if (fl) {
            m.bases.add(nucKey(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction))
            m.bases.add(nucKey(fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction))
          }
        } else {
          const xo = design?.crossovers?.find(x => x.id === ref.id)
          if (xo) for (const half of [xo.half_a, xo.half_b]) m.bases.add(nucKey(half.helix_id, half.index, half.strand))
        }
        break
      }
      default: break // protein / nanoparticle carry no backbone beads; see annotation_external.js
    }
  }
  return m
}

/** Backbone entries belonging to the refs. */
export function matchTargetEntries(refs, design, entries) {
  const m = buildTargetMatcher(refs, design)
  const empty = !m.strands.size && !m.domains.size && !m.helices.size && !m.bases.size && !m.extHelices.size
  if (empty || !entries?.length) return []
  const out = []
  for (const entry of entries) {
    const nuc = entry?.nuc
    if (!nuc || !entry.pos) continue
    if (m.strands.has(nuc.strand_id)
      || (m.helices.size && m.helices.has(nuc.helix_id))
      || (m.extHelices.size && m.extHelices.has(nuc.helix_id))
      || (m.domains.size && nuc.domain_index != null && m.domains.has(domainKey(nuc.strand_id, nuc.domain_index)))
      || (m.bases.size && m.bases.has(baseKey(nuc, nuc.copy_k ?? 0)))) out.push(entry)
  }
  return out
}

/** Base/end/bond keys the backbone entries could not supply (e.g. extra crossover bases). */
export function unresolvedBaseKeys(refs, matched) {
  const found = new Set(matched.map(e => baseKey(e.nuc, e.nuc.copy_k ?? 0)))
  const out = []
  for (const ref of refs ?? []) {
    const keys = ref.kind === 'base' || ref.kind === 'end' ? [ref.key] : ref.kind === 'bond' ? [ref.fromKey, ref.toKey] : []
    for (const key of keys) if (!found.has(key)) out.push(key)
  }
  return out
}

/**
 * Anchor for the leader: the member point nearest the centroid, so a strand's
 * leader lands on real geometry rather than in the empty middle of a loop.
 */
export function anchorFromPoints(points) {
  if (!points?.length) return null
  if (points.length === 1) return { x: points[0].x, y: points[0].y, z: points[0].z }
  let cx = 0, cy = 0, cz = 0
  for (const p of points) { cx += p.x; cy += p.y; cz += p.z }
  cx /= points.length; cy /= points.length; cz /= points.length
  let best = points[0], bestD = Infinity
  for (const p of points) {
    const d = (p.x - cx) ** 2 + (p.y - cy) ** 2 + (p.z - cz) ** 2
    if (d < bestD) { bestD = d; best = p }
  }
  return { x: best.x, y: best.y, z: best.z }
}

const shortId = id => (String(id).length > 10 ? `${String(id).slice(0, 8)}…` : String(id))

function describeOne(ref, design) {
  const kind = KIND_LABELS[ref.kind] ?? ref.kind
  switch (ref.kind) {
    case 'strand': {
      const s = design?.strands?.find(x => x.id === ref.id)
      return `${kind} · ${s?.name || shortId(ref.id)}`
    }
    case 'domain': {
      const s = design?.strands?.find(x => x.id === ref.strandId)
      return `${kind} ${ref.domainIndex + 1} · ${s?.name || shortId(ref.strandId)}`
    }
    case 'base': case 'end': return `${kind} · ${ref.key}`
    case 'cluster': return `${kind} · ${design?.cluster_transforms?.find(c => c.id === ref.id)?.name || shortId(ref.id)}`
    case 'overhang': return `${kind} · ${shortId(ref.id)}`
    case 'nanoparticle': {
      const p = design?.nanoparticles?.find(x => x.id === ref.id)
      return p ? `${p.kind === 'quantum_dot' ? 'Quantum dot' : 'Gold nanosphere'} · ${p.diameter_nm} nm` : `${kind} · ${shortId(ref.id)}`
    }
    default: return `${kind} · ${shortId(ref.id ?? ref.fromKey ?? '')}`
  }
}

/** One-line target summary for the sidebar. */
export function describeTarget(refs, design) {
  if (!refs?.length) return 'No target'
  if (refs.length === 1) return describeOne(refs[0], design)
  const counts = new Map()
  for (const ref of refs) counts.set(ref.kind, (counts.get(ref.kind) ?? 0) + 1)
  const parts = [...counts].map(([kind, n]) => `${n} ${(KIND_LABELS[kind] ?? kind).toLowerCase()}${n > 1 ? 's' : ''}`)
  return `${refs.length} items · ${parts.join(', ')}`
}
