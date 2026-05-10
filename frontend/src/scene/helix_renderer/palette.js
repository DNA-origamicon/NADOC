// ── Palette ───────────────────────────────────────────────────────────────────

export const C = {
  scaffold_backbone: 0x29b6f6,
  scaffold_slab:     0x0277bd,
  scaffold_arrow:    0x0288d1,
  axis:              0x555566,
  highlight_red:     0xff3333,
  highlight_blue:    0x3399ff,
  highlight_yellow:  0xffdd00,
  highlight_magenta: 0xff00ff,
  highlight_orange:  0xff8c00,
  overhang:          0xf5a623,   // amber — single-stranded overhang domains
  white:             0xffffff,
  dim:               0x15202e,
  unassigned:        0x445566,
}

// Canonical palette — must match backend/core/constants.py STAPLE_PALETTE
// and frontend/src/cadnano-editor/pathview.js STAPLE_PALETTE exactly.
export const STAPLE_PALETTE = [
  0xff6b6b, 0xffd93d, 0x6bcb77, 0xf9844a, 0xa29bfe, 0xff9ff3,
  0x00cec9, 0xe17055, 0x74b9ff, 0x55efc4, 0xfdcb6e, 0xd63031,
]

// Coloring-mode palettes. Base colours mirror sequence_overlay.LETTER_DEFS.
export const BASE_COLORS = { A: 0x44dd88, T: 0xff5555, G: 0xffcc00, C: 0x55aaff }

/**
 * Build a per-nucleotide letter lookup ('A'|'T'|'G'|'C') for the given design.
 * Mirrors the assignment logic in sequence_overlay.js so on-bead colours
 * match the letter sprites exactly.  Nucs without an assigned letter are absent.
 *
 * @param {object} design
 * @param {Array}  nucs    nucleotide objects whose .strand_id, .domain_index,
 *                         .bp_index, .direction, .overhang_id are populated.
 * @returns {Map<object,'A'|'T'|'G'|'C'>}
 */
export function buildNucLetterMap(design, nucs) {
  const nucLetter = new Map()
  if (!design) return nucLetter

  const seqMap = new Map()
  for (const s of (design.strands ?? [])) if (s.sequence) seqMap.set(s.id, s.sequence)
  if (seqMap.size) {
    const byStrand = new Map()
    for (const nuc of nucs) {
      if (!nuc.strand_id) continue
      if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
      byStrand.get(nuc.strand_id).push(nuc)
    }
    for (const arr of byStrand.values()) {
      arr.sort((a, b) => {
        const di = (a.domain_index ?? 0) - (b.domain_index ?? 0)
        if (di !== 0) return di
        return a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
      })
    }
    for (const [sid, arr] of byStrand) {
      const seq = seqMap.get(sid)
      if (!seq) continue
      for (let i = 0; i < arr.length; i++) {
        const ch = seq[i]?.toUpperCase()
        if (ch && 'ATGC'.includes(ch)) nucLetter.set(arr[i], ch)
      }
    }
  }

  const ovhgSeqMap = new Map()
  for (const o of (design.overhangs ?? [])) if (o.sequence) ovhgSeqMap.set(o.id, o.sequence)
  if (ovhgSeqMap.size) {
    const byOvhg = new Map()
    for (const nuc of nucs) {
      if (!nuc.overhang_id) continue
      if (!byOvhg.has(nuc.overhang_id)) byOvhg.set(nuc.overhang_id, [])
      byOvhg.get(nuc.overhang_id).push(nuc)
    }
    for (const [oid, arr] of byOvhg) {
      const seq = ovhgSeqMap.get(oid)
      if (!seq) continue
      arr.sort((a, b) =>
        a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index)
      for (let i = 0; i < arr.length; i++) {
        if (nucLetter.has(arr[i])) continue
        const ch = seq[i]?.toUpperCase()
        if (ch && 'ATGC'.includes(ch)) nucLetter.set(arr[i], ch)
      }
    }
  }
  return nucLetter
}

/**
 * Build a (nuc-or-domain) → cluster-index lookup.  Mirrors the membership rule
 * used by assembly_renderer._clusterMemberFilter: domain-level entries (bridges)
 * win over the helix-level fallback.
 *
 * @param {object} design
 * @returns {(nuc:object) => number|undefined}
 */
