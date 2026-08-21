/** Paired legacy/current microbenchmarks for responsiveness campaign batch three. */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { performance } from 'node:perf_hooks'

import {
  domainEndKey, domainLineKey, parseEndKey, parseLineKey,
} from '../src/cadnano-editor/element_keys.js'
import { buildVisibilityGeometryIndex } from '../src/scene/visibility_controller.js'

const RUNS = Math.max(5, Number(process.env.NADOC_PERF_RUNS ?? 15))
const summarize = raw => {
  const sorted = [...raw].sort((a, b) => a - b)
  const at = p => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))]
  return { n: raw.length, medianMs: at(.5), p95Ms: at(.95), minMs: sorted[0],
    maxMs: sorted.at(-1), meanMs: raw.reduce((a, b) => a + b, 0) / raw.length }
}
function measure(fn) {
  fn()
  const raw = []
  let checksum = 0
  for (let i = 0; i < RUNS; i++) {
    const start = performance.now()
    checksum ^= fn()
    raw.push(performance.now() - start)
  }
  return { raw, summary: summarize(raw), checksum }
}
const paired = (before, after) => {
  const b = before(), a = after()
  if (b !== a) throw new Error(`paired checksum mismatch: ${b} !== ${a}`)
  return { before: measure(before), after: measure(after) }
}

const DIRECTION = index => index % 2 ? 'FORWARD' : 'REVERSE'
const trackKey = (helix, direction) => `${helix}_${direction}`
const transitionKey = (a, b) =>
  `${a.helix_id}\0${a.end_bp}\0${a.direction}\0${b.helix_id}\0${b.start_bp}\0${b.direction}`

// 21: coaxial/forced-ligation transition preparation.
const transitionCount = 12_000
const transitions = Array.from({ length: transitionCount }, (_, index) => [{
  helix_id: `h${index % 240}`, end_bp: index, direction: DIRECTION(index),
}, {
  helix_id: `h${(index + 1) % 240}`, start_bp: index + 1, direction: DIRECTION(index + 1),
}])
const forcedLigations = Array.from({ length: 1_200 }, (_, n) => {
  const [a, b] = transitions[n * 10]
  return { three_prime_helix_id: a.helix_id, three_prime_bp: a.end_bp,
    three_prime_direction: a.direction, five_prime_helix_id: b.helix_id,
    five_prime_bp: b.start_bp, five_prime_direction: b.direction }
})
const forcedKeys = new Set(forcedLigations.map(fl =>
  `${fl.three_prime_helix_id}\0${fl.three_prime_bp}\0${fl.three_prime_direction}\0` +
  `${fl.five_prime_helix_id}\0${fl.five_prime_bp}\0${fl.five_prime_direction}`))
const legacyCoax = () => {
  let count = 0
  for (const [a, b] of transitions) {
    const forced = forcedLigations.some(fl =>
      fl.three_prime_helix_id === a.helix_id && fl.three_prime_bp === a.end_bp &&
      fl.three_prime_direction === a.direction && fl.five_prime_helix_id === b.helix_id &&
      fl.five_prime_bp === b.start_bp && fl.five_prime_direction === b.direction)
    if (!forced) count++
  }
  return count
}
const indexedCoax = () => {
  let count = 0
  for (const [a, b] of transitions) if (!forcedKeys.has(transitionKey(a, b))) count++
  return count
}

// Shared large design for extension, drag, heatmap, lasso, and helix lookup kernels.
const strandCount = 6_000
const strands = Array.from({ length: strandCount }, (_, index) => ({
  id: `strand_${index}`, strand_type: index % 11 === 0 ? 'scaffold' : 'staple',
  domains: Array.from({ length: 4 }, (_, domainIndex) => ({
    helix_id: `h${(index + domainIndex) % 240}`,
    start_bp: index * 6 + domainIndex * 40,
    end_bp: index * 6 + domainIndex * 40 + 31,
    direction: DIRECTION(index + domainIndex),
  })),
}))
const extensions = Array.from({ length: 3_000 }, (_, index) => ({
  id: `ext_${index}`, strand_id: `strand_${index * 2}`, end: index % 2 ? 'five_prime' : 'three_prime',
}))
const strandById = new Map(strands.map((strand, index) => [strand.id, { strand, index }]))
const cachedExtensionHosts = extensions.flatMap(ext => {
  const host = strandById.get(ext.strand_id)
  return host ? [{ ext, ...host }] : []
})
const extensionChecksum = entries => {
  let checksum = entries.length
  for (const entry of entries) checksum = (checksum + entry.index + entry.strand.id.length) | 0
  return checksum
}
const legacyExtensions = () => {
  const hosts = new Map(strands.map((strand, index) => [strand.id, { strand, index }]))
  return extensionChecksum(extensions.flatMap(ext => {
    const host = hosts.get(ext.strand_id)
    return host ? [{ ext, ...host }] : []
  }))
}
const indexedExtensions = () => extensionChecksum(cachedExtensionHosts)

