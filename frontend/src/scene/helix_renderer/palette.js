// ── Palette ───────────────────────────────────────────────────────────────────

import { isAutoCluster } from '../cluster_entries.js'
import { assembleOverhangSequence } from '../design_queries.js'

export const C = {
  scaffold_backbone: 0x0070bb,
  scaffold_slab:     0x0277bd,
  scaffold_arrow:    0x0288d1,
  axis:              0x555566,
  highlight_red:     0xff3333,
  highlight_blue:    0x3399ff,
  highlight_yellow:  0xffdd00,
  highlight_magenta: 0xff00ff,
  highlight_orange:  0xff8c00,
  overhang:          0xf5a623,   // amber — single-stranded overhang domains
  oh_binder:         0xc050d0,   // magenta — overhang-binding oligo (matches CLR_OH_BINDER)
  white:             0xffffff,
  dim:               0x15202e,
  dim_gray:          0xbbbbbb,
  unassigned:        0x445566,
}

// Canonical palette. Must match, exactly and in order:
//   backend/core/constants.py            STAPLE_PALETTE       ('#rrggbb' strings)
//   backend/core/surface.py              _STAPLE_PALETTE_HEX  (0xRRGGBB ints)
//   cadnano-editor/pathview/palette.js   STAPLE_PALETTE       ('#rrggbb' strings)
//   scene/color_util.js                  ATOM_STAPLE_PALETTE  (0xrrggbb ints)
//   scene/selection_manager.js           PICKER_COLORS        ({hex, css, label})
// Frontend consumers import from HERE — do not re-declare it locally.
// (ui/spreadsheet.js did exactly that until 2026-07-30, with different colours, so the
//  strand panel and the exported .xlsx disagreed with the 3D view for every staple
//  whose `color` was null. See memory/project_tech_debt.md.)
export const STAPLE_PALETTE = [
  0xff6b6b, 0xffd93d, 0x6bcb77, 0xf9844a, 0xa29bfe, 0xff9ff3,
  0x00cec9, 0xe17055, 0x74b9ff, 0x55efc4, 0xfdcb6e, 0xd63031,
]

// Coloring-mode palettes. Base colours mirror sequence_overlay.LETTER_DEFS.
export const BASE_COLORS = { A: 0x44dd88, T: 0xff5555, G: 0xffcc00, C: 0x55aaff }

