/**
 * Color helpers extracted from main.js. Pure (Math only). Unit-tested in
 * color_util.test.js.
 */

// Strand-length heatmap domain (nt): clamps below 14 / above 60.
const HEATMAP_MIN = 14, HEATMAP_MAX = 60

/**
 * Packed 0xRRGGBB int → '#rrggbb' string. Masks to 24 bits so negatives /
 * over-range ints (e.g. signed colours) still produce a 6-digit hex.
 * (Deduped from two inline copies in main.js.)
 */
export function hexFromInt(value) {
  return '#' + ((value >>> 0) & 0xffffff).toString(16).padStart(6, '0')
}

// Per-base atom colours (A=green, T=red, G=yellow, C=blue), packed 0xRRGGBB.
export const BASE_HEX = { A: 0x44dd88, T: 0xff5555, G: 0xffcc00, C: 0x55aaff }

/**
 * Build the per-atom base-letter colour map keyed "strand_id:bp_index:direction".
 * `nucLetter` is the iterable of [nuc, baseLetter] pairs from buildNucLetterMap.
 * Pure — the store/geometry read stays in the caller.
 */
export function atomColorsFromLetters(nucLetter) {
  const out = new Map()
  for (const [nuc, ch] of (nucLetter ?? [])) {
    out.set(`${nuc.strand_id}:${nuc.bp_index}:${nuc.direction}`, BASE_HEX[ch])
  }
  return out
}

// Cluster-coloring palette for atomistic/surface strand colours (packed 0xRRGGBB).
export const ATOM_STAPLE_PALETTE = [
  0xff6b6b, 0xffd93d, 0x6bcb77, 0xf9844a, 0xa29bfe, 0xff9ff3,
  0x00cec9, 0xe17055, 0x74b9ff, 0x55efc4, 0xfdcb6e, 0xd63031,
]

/**
 * Resolve per-strand colours for the atomistic / surface renderers from a store
 * snapshot. Returns a Map<strand_id, packedInt>. Pure: the caller reads the store
 * and builds `staplePalette` (the buildStapleColorMap result, or null when design/
 * geometry are missing) so this stays free of the helix_renderer import.
 *
 * Precedence (later wins): base strandColors → strand-group colours → scaffold blue
 * → palette fill for unassigned staples → loop/circular red (unless cluster mode) →
 * cluster-palette override (cluster mode only).
 */