// 23: selected end/domain key resolution.
const endEntryByKey = new Map(), lineEntryByKey = new Map(), domainsByTrack = new Map()
for (let si = 0; si < strands.length; si++) {
  const strand = strands[si]
  for (let di = 0; di < strand.domains.length; di++) {
    const dom = strand.domains[di]
    const lo = Math.min(dom.start_bp, dom.end_bp), hi = Math.max(dom.start_bp, dom.end_bp)
    const entry = { strand, si, di, dom, lo, hi }
    if (!lineEntryByKey.has(domainLineKey(dom))) lineEntryByKey.set(domainLineKey(dom), entry)
    for (const end of ['5p', '3p']) {
      const key = domainEndKey(dom, end)
      if (!endEntryByKey.has(key)) endEntryByKey.set(key, entry)
    }
    const key = trackKey(dom.helix_id, dom.direction)
    let track = domainsByTrack.get(key)
    if (!track) domainsByTrack.set(key, track = [])
    track.push(entry)
  }
}
const selectedKeys = []
for (let index = 0; index < 800; index++) {
  const strand = strands[(index * 313) % strands.length]
  const dom = strand.domains[index % strand.domains.length]
  selectedKeys.push(index % 2 ? domainLineKey(dom) : domainEndKey(dom, index % 4 ? '3p' : '5p'))
}
const legacyResolveDrag = () => {
  let checksum = 0
  for (const key of selectedKeys) {
    const isLine = key.startsWith('line:')
    const parsed = isLine ? parseLineKey(key) : parseEndKey(key)
    outer: for (let si = 0; si < strands.length; si++) {
      for (let di = 0; di < strands[si].domains.length; di++) {
        const dom = strands[si].domains[di]
        const lo = Math.min(dom.start_bp, dom.end_bp), hi = Math.max(dom.start_bp, dom.end_bp)
        const matches = isLine
          ? dom.helix_id === parsed.helix_id && dom.direction === parsed.direction &&
            lo === parsed.lo && hi === parsed.hi
          : dom.helix_id === parsed.helix_id && dom.direction === parsed.direction &&
            (parsed.bp === lo || parsed.bp === hi)
        if (matches) {
          checksum = (checksum + si + di) | 0
          break outer
        }
      }
    }
  }
  return checksum
}
const indexedResolveDrag = () => {
  let checksum = 0
  for (const key of selectedKeys) {
    const entry = (key.startsWith('line:') ? lineEntryByKey : endEntryByKey).get(key)
    if (entry) checksum = (checksum + entry.si + entry.di) | 0
  }
  return checksum
}

// 24: drag blockers, indexed by helix/direction.
const xovers = Array.from({ length: 12_000 }, (_, index) => ({
  half_a: { helix_id: `h${index % 240}`, strand: DIRECTION(index), index: index * 3 },
  half_b: { helix_id: `h${(index + 1) % 240}`, strand: DIRECTION(index + 1), index: index * 3 },
}))
const xoversByTrack = new Map()
for (const xo of xovers) for (const half of [xo.half_a, xo.half_b]) {
  const key = trackKey(half.helix_id, half.strand)
  let values = xoversByTrack.get(key)
  if (!values) xoversByTrack.set(key, values = new Set())
  values.add(half.index)
}
const dragEntries = Array.from({ length: 240 }, (_, index) => {
  const indexed = domainsByTrack.get(trackKey(`h${index}`, DIRECTION(index)))?.[5]
  return { helixId: indexed.dom.helix_id, direction: indexed.dom.direction,
    domLo: indexed.lo, domHi: indexed.hi }
})
const legacyDragBlockers = () => {
  let checksum = 0
  for (const selected of dragEntries) {
    let endpoints = 0, occupied = 0
    for (const strand of strands) for (const dom of strand.domains) {
      if (dom.helix_id === selected.helixId && dom.direction === selected.direction) endpoints += 2
    }
    for (const xo of xovers) for (const half of [xo.half_a, xo.half_b]) {
      if (half.helix_id === selected.helixId && half.strand === selected.direction) occupied++
    }
    checksum = (checksum + endpoints * 3 + occupied) | 0
  }
  return checksum
}
const indexedDragBlockers = () => {
  let checksum = 0
  for (const selected of dragEntries) {
    const endpoints = (domainsByTrack.get(trackKey(selected.helixId, selected.direction))?.length ?? 0) * 2
    const occupied = xoversByTrack.get(trackKey(selected.helixId, selected.direction))?.size ?? 0
    checksum = (checksum + endpoints * 3 + occupied) | 0
  }
  return checksum
}