function _orderNucleotides5to3(nucs) {
  const copyIdx = new Map()
  const seen = new Map()
  for (const nuc of nucs) {
    const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
    const copy = seen.get(key) ?? 0
    copyIdx.set(nuc, copy)
    seen.set(key, copy + 1)
  }
  nucs.sort((a, b) => {
    const domain = (a.domain_index ?? 0) - (b.domain_index ?? 0)
    if (domain !== 0) return domain
    const bp = a.direction === 'FORWARD'
      ? a.bp_index - b.bp_index
      : b.bp_index - a.bp_index
    if (bp !== 0) return bp
    const copies = (copyIdx.get(a) ?? 0) - (copyIdx.get(b) ?? 0)
    return a.direction === 'FORWARD' ? copies : -copies
  })
  return nucs
}

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

  // Synthetic extension geometry carries the exact residue identity. Its
  // ext_k increases away from the anchor, which reverses chemical sequence at
  // a 5′ tail; the backend has already applied that authoritative rule.
  for (const nuc of nucs) {
    const base = String(nuc?.nucleobase ?? '').toUpperCase()
    if (BASE_COLORS[base] != null) nucLetter.set(nuc, base)
  }

  const seqMap = new Map()
  for (const s of (design.strands ?? [])) if (s.sequence) seqMap.set(s.id, s.sequence)
  if (seqMap.size) {
    const byStrand = new Map()
    for (const nuc of nucs) {
      // Strand.sequence covers domains only; extensions own a separate sequence.
      if (!nuc.strand_id || nuc.extension_id != null) continue
      if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
      byStrand.get(nuc.strand_id).push(nuc)
    }
    for (const arr of byStrand.values()) _orderNucleotides5to3(arr)
    for (const [sid, arr] of byStrand) {
      const seq = seqMap.get(sid)
      if (!seq) continue
      for (let i = 0; i < arr.length; i++) {
        const ch = seq[i]?.toUpperCase()
        if (ch && 'ATGC'.includes(ch)) nucLetter.set(arr[i], ch)
      }
    }
  }

  const overhangMap = new Map((design.overhangs ?? []).map(overhang => [overhang.id, overhang]))
  if (overhangMap.size) {
    const byOvhg = new Map()
    for (const nuc of nucs) {
      if (!nuc.overhang_id) continue
      if (!byOvhg.has(nuc.overhang_id)) byOvhg.set(nuc.overhang_id, [])
      byOvhg.get(nuc.overhang_id).push(nuc)
    }
    for (const [oid, arr] of byOvhg) {
      const overhang = overhangMap.get(oid)
      if (!overhang) continue
      _orderNucleotides5to3(arr)
      const seq = assembleOverhangSequence(overhang, arr.length)
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

/** "#rrggbb" → packed 0xRRGGBB, or null for anything malformed. */
function _hexToInt(c) {
  return (typeof c === 'string' && /^#[0-9a-fA-F]{6}$/.test(c))
    ? parseInt(c.slice(1), 16)
    : null
}

/**
 * Build a (nuc-or-domain) → cluster COLOUR lookup for `coloringMode === 'cluster'`.
 *
 * A cluster's user-set `color` overrides its automatic palette slot; a cluster with
 * no colour keeps `STAPLE_PALETTE[index % 12]`, so a design where nobody has picked
 * a colour renders exactly as it always did.
 *
 * Resolution when clusters OVERLAP (two clusters listing the same helix, which is
 * normal for scaffold-vs-geometry cluster pairs):
 *
 *     tier:          a domain-level entry beats the helix-level fallback
 *                    (unchanged — same rule as buildClusterLookup)
 *     within a tier: a cluster with an explicit colour beats one still on the
 *                    auto palette, so the swatch you just set is never silently
 *                    overridden by an unstyled cluster that happens to be later
 *                    in the array
 *     tie:           the later array entry wins (buildClusterLookup's rule)
 *
 * Colours are resolved once per cluster here, not per nucleotide — applyColoring
 * runs this across every nucleotide in the design.
 *
 * @param {object} design
 * @returns {(nuc:object) => number|undefined}   packed 0xRRGGBB
 */
export function buildClusterColorLookup(design) {
  const clusters = design?.cluster_transforms ?? []
  if (!clusters.length) return () => undefined

  // Per-cluster resolved colour + whether the user picked it (the tiebreak rank).
  const colorOf = clusters.map((c, i) => _hexToInt(c?.color) ?? STAPLE_PALETTE[i % STAPLE_PALETTE.length])
  const explicit = clusters.map(c => _hexToInt(c?.color) != null)

  const helixWin  = new Map()   // helix_id → cluster index
  const domainWin = new Map()   // "strand_id:domain_index" → cluster index
  // Provenance outranks everything: a cluster the USER built always beats one the app
  // made by itself. Auto clusters routinely blanket every helix, so otherwise an
  // imported design's "Scaffold Cluster"/"Geometry Cluster" could win the colour on a
  // nucleotide the user had deliberately clustered.
  const auto = clusters.map(isAutoCluster)
  /** Manual beats auto; then an explicit colour beats the auto palette; then later wins. */
  const better = (cand, held) => {
    if (held === undefined) return true
    if (auto[cand] !== auto[held]) return !auto[cand]
    if (explicit[cand] !== explicit[held]) return explicit[cand]
    return true                                   // same rank → later entry wins
  }

  const strands = design?.strands ?? []
  // Bucket strand domains by helix once, so the per-helix coverage check below is
  // cheap when a cluster lists hundreds of domain_ids.
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

  // Per-cluster coverage, kept so the extension pass below can re-use it.
  const ownedHelices = clusters.map(() => new Set())
  const ownedStrands = clusters.map(() => new Set())

  for (let i = 0; i < clusters.length; i++) {
    const c = clusters[i]
    if (c.domain_ids?.length) {
      const keys = new Set()
      for (const dr of c.domain_ids) {
        const k = `${dr.strand_id}:${dr.domain_index}`
        keys.add(k)
        ownedStrands[i].add(dr.strand_id)
        if (better(i, domainWin.get(k))) domainWin.set(k, i)
      }
      // Same full-coverage rule as buildClusterLookup: the cluster owns a helix
      // only when EVERY strand domain on it is in keys; partial coverage = bridge.
      for (const hid of (c.helix_ids ?? [])) {
        const arr = domainsByHelix.get(hid) ?? []
        let allCovered = true
        for (const d of arr) {
          if (!keys.has(d.key)) { allCovered = false; break }
        }
        if (allCovered) {
          ownedHelices[i].add(hid)
          if (better(i, helixWin.get(hid))) helixWin.set(hid, i)
        }
      }
    } else {
      for (const hid of (c.helix_ids ?? [])) {
        ownedHelices[i].add(hid)
        if (better(i, helixWin.get(hid))) helixWin.set(hid, i)
      }
    }
  }

  // 5′/3′ extension beads. They sit on SYNTHETIC helices named '__ext_<id>' that no
  // cluster lists, and their domain_index is a sentinel (-1 for 5′, len(domains) for
  // 3′ — design_geometry.py), so neither of the two tiers above can ever resolve
  // them: an extension rendered at its strand colour while the helix it grows out of
  // took the cluster colour. Register the synthetic helix id explicitly, using the
  // same rule clusterNucKeys uses for the opacity side, so colour and fade agree:
  // the extension follows its host strand when a cluster owns that strand by domain,
  // otherwise the cluster owning its terminal domain's helix.
  const strandById = new Map(strands.map(s => [s.id, s]))
  for (const ext of (design?.extensions ?? [])) {
    const strand = strandById.get(ext.strand_id)
    const termDom = strand && (ext.end === 'five_prime'
      ? strand.domains?.[0]
      : strand.domains?.[strand.domains.length - 1])
    const key = `__ext_${ext.id}`
    for (let i = 0; i < clusters.length; i++) {
      const covered = ownedStrands[i].has(ext.strand_id) ||
        (termDom && ownedHelices[i].has(termDom.helix_id))
      if (covered && better(i, helixWin.get(key))) helixWin.set(key, i)
    }
  }

  return (nuc) => {
    if (nuc?.strand_id != null && nuc?.domain_index != null) {
      const k = `${nuc.strand_id}:${nuc.domain_index}`
      if (domainWin.has(k)) return colorOf[domainWin.get(k)]
    }
    const hi = helixWin.get(nuc?.helix_id)
    return hi === undefined ? undefined : colorOf[hi]
  }
}

// Per-design pinned staple colours: designId → Map(strandId → hex). A staple
// with no explicit colour gets a palette slot the FIRST time it is seen and
// keeps it for the life of the design (mirrors the 2D editor's
// pathview/palette.js ensureStapleColors). Without this the palette slot was
// re-derived from the strand's *array position* on every rebuild, so any edit
// that reshuffles design.strands — a scaffold nick/crossover, a forced-ligation
// delete (splits a strand → appends fragments at the end) — shifted every later
// staple's index and silently recoloured untouched staples. Keying on strand.id
// pins each colour so only strands an op actually creates change colour. Keyed
// by design.id (stable across mutations) so multiple assembly-part designs each
// keep their own pins. First-encounter slot is still the array index, so a fresh
// design shows the exact same colours on load as before.
const _pinnedByDesign = new Map()   // designId → Map(strandId → hex)

export function buildStapleColorMap(geometry, design) {
  const strands    = design?.strands   ?? []
  const crossovers = design?.crossovers ?? []

  const designId = design?.id ?? '__anon__'
  let pinned = _pinnedByDesign.get(designId)
  if (!pinned) { pinned = new Map(); _pinnedByDesign.set(designId, pinned) }

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

  const map = new Map()   // strand_id → hex color (for strands present in geometry)
  for (const nuc of geometry) {
    if (!nuc.strand_id || nuc.strand_type === 'scaffold' || map.has(nuc.strand_id)) continue
    let color = pinned.get(nuc.strand_id)
    if (color === undefined) {
      const si         = strandIdxOf.get(nuc.strand_id) ?? -1
      const paletteIdx = si >= 0 ? find(si) : pinned.size
      color = STAPLE_PALETTE[paletteIdx % STAPLE_PALETTE.length]
      pinned.set(nuc.strand_id, color)
    }
    map.set(nuc.strand_id, color)
  }
  return map
}

/** Test/lifecycle hook: drop pinned staple colours (all designs, or one). The
 *  main app never needs this — pins are keyed by design.id and simply go unused
 *  when a design is replaced — but tests assert first-encounter behaviour. */
export function _resetStapleColorPins(designId) {
  if (designId === undefined) _pinnedByDesign.clear()
  else _pinnedByDesign.delete(designId)
}

export function nucColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_backbone
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  if (nuc.strand_type === 'oh_binder') return C.oh_binder
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
export function nucSlabColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_slab
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  if (nuc.strand_type === 'oh_binder') return C.oh_binder
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
export function nucArrowColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_arrow
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  if (nuc.strand_type === 'oh_binder') return C.oh_binder
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