export function buildClusterLookup(design) {
  const clusters = design?.cluster_transforms ?? []
  if (!clusters.length) return () => undefined

  const helixToCluster  = new Map()   // helix_id → cluster_index
  const domainToCluster = new Map()   // "strand_id:domain_index" → cluster_index
  const strands = design?.strands ?? []

  // Bucket strand domains by helix once so the per-helix coverage check below
  // is cheap when a cluster lists hundreds of domain_ids.
  const domainsByHelix = new Map()
  for (const s of strands) {
    for (let di = 0; di < (s.domains ?? []).length; di++) {
      const d = s.domains[di]
      if (!d?.helix_id) continue
      let arr = domainsByHelix.get(d.helix_id)
      if (!arr) { arr = []; domainsByHelix.set(d.helix_id, arr) }
      arr.push({ key: `${s.id}:${di}`, helix_id: d.helix_id })
    }
  }

  for (let i = 0; i < clusters.length; i++) {
    const c = clusters[i]
    if (c.domain_ids?.length) {
      const keys = new Set()
      for (const dr of c.domain_ids) {
        const k = `${dr.strand_id}:${dr.domain_index}`
        keys.add(k)
        domainToCluster.set(k, i)
      }
      // A helix is "owned" by this cluster when every strand domain on it
      // appears in keys (full coverage). It's a "bridge" only when SOME of
      // its domains are in keys and others aren't (partial coverage). Mirrors
      // the corrected backend `_overhang_owning_cluster_id` rule.
      for (const hid of (c.helix_ids ?? [])) {
        const arr = domainsByHelix.get(hid) ?? []
        let allCovered = true
        for (const d of arr) {
          if (!keys.has(d.key)) { allCovered = false; break }
        }
        if (allCovered) helixToCluster.set(hid, i)
      }
    } else {
      for (const hid of (c.helix_ids ?? [])) helixToCluster.set(hid, i)
    }
  }
  return (nuc) => {
    if (nuc?.strand_id != null && nuc?.domain_index != null) {
      const k = `${nuc.strand_id}:${nuc.domain_index}`
      if (domainToCluster.has(k)) return domainToCluster.get(k)
    }
    return helixToCluster.get(nuc?.helix_id)
  }
}

export function buildStapleColorMap(geometry, design) {
  const strands    = design?.strands   ?? []
  const crossovers = design?.crossovers ?? []

  // Palette index = position in design.strands (full list, including scaffolds).
  // This mirrors the 2D cadnano editor's pathview `strandColor(strands[si], si)`
  // exactly so that staples without an explicit strand.color render the same
  // colour in both views on initial load. Filtering scaffolds out (as the old
  // implementation did) shifted every staple's palette slot relative to
  // pathview, which is why colours diverged before any user color assignment.
  const strandIdxOf = new Map(strands.map((s, i) => [s.id, i]))

  // Union-find over design.strands indices: strands joined by a non-ligated
  // crossover share a palette color. In practice this fires rarely (server-side
  // ligation collapses most crossovers into single strands), but the merge is
  // preserved so the 3D view still groups topology-connected oligos visually.
  const parent = Array.from({length: strands.length}, (_, i) => i)
  function find(i) { return parent[i] === i ? i : (parent[i] = find(parent[i])) }
  function union(a, b) { if (a >= 0 && b >= 0) parent[find(a)] = find(b) }

  for (const xo of crossovers) {
    const sA = strands.findIndex(s => s.strand_type === 'staple' && s.domains.some(d =>
      d.helix_id  === xo.half_a.helix_id && d.direction === xo.half_a.strand &&
      Math.min(d.start_bp, d.end_bp) <= xo.half_a.index &&
      xo.half_a.index <= Math.max(d.start_bp, d.end_bp)))
    const sB = strands.findIndex(s => s.strand_type === 'staple' && s.domains.some(d =>
      d.helix_id  === xo.half_b.helix_id && d.direction === xo.half_b.strand &&
      Math.min(d.start_bp, d.end_bp) <= xo.half_b.index &&
      xo.half_b.index <= Math.max(d.start_bp, d.end_bp)))
    union(sA, sB)
  }

  const map = new Map()   // strand_id → hex color
  for (const nuc of geometry) {
    if (!nuc.strand_id || nuc.strand_type === 'scaffold' || map.has(nuc.strand_id)) continue
    const si         = strandIdxOf.get(nuc.strand_id) ?? -1
    const paletteIdx = si >= 0 ? find(si) : map.size
    map.set(nuc.strand_id, STAPLE_PALETTE[paletteIdx % STAPLE_PALETTE.length])
  }
  return map
}

export function nucColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_backbone
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
export function nucSlabColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_slab
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
export function nucArrowColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_arrow
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