// 25: renderer identity/domain reference lookups.
const rendererEntries = Array.from({ length: 20_000 }, (_, index) => ({
  nuc: { index }, strandId: `strand_${index >> 2}`, domainIndex: index % 4, id: index,
}))
const rendererByNuc = new Map(rendererEntries.map(entry => [entry.nuc, entry]))
const rendererByRef = new Map(rendererEntries.map(entry => [`${entry.strandId}:${entry.domainIndex}`, entry]))
const rendererQueries = Array.from({ length: 4_000 }, (_, index) => rendererEntries[(index * 7919) % rendererEntries.length])
const legacyRendererLookup = () => {
  let checksum = 0
  for (const query of rendererQueries) {
    checksum = (checksum + rendererEntries.find(entry => entry.nuc === query.nuc).id) | 0
    checksum = (checksum + rendererEntries.find(entry =>
      entry.strandId === query.strandId && entry.domainIndex === query.domainIndex).id) | 0
  }
  return checksum
}
const indexedRendererLookup = () => {
  let checksum = 0
  for (const query of rendererQueries) {
    checksum = (checksum + rendererByNuc.get(query.nuc).id) | 0
    checksum = (checksum + rendererByRef.get(`${query.strandId}:${query.domainIndex}`).id) | 0
  }
  return checksum
}

// 26: heatmap preparation once per immutable design.
const heatmapValue = strand => strand.domains.reduce((sum, dom) => sum + Math.abs(dom.end_bp - dom.start_bp) + 1, 0)
const buildHeatmap = () => new Map(strands.flatMap((strand, index) =>
  strand.strand_type === 'scaffold' ? [] : [[index, heatmapValue(strand)]]))
const preparedHeatmap = buildHeatmap()
const heatmapChecksum = map => map.size + (map.get(1) ?? 0) + (map.get(strands.length - 1) ?? 0)
const legacyHeatmap = () => {
  let checksum = 0
  for (let redraw = 0; redraw < 100; redraw++) checksum = (checksum + heatmapChecksum(buildHeatmap())) | 0
  return checksum
}
const indexedHeatmap = () => {
  let checksum = 0
  for (let redraw = 0; redraw < 100; redraw++) checksum = (checksum + heatmapChecksum(preparedHeatmap)) | 0
  return checksum
}

// 27: repeated strand visibility queries.
const geometry = Array.from({ length: 30_000 }, (_, index) => ({
  helix_id: `h${index % 240}`, bp_index: index, direction: DIRECTION(index),
  strand_id: `strand_${index % strandCount}`, domain_index: index % 4,
}))
const visibilityIndex = buildVisibilityGeometryIndex(geometry)
const visibilityQueries = Array.from({ length: 1_000 }, (_, index) => `strand_${(index * 313) % strandCount}`)
const legacyVisibility = () => {
  let checksum = 0
  for (const strandId of visibilityQueries) checksum += geometry.filter(nuc => nuc.strand_id === strandId).length
  return checksum
}
const indexedVisibility = () => {
  let checksum = 0
  for (const strandId of visibilityQueries) checksum += visibilityIndex.baseKeysByStrand.get(strandId)?.length ?? 0
  return checksum
}

// 28: lasso candidate domain traversal.
const lasso = { helixIds: new Set(['h117', 'h118', 'h119']), lo: 12_000, hi: 13_000 }
const legacyLasso = () => {
  let checksum = 0
  for (const strand of strands) for (const dom of strand.domains) {
    if (!lasso.helixIds.has(dom.helix_id)) continue
    const lo = Math.min(dom.start_bp, dom.end_bp), hi = Math.max(dom.start_bp, dom.end_bp)
    if (hi >= lasso.lo && lo <= lasso.hi) checksum = (checksum + strand.id.length + lo) | 0
  }
  return checksum
}
const indexedLasso = () => {
  let checksum = 0
  for (const helixId of lasso.helixIds) for (const direction of ['FORWARD', 'REVERSE']) {
    for (const entry of domainsByTrack.get(trackKey(helixId, direction)) ?? []) {
      if (entry.hi >= lasso.lo && entry.lo <= lasso.hi) checksum = (checksum + entry.strand.id.length + entry.lo) | 0
    }
  }
  return checksum
}