export function computeAtomStrandColors(state, staplePalette) {
  const { strandColors, strandGroups, currentDesign, coloringMode, loopStrandIds } = state
  const effective = { ...strandColors }
  for (const g of strandGroups ?? []) {
    if (g.color) {
      const hex = parseInt(g.color.replace('#', ''), 16)
      for (const sid of g.strandIds) effective[sid] = hex
    }
  }
  // scaffold gets cadnano blue
  for (const s of currentDesign?.strands ?? []) {
    if (s.strand_type === 'scaffold' && !(s.id in effective)) {
      effective[s.id] = 0x0070bb
    }
  }
  // Fill in palette-assigned colours for every staple strand so atomistic
  // matches the bead view exactly (atoms whose strand is not in the map fall
  // back to CPK in the renderer, which would mismatch the beads).
  if (staplePalette) {
    for (const s of currentDesign.strands ?? []) {
      if (!(s.id in effective)) {
        const p = staplePalette.get(s.id)
        if (p != null) effective[s.id] = p
      }
    }
  }
  // Loop / circular-strand red highlight (matches helix_renderer.nucColor).
  // Skip in cluster mode — cluster fill below should win on clustered strands.
  if (loopStrandIds?.length && coloringMode !== 'cluster') {
    for (const sid of loopStrandIds) effective[sid] = 0xff3333
  }
  // 'cluster' coloring: replace each strand's color with its cluster's
  // palette colour, keyed off the strand's first domain helix.
  // 'base' is left as strand colour (atomistic lacks per-atom base mapping).
  if (coloringMode === 'cluster' && currentDesign?.cluster_transforms?.length) {
    for (const [sid, ci] of resolveStrandClusters(currentDesign)) {
      // A user-set cluster colour overrides the auto palette slot, matching the CG
      // path (helix_renderer/palette.js::buildClusterColorLookup).
      const custom = currentDesign.cluster_transforms[ci]?.color
      effective[sid] = (typeof custom === 'string' && /^#[0-9a-fA-F]{6}$/.test(custom))
        ? parseInt(custom.slice(1), 16)
        : ATOM_STAPLE_PALETTE[ci % ATOM_STAPLE_PALETTE.length]
    }
  }
  return new Map(Object.entries(effective).map(([k, v]) => [k, typeof v === 'number' ? v : parseInt(v.replace('#',''), 16)]))
}

/**
 * strand id → owning cluster INDEX. **SURFACE ONLY.**
 *
 * Collapses each strand onto the FIRST of its domains any cluster claims, so a strand
 * spanning two clusters takes one of them. That is WRONG for anything that can do
 * better — it is why the scaffold, which passes through nearly every cluster, was
 * painted a single colour in atomistic (reported 2026-08-01 on VoltronCoreScad: the
 * scaffold inside Cluster 3 came out Cluster 4's colour). Atomistic now uses
 * `buildNucClusterIndex` and resolves per nucleotide.
 *
 * The surface used to have the same problem for the same reason. It no longer does: the
 * backend ships `vertex_nuc_index_table` / `vertex_nuc_index` alongside the strand pair
 * (2026-08-01), so the surface resolves per nucleotide too. These strand-level helpers
 * survive only as the FALLBACK for payloads without that block — the oxDNA frame-surface
 * overlay, or a surface cached before it shipped.
 *
 * @param {object} currentDesign
 * @returns {Map<string, number>} strand id → cluster index
 */
export function resolveStrandClusters(currentDesign) {
  const out = new Map()
  const clusters = currentDesign?.cluster_transforms ?? []
  if (!clusters.length) return out
  const helixCluster = new Map()
  const domainCluster = new Map()
  const strandMap = new Map((currentDesign.strands ?? []).map(s => [s.id, s]))
  clusters.forEach((c, i) => {
    if (c.domain_ids?.length) {
      const bridges = new Set()
      for (const dr of c.domain_ids) {
        domainCluster.set(`${dr.strand_id}:${dr.domain_index}`, i)
        const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
        if (dom) bridges.add(dom.helix_id)
      }
      for (const hid of (c.helix_ids ?? [])) if (!bridges.has(hid)) helixCluster.set(hid, i)
    } else {
      for (const hid of (c.helix_ids ?? [])) helixCluster.set(hid, i)
    }
  })
  for (const s of currentDesign.strands ?? []) {
    for (let di = 0; di < (s.domains ?? []).length; di++) {
      const k = `${s.id}:${di}`
      if (domainCluster.has(k)) { out.set(s.id, domainCluster.get(k)); break }
      const hid = s.domains[di].helix_id
      if (helixCluster.has(hid)) { out.set(s.id, helixCluster.get(hid)); break }
    }
  }
  return out
}

/**
 * strand id → per-cluster OPACITY. **SURFACE ONLY** — see resolveStrandClusters for
 * why atomistic no longer uses this. Atomistic's twin is `computeAtomNucAlphas`.
 *
 * Unlike colour, opacity applies in EVERY coloring mode — so this does not consult
 * `coloringMode` at all. Strands in no cluster, and clusters at full opacity, are
 * omitted: an empty map is the signal that nothing needs fading, which is what keeps
 * the whole path free for designs nobody has styled.
 *
 * @param {object} currentDesign
 * @returns {Map<string, number>} strand id → alpha in [0,1)
 */
export function computeAtomStrandAlphas(currentDesign) {
  const out = new Map()
  const clusters = currentDesign?.cluster_transforms ?? []
  if (!clusters.length) return out
  for (const [sid, ci] of resolveStrandClusters(currentDesign)) {
    const a = clusters[ci]?.opacity
    if (typeof a === 'number' && a < 1) out.set(sid, Math.max(0, a))
  }
  return out
}

/**
 * `helix:bp:dir` → owning cluster INDEX, for the atomistic path.
 *
 * WHY this exists on top of resolveStrandClusters: a strand can pass through several
 * clusters — the scaffold passes through nearly all of them — so collapsing a strand
 * onto ONE cluster paints every scaffold atom with whichever cluster happened to own
 * its first domain. On VoltronCoreScad that is Cluster 4, so the scaffold segments
 * genuinely inside Cluster 3 came out Cluster 4's colour.
 *
 * Atoms carry no `domain_index`, but they DO carry helix + bp + direction, so walking
 * the design's domains recovers the (strand_id, domain_index) an atom belongs to. Each
 * domain is then resolved by the SAME two-tier lookup the bead view uses
 * (helix_renderer/palette.js::buildClusterColorLookup semantics: a domain-level entry
 * beats the helix-level fallback), which is what makes atomistic agree with the beads.
 *
 * Cost is one entry per nucleotide of every clustered domain — tens of thousands for a
 * large origami, built once per design change, O(1) per atom afterwards. A per-atom
 * range scan would be O(domains) against millions of atoms.
 *
 * @param {object} design
 * @returns {Map<string, number>} 'helix:bp:dir' → cluster index
 */
export function buildNucClusterIndex(design) {
  const out = new Map()
  const clusters = design?.cluster_transforms ?? []
  if (!clusters.length) return out

  const helixCluster = new Map()   // helix_id → cluster index (the fallback tier)
  const domainCluster = new Map()  // 'strand_id:domain_index' → cluster index (wins)
  const strandMap = new Map((design.strands ?? []).map(s => [s.id, s]))
  clusters.forEach((c, i) => {
    if (c.domain_ids?.length) {
      const bridges = new Set()
      for (const dr of c.domain_ids) {
        domainCluster.set(`${dr.strand_id}:${dr.domain_index}`, i)
        const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
        if (dom) bridges.add(dom.helix_id)
      }
      for (const hid of (c.helix_ids ?? [])) if (!bridges.has(hid)) helixCluster.set(hid, i)
    } else {
      for (const hid of (c.helix_ids ?? [])) helixCluster.set(hid, i)
    }
  })

  for (const s of design.strands ?? []) {
    const doms = s.domains ?? []
    for (let di = 0; di < doms.length; di++) {
      const d = doms[di]
      if (!d?.helix_id) continue
      const ci = domainCluster.get(`${s.id}:${di}`) ?? helixCluster.get(d.helix_id)
      if (ci == null) continue
      // REVERSE domains store start_bp > end_bp.
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      for (let bp = lo; bp <= hi; bp++) out.set(`${d.helix_id}:${bp}:${d.direction}`, ci)
    }
  }
  return out
}

/**
 * `helix:bp:dir` → per-cluster COLOUR for the atomistic path. Empty unless the viewer
 * is in cluster-coloring mode. Explicit colour beats the auto palette slot, matching
 * the bead view.
 * @param {object} state  the store state ({ currentDesign, coloringMode })
 * @returns {Map<string, number>} packed 0xRRGGBB
 */
export function computeAtomNucColors(state) {
  const out = new Map()
  const design = state?.currentDesign
  if (state?.coloringMode !== 'cluster') return out
  const clusters = design?.cluster_transforms ?? []
  if (!clusters.length) return out
  const resolved = clusters.map((c, i) => {
    const custom = c?.color
    return (typeof custom === 'string' && /^#[0-9a-fA-F]{6}$/.test(custom))
      ? parseInt(custom.slice(1), 16)
      : ATOM_STAPLE_PALETTE[i % ATOM_STAPLE_PALETTE.length]
  })
  for (const [k, ci] of buildNucClusterIndex(design)) out.set(k, resolved[ci])
  return out
}

/**
 * `helix:bp:dir` → per-cluster OPACITY for the atomistic path. Unlike colour this
 * ignores coloringMode — a fade applies in every mode. Clusters at full opacity are
 * omitted, so an unstyled design yields an empty map and costs nothing.
 * @param {object} design
 * @returns {Map<string, number>}
 */
export function computeAtomNucAlphas(design) {
  const out = new Map()
  const clusters = design?.cluster_transforms ?? []
  if (!clusters.some(c => typeof c?.opacity === 'number' && c.opacity < 1)) return out
  for (const [k, ci] of buildNucClusterIndex(design)) {
    const a = clusters[ci]?.opacity
    if (typeof a === 'number' && a < 1) out.set(k, Math.max(0, a))
  }
  return out
}

/** Map an nt count to a blue→red heatmap colour (packed 0xRRGGBB int). */
export function heatmapHex(ntCount) {
  const t = Math.max(0, Math.min(1, (ntCount - HEATMAP_MIN) / (HEATMAP_MAX - HEATMAP_MIN)))
  const hue = Math.round(240 * (1 - t))
  // HSL → hex
  const s = 0.9, l = 0.5
  const k = n => (n + hue / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const ch = n => Math.round((l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))) * 255)
  return (ch(0) << 16) | (ch(8) << 8) | ch(4)
}
