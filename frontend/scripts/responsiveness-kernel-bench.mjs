/** Reproducible microbenchmarks for pure frontend responsiveness kernels. */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { performance } from 'node:perf_hooks'

import { resolveAtomColor } from '../src/scene/atomistic_renderer/color_resolver.js'
import { C_HIGHLIGHT } from '../src/scene/atomistic_renderer/atom_palette.js'
import {
  clusterAlphaKeys,
  clusterIdForNucleotide,
  clusterMemberFilter,
  clusterNucKeysFor,
} from '../src/scene/cluster_entries.js'

const RUNS = Math.max(5, Number(process.env.NADOC_PERF_RUNS ?? 15))

function summarize(raw) {
  const sorted = [...raw].sort((a, b) => a - b)
  const at = p => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))]
  return {
    n: raw.length,
    medianMs: at(0.5),
    p95Ms: at(0.95),
    minMs: sorted[0],
    maxMs: sorted.at(-1),
    meanMs: raw.reduce((a, b) => a + b, 0) / raw.length,
  }
}

function measure(fn) {
  fn() // warm-up/JIT
  const raw = []
  let checksum = 0
  for (let i = 0; i < RUNS; i++) {
    const t0 = performance.now()
    checksum ^= Number(fn()) | 0
    raw.push(performance.now() - t0)
  }
  return { raw, summary: summarize(raw), checksum }
}

function legacyResolveAtomColor(ctx, atom, selection, hasSelection) {
  const normal = resolveAtomColor(ctx, atom, null, false)
  if (!hasSelection) return normal
  if (selection?.extensionIds?.includes(atom.extension_id)) return C_HIGHLIGHT
  if (selection?.helixIds?.includes(atom.helix_id)) return C_HIGHLIGHT
  if (selection?.strandIds?.includes(atom.strand_id)) return C_HIGHLIGHT
  if (selection?.domains?.some(domain =>
    atom.strand_id === domain.strandId && atom.helix_id === domain.helixId &&
    atom.direction === domain.direction && atom.bp_index >= domain.lo && atom.bp_index <= domain.hi)) {
    return C_HIGHLIGHT
  }
  if (selection?.bases?.some(base =>
    atom.helix_id === base.helix_id && atom.bp_index === base.bp_index &&
    atom.direction === base.direction)) return C_HIGHLIGHT
  return normal
}

function atomColorScenario(resolver) {
  const atoms = Array.from({ length: 60_000 }, (_, i) => ({
    element: i % 3 ? 'C' : 'N',
    extension_id: i % 997 === 0 ? `ext${i % 700}` : null,
    helix_id: `h${i % 1600}`,
    strand_id: `s${i % 6000}`,
    direction: i % 2 ? 'FORWARD' : 'REVERSE',
    bp_index: i % 800,
  }))
  const selection = {
    extensionIds: Array.from({ length: 250 }, (_, i) => `ext${i}`),
    helixIds: Array.from({ length: 300 }, (_, i) => `h${i * 2}`),
    strandIds: Array.from({ length: 350 }, (_, i) => `s${i * 3}`),
    domains: Array.from({ length: 200 }, (_, i) => ({
      strandId: `s${i * 5}`, helixId: `h${i * 3}`,
      direction: i % 2 ? 'FORWARD' : 'REVERSE', lo: 100, hi: 500,
    })),
    bases: Array.from({ length: 200 }, (_, i) => ({
      helix_id: `h${i * 3}`, bp_index: i % 800,
      direction: i % 2 ? 'FORWARD' : 'REVERSE',
    })),
  }
  const ctx = {
    colorMode: 'strand', strandColors: new Map(), baseColors: new Map(),
    clusterColors: new Map(), scalarColors: null,
  }
  return () => {
    let checksum = 0
    for (const atom of atoms) checksum ^= resolver(ctx, atom, selection, true)
    return checksum
  }
}

function legacyClusterIdForNucleotide(nucleotide, design) {
  const clusters = design?.cluster_transforms ?? []
  if (!nucleotide || !clusters.length) return null
  let best = null
  let bestSize = Infinity
  for (const cluster of clusters) {
    if (cluster.is_default) continue
    const isMember = clusterMemberFilter(cluster, design)
    if (isMember?.(nucleotide)) {
      const size = cluster.helix_ids?.length ?? Infinity
      if (size < bestSize) { best = cluster; bestSize = size }
    }
  }
  if (best) return best.id
  const fallback = clusters.find(cluster =>
    cluster.is_default && clusterMemberFilter(cluster, design)?.(nucleotide)) ??
    clusters.find(cluster => clusterMemberFilter(cluster, design)?.(nucleotide))
  return fallback?.id ?? null
}