// 29: x-bucketed crossover arc candidates.
const arcDescriptors = Array.from({ length: 12_000 }, (_, index) => ({
  id: index, xMin: index * 8 - 4, xMax: index * 8 + 4,
  yMin: (index % 240) * 12, yMax: (index % 240) * 12 + 24,
}))
const ARC_BUCKET = 64
const arcBins = new Map()
for (const arc of arcDescriptors) {
  for (let bucket = Math.floor(arc.xMin / ARC_BUCKET); bucket <= Math.floor(arc.xMax / ARC_BUCKET); bucket++) {
    let values = arcBins.get(bucket)
    if (!values) arcBins.set(bucket, values = [])
    values.push(arc)
  }
}
const arcPoints = Array.from({ length: 2_000 }, (_, index) => ({
  x: ((index * 3571) % arcDescriptors.length) * 8,
  y: (((index * 3571) % arcDescriptors.length) % 240) * 12 + 5,
}))
const arcHitChecksum = candidatesFor => {
  let checksum = 0
  for (const point of arcPoints) for (const arc of candidatesFor(point)) {
    if (point.x >= arc.xMin && point.x <= arc.xMax && point.y >= arc.yMin && point.y <= arc.yMax) checksum ^= arc.id
  }
  return checksum
}
const legacyArcHit = () => arcHitChecksum(() => arcDescriptors)
const indexedArcHit = () => arcHitChecksum(point => arcBins.get(Math.floor(point.x / ARC_BUCKET)) ?? [])

// 30: design-update helix comparison.
const helices = Array.from({ length: 8_000 }, (_, index) => ({ id: `helix_${index}`, bp_start: index % 11, length_bp: 128 }))
const nextHelices = helices.map((helix, index) => ({ ...helix, length_bp: helix.length_bp + (index % 997 === 0 ? 1 : 0) }))
const helixById = new Map(helices.map(helix => [helix.id, helix]))
const legacyHelixDiff = () => {
  let checksum = 0
  for (const helix of nextHelices) {
    const old = helices.find(candidate => candidate.id === helix.id)
    if (!old || old.length_bp !== helix.length_bp || old.bp_start !== helix.bp_start) checksum += helix.id.length
  }
  return checksum
}
const indexedHelixDiff = () => {
  let checksum = 0
  for (const helix of nextHelices) {
    const old = helixById.get(helix.id)
    if (!old || old.length_bp !== helix.length_bp || old.bp_start !== helix.bp_start) checksum += helix.id.length
  }
  return checksum
}

const report = {
  environment: { node: process.version, runs: RUNS },
  fixture: { transitions: transitionCount, forcedLigations: forcedLigations.length,
    strands: strands.length, domains: strands.length * 4, extensions: extensions.length,
    selectedDragKeys: selectedKeys.length, xovers: xovers.length,
    rendererEntries: rendererEntries.length, geometry: geometry.length,
    heatmapRedrawsPerSample: 100, arcs: arcDescriptors.length,
    arcPoints: arcPoints.length, helices: helices.length },
  coaxialForcedTransitionIndex: paired(legacyCoax, indexedCoax),
  pathviewExtensionHostCache: paired(legacyExtensions, indexedExtensions),
  dragElementResolutionIndex: paired(legacyResolveDrag, indexedResolveDrag),
  dragBlockerTrackIndex: paired(legacyDragBlockers, indexedDragBlockers),
  rendererIdentityAndDomainIndex: paired(legacyRendererLookup, indexedRendererLookup),
  heatmapDesignCache: paired(legacyHeatmap, indexedHeatmap),
  visibilityStrandGeometryIndex: paired(legacyVisibility, indexedVisibility),
  lassoTrackDomainIndex: paired(legacyLasso, indexedLasso),
  crossoverArcHitBins: paired(legacyArcHit, indexedArcHit),
  pathviewHelixUpdateMap: paired(legacyHelixDiff, indexedHelixDiff),
}

console.log(JSON.stringify(report, null, 2))
if (process.env.NADOC_PERF_OUTPUT) {
  const output = resolve(process.cwd(), process.env.NADOC_PERF_OUTPUT)
  mkdirSync(dirname(output), { recursive: true })
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
}