function legacyClusterNucKeys(cluster, design) {
  const keys = new Set()
  if (!cluster?.helix_ids?.length) return keys
  const strandIds = new Set()
  const helixIds = new Set()
  if (cluster.domain_ids?.length) {
    const strandMap = new Map((design?.strands ?? []).map(s => [s.id, s]))
    const bridgeHelixIds = new Set()
    for (const d of cluster.domain_ids) {
      const dom = strandMap.get(d.strand_id)?.domains?.[d.domain_index]
      if (dom) bridgeHelixIds.add(dom.helix_id)
      keys.add(`d:${d.strand_id}:${d.domain_index}`)
      strandIds.add(d.strand_id)
    }
    for (const hid of cluster.helix_ids) {
      if (!bridgeHelixIds.has(hid)) { keys.add(`h:${hid}`); helixIds.add(hid) }
    }
  } else {
    for (const hid of cluster.helix_ids) { keys.add(`h:${hid}`); helixIds.add(hid) }
  }
  for (const ext of design?.extensions ?? []) {
    if (strandIds.has(ext.strand_id)) {
      keys.add('h:__ext_' + ext.id)
    } else if (helixIds.size) {
      const strand = (design?.strands ?? []).find(s => s.id === ext.strand_id)
      const termDom = strand && (ext.end === 'five_prime'
        ? strand.domains[0]
        : strand.domains[strand.domains.length - 1])
      if (termDom && helixIds.has(termDom.helix_id)) keys.add('h:__ext_' + ext.id)
    }
  }
  return keys
}

function legacyClusterNucKeysFor(design, idSet) {
  const want = idSet instanceof Set ? idSet : new Set(idSet ?? [])
  const keys = new Set()
  for (const cluster of design?.cluster_transforms ?? []) {
    if (!want.has(cluster.id)) continue
    for (const key of legacyClusterNucKeys(cluster, design)) keys.add(key)
  }
  return keys
}

function legacyClusterAlphaKeys(design) {
  const out = new Map()
  for (const cluster of design?.cluster_transforms ?? []) {
    const alpha = typeof cluster.opacity === 'number' ? cluster.opacity : 1
    if (!(alpha < 1)) continue
    for (const key of legacyClusterNucKeys(cluster, design)) {
      const previous = out.get(key)
      if (previous === undefined || alpha < previous) out.set(key, Math.max(0, alpha))
    }
  }
  return out
}

function clusterScenario() {
  const strands = Array.from({ length: 1_000 }, (_, si) => ({
    id: `s${si}`,
    domains: Array.from({ length: 4 }, (_, di) => ({ helix_id: `h${(si * 4 + di) % 2_000}` })),
  }))
  const clusters = Array.from({ length: 30 }, (_, ci) => ({
    id: `c${ci}`,
    is_default: ci === 29,
    opacity: ci % 3 ? 0.65 : 1,
    helix_ids: Array.from({ length: 100 }, (_, i) => `h${(ci * 23 + i * 7) % 2_000}`),
    domain_ids: ci % 2 ? Array.from({ length: 80 }, (_, i) => ({
      strand_id: `s${(ci * 61 + i * 13) % strands.length}`, domain_index: i % 4,
    })) : [],
  }))
  const extensions = Array.from({ length: 2_000 }, (_, i) => ({
    id: `e${i}`, strand_id: `s${i % strands.length}`, end: i % 2 ? 'five_prime' : 'three_prime',
  }))
  const design = { strands, cluster_transforms: clusters, extensions }
  const nucleotides = Array.from({ length: 2_000 }, (_, i) => ({
    strand_id: `s${i % strands.length}`, domain_index: i % 4,
    helix_id: strands[i % strands.length].domains[i % 4].helix_id,
  }))
  const wanted = new Set(clusters.filter((_, i) => i % 2).map(c => c.id))
  return {
    idLookup: resolver => () => {
      let checksum = 0
      for (const nuc of nucleotides) checksum ^= (resolver(nuc, design)?.length ?? 0)
      return checksum
    },
    alphaKeys: resolver => () => resolver(design).size,
    selectedKeys: resolver => () => resolver(design, wanted).size,
  }
}

const cluster = clusterScenario()
const report = {
  environment: { node: process.version, runs: RUNS },
  atomColorSelection: {
    before: measure(atomColorScenario(legacyResolveAtomColor)),
    after: measure(atomColorScenario(resolveAtomColor)),
  },
  clusterIdLookup: {
    before: measure(cluster.idLookup(legacyClusterIdForNucleotide)),
    after: measure(cluster.idLookup(clusterIdForNucleotide)),
  },
  clusterAlphaKeys: {
    before: measure(cluster.alphaKeys(legacyClusterAlphaKeys)),
    after: measure(cluster.alphaKeys(clusterAlphaKeys)),
  },
  clusterSelectedKeys: {
    before: measure(cluster.selectedKeys(legacyClusterNucKeysFor)),
    after: measure(cluster.selectedKeys(clusterNucKeysFor)),
  },
}

console.log(JSON.stringify(report, null, 2))
if (process.env.NADOC_PERF_OUTPUT) {
  const output = resolve(process.cwd(), process.env.NADOC_PERF_OUTPUT)
  mkdirSync(dirname(output), { recursive: true })
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
}
