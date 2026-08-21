/** Paired, anti-gaming microbenchmarks for responsiveness campaign batch five. */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { performance } from 'node:perf_hooks'

const RUNS = Math.max(7, Number(process.env.NADOC_PERF_RUNS ?? 15))
const summarize = raw => {
  const sorted = [...raw].sort((a, b) => a - b)
  const at = p => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))]
  return { n: raw.length, medianMs: at(.5), p95Ms: at(.95), minMs: sorted[0],
    maxMs: sorted.at(-1), meanMs: raw.reduce((a, b) => a + b, 0) / raw.length }
}
const hashInts = values => {
  let hash = 0x811c9dc5
  for (const value of values) {
    if (typeof value === 'string') {
      for (let i = 0; i < value.length; i++) {
        const code = value.charCodeAt(i)
        hash ^= code & 255; hash = Math.imul(hash, 0x01000193)
        hash ^= code >>> 8; hash = Math.imul(hash, 0x01000193)
      }
      continue
    }
    let n = Number(value) | 0
    for (let i = 0; i < 4; i++) { hash ^= n & 255; hash = Math.imul(hash, 0x01000193); n >>= 8 }
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}
function measure(fn) {
  fn()
  const raw = [], checksums = []
  for (let i = 0; i < RUNS; i++) {
    const started = performance.now()
    checksums.push(fn())
    raw.push(performance.now() - started)
  }
  if (!checksums.every(value => value === checksums[0])) throw new Error('unstable timed checksum')
  return { summary: summarize(raw), checksum: checksums[0] }
}
function auditedPair({ beforeBuild, afterBuild, runBefore, runAfter, queryFingerprint, cardinality }) {
  const beforeState = beforeBuild(), afterState = afterBuild()
  const beforeResults = runBefore(beforeState, true), afterResults = runAfter(afterState, true)
  const beforeFingerprint = hashInts(beforeResults)
  const afterFingerprint = hashInts(afterResults)
  if (beforeFingerprint !== afterFingerprint || beforeResults.length !== afterResults.length) {
    throw new Error(`paired result mismatch: ${beforeFingerprint} != ${afterFingerprint}`)
  }
  const beforeWork = runBefore(beforeState, false, true)
  const afterWork = runAfter(afterState, false, true)
  const before = measure(() => runBefore(beforeState, false))
  const after = measure(() => runAfter(afterState, false))
  const beforeCold = measure(() => runBefore(beforeBuild(), false))
  const afterCold = measure(() => runAfter(afterBuild(), false))
  return {
    audit: {
      identicalQueryFingerprint: queryFingerprint,
      identicalResultFingerprint: beforeFingerprint,
      resultCount: beforeResults.length,
      independentResultComparison: true,
      coldIncludesIndexConstruction: true,
      candidateVisits: { before: beforeWork.visits, after: afterWork.visits },
      indexCardinality: cardinality(afterState),
    },
    steady: { before, after },
    coldTotal: { before: beforeCold, after: afterCold },
  }
}

const direction = n => n & 1 ? 'FORWARD' : 'REVERSE'
const helixCount = 240, strandCount = 6_000, domainsPerStrand = 4
const rows = Array.from({ length: helixCount }, (_, i) => ({
  id: i, lo: i * 48, hi: i * 48 + 40, fwdY: i * 48 + 8, revY: i * 48 + 24,
}))
const strands = Array.from({ length: strandCount }, (_, si) => ({
  id: si,
  domains: Array.from({ length: domainsPerStrand }, (_, di) => {
    const lo = ((si * 17 + di * 53) % 4_800) - 200
    return { id: si * domainsPerStrand + di, strandId: si,
      helix: (si + di * 17) % helixCount, direction: direction(si + di), lo, hi: lo + 18 + (si % 17) }
  }),
}))
const domains = strands.flatMap(strand => strand.domains)
const trackKey = (helix, dir) => `${helix}:${dir}`
const tracks = new Map()
for (let order = 0; order < domains.length; order++) {
  const entry = { ...domains[order], order }
  const key = trackKey(entry.helix, entry.direction)
  let bucket = tracks.get(key)
  if (!bucket) tracks.set(key, bucket = [])
  bucket.push(entry)
}
const buildTrackSearch = () => {
  const search = new Map()
  for (const [key, original] of tracks) {
    const entries = [...original].sort((a, b) => a.lo - b.lo || a.order - b.order)
    const prefixMaxHi = []; let maxHi = -Infinity
    for (const entry of entries) { maxHi = Math.max(maxHi, entry.hi); prefixMaxHi.push(maxHi) }
    search.set(key, { entries, prefixMaxHi })
  }
  return search
}
const firstAt = (search, key, bp, work) => {
  const { entries, prefixMaxHi } = search.get(key) ?? { entries: [], prefixMaxHi: [] }
  let lo = 0, hi = entries.length - 1, right = -1
  while (lo <= hi) { work.visits++; const mid = (lo + hi) >> 1
    if (entries[mid].lo <= bp) { right = mid; lo = mid + 1 } else hi = mid - 1 }
  let best = null
  for (let i = right; i >= 0 && prefixMaxHi[i] >= bp; i--) { work.visits++; const e = entries[i]
    if (e.hi >= bp && (!best || e.order < best.order)) best = e }
  return best
}

// 41: row-band lookup for pointer helix/track resolution.
const rowQueries = Array.from({ length: 30_000 }, (_, i) => (i * 7919 % (helixCount * 48 + 100)) - 50)
const runRowLegacy = (_state, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const y of rowQueries) { let found = -1
    for (const row of rows) { work.visits++; if (row.lo <= y && y <= row.hi) { found = row.id; break } }
    if (results) out.push(found); checksum = (checksum + found * 31) | 0 }
  return countOnly ? work : results ? out : checksum
}
const runRowIndexed = (bands, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const y of rowQueries) { let lo = 0, hi = bands.length - 1, found = bands.length
    while (lo <= hi) { work.visits++; const mid = (lo + hi) >> 1
      if (bands[mid].hi >= y) { found = mid; hi = mid - 1 } else lo = mid + 1 }
    const id = bands[found]?.lo <= y ? bands[found].id : -1
    if (results) out.push(id); checksum = (checksum + id * 31) | 0 }
  return countOnly ? work : results ? out : checksum
}

// 42: sorted/prefix-max interval range lookup for lasso windows.
const intervalQueries = Array.from({ length: 12_000 }, (_, i) => {
  const entry = domains[(i * 3571) % domains.length]
  const left = entry.lo + i % 5
  return [trackKey(entry.helix, entry.direction), left, left + 20]
})
const runIntervalLegacy = (_state, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const [key, left, right] of intervalQueries) { let hash = 0
    for (const entry of tracks.get(key) ?? []) { work.visits++
      if (entry.hi + 1 > left && entry.lo < right) hash = (hash + entry.id * 17) | 0 }
    if (results) out.push(hash); checksum ^= hash }
  return countOnly ? work : results ? out : checksum
}
const runIntervalIndexed = (search, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const [key, left, right] of intervalQueries) { let hash = 0
    for (const entry of overlapTrack(search, key, left, right, work)) hash = (hash + entry.id * 17) | 0
    if (results) out.push(hash); checksum ^= hash }
  return countOnly ? work : results ? out : checksum
}

// 43: viewport lasso uses row bands + interval candidates, not every domain.
const lassoQueries = Array.from({ length: 350 }, (_, i) => ({
  y0: (i * 31 % helixCount) * 48, y1: (i * 31 % helixCount) * 48 + 70,
  x0: (i * 83 % 4_000) - 150, x1: (i * 83 % 4_000) + 80,
}))
const lassoHit = (entry, q) => {
  const row = rows[entry.helix]
  const y = entry.direction === 'FORWARD' ? row.fwdY : row.revY
  return y + 8 > q.y0 && y - 8 < q.y1 && entry.hi + 1 > q.x0 && entry.lo < q.x1
}
const runLassoLegacy = (_state, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const q of lassoQueries) { let hash = 0
    for (const entry of domains) { work.visits++; if (lassoHit(entry, q)) hash = (hash + entry.id * 17) | 0 }
    if (results) out.push(hash); checksum ^= hash }
  return countOnly ? work : results ? out : checksum
}
const overlapTrack = (search, key, left, right, work) => {
  const { entries, prefixMaxHi } = search.get(key) ?? { entries: [], prefixMaxHi: [] }
  let lo = 0, hi = entries.length - 1, last = -1
  while (lo <= hi) { work.visits++; const mid = (lo + hi) >> 1
    if (entries[mid].lo < right) { last = mid; lo = mid + 1 } else hi = mid - 1 }
  const hits = []
  for (let i = last; i >= 0 && prefixMaxHi[i] + 1 > left; i--) { work.visits++
    if (entries[i].hi + 1 > left) hits.push(entries[i]) }
  return hits
}
const runLassoIndexed = (state, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const q of lassoQueries) { let hash = 0, lo = 0, hi = state.rows.length - 1, first = state.rows.length
    while (lo <= hi) { work.visits++; const mid = (lo + hi) >> 1
      if (state.rows[mid].hi > q.y0) { first = mid; hi = mid - 1 } else lo = mid + 1 }
    for (let ri = first; ri < state.rows.length && state.rows[ri].lo < q.y1; ri++) {
      work.visits++; const row = state.rows[ri]
      for (const dir of ['FORWARD', 'REVERSE']) for (const entry of overlapTrack(
        state.search, trackKey(row.id, dir), q.x0, q.x1, work)) {
        if (lassoHit(entry, q)) hash = (hash + entry.id * 17) | 0
      }
    }
    if (results) out.push(hash); checksum ^= hash
  }
  return countOnly ? work : results ? out : checksum
}

// 44/45: one shared descriptor/bin index for forced-ligation/xover point and lasso hits.
const arcs = Array.from({ length: 12_000 }, (_, id) => {
  const x = (id * 37) % 5_000, y = (id * 71) % (helixCount * 48)
  return { id, x0: x, x1: x + 16 + id % 90, y0: y, y1: y + 10 + id % 80, order: id }
})
const ARC_BUCKET = 64
const buildArcBins = () => { const bins = new Map()
  for (const arc of arcs) { const first = Math.floor((Math.min(arc.x0, arc.x1) - 4) / ARC_BUCKET)
    const last = Math.floor((Math.max(arc.x0, arc.x1) + 4) / ARC_BUCKET)
    for (let b = first; b <= last; b++) { let bucket = bins.get(b); if (!bucket) bins.set(b, bucket = []); bucket.push(arc) } }
  return bins
}
const arcPointQueries = Array.from({ length: 2_000 }, (_, i) => { const a = arcs[(i * 3571) % arcs.length]
  return { x: (a.x0 + a.x1) / 2, y: (a.y0 + a.y1) / 2 } })
const pointDist = (arc, q) => { const dx = arc.x1 - arc.x0, dy = arc.y1 - arc.y0
  const t = Math.max(0, Math.min(1, ((q.x - arc.x0) * dx + (q.y - arc.y0) * dy) / (dx * dx + dy * dy)))
  return (q.x - arc.x0 - t * dx) ** 2 + (q.y - arc.y0 - t * dy) ** 2 }
const runArcPoint = candidates => (state, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const q of arcPointQueries) { let best = null, dist = 16
    for (const arc of candidates(state, q)) { work.visits++; const d = pointDist(arc, q)
      if (d < dist || (d === dist && arc.order < best?.order)) { best = arc; dist = d } }
    const id = best?.id ?? -1; if (results) out.push(id); checksum = (checksum + id) | 0 }
  return countOnly ? work : results ? out : checksum
}
const arcLassoQueries = Array.from({ length: 500 }, (_, i) => ({ x0: i * 97 % 4_800, x1: i * 97 % 4_800 + 120,
  y0: i * 193 % (helixCount * 48), y1: i * 193 % (helixCount * 48) + 100 }))
const runArcLasso = candidates => (state, results, countOnly) => {
  const out = [], work = { visits: 0 }; let checksum = 0
  for (const q of arcLassoQueries) { const seen = new Set(); let hash = 0
    for (const arc of candidates(state, q)) { if (seen.has(arc.id)) continue; seen.add(arc.id); work.visits++
      const minX = Math.min(arc.x0, arc.x1), maxX = Math.max(arc.x0, arc.x1)
      const minY = Math.min(arc.y0, arc.y1), maxY = Math.max(arc.y0, arc.y1)
      if (maxX > q.x0 && minX < q.x1 && maxY > q.y0 && minY < q.y1) hash = (hash + arc.id * 13) | 0 }
    if (results) out.push(hash); checksum ^= hash
  }
  return countOnly ? work : results ? out : checksum
}
const arcPointBefore = runArcPoint(() => arcs)
const arcPointAfter = runArcPoint((bins, q) => bins.get(Math.floor(q.x / ARC_BUCKET)) ?? [])
const arcLassoBefore = runArcLasso(() => arcs)
const arcLassoAfter = runArcLasso((bins, q) => { const out = []
  for (let b = Math.floor(q.x0 / ARC_BUCKET); b <= Math.floor(q.x1 / ARC_BUCKET); b++) out.push(...(bins.get(b) ?? []))
  return out })

// 46: selected crossover keys resolve directly to crossover records.
const xovers = Array.from({ length: 16_000 }, (_, id) => ({ id, key: `xo:${id % 14_000}` }))
const selectedXoverKeys = Array.from({ length: 900 }, (_, i) => `xo:${i * 7919 % 14_000}`)
const buildXoverMap = () => { const map = new Map(); for (const xo of xovers) {
  let bucket = map.get(xo.key); if (!bucket) map.set(xo.key, bucket = []); bucket.push(xo) } return map }
const runXoverLegacy = (_state, results, countOnly) => { const out = [], work = { visits: 0 }; let checksum = 0
  for (const key of selectedXoverKeys) { let hash = 0; for (const xo of xovers) { work.visits++; if (xo.key === key) hash += xo.id }
    if (results) out.push(hash); checksum = (checksum + hash) | 0 }
  return countOnly ? work : results ? out : checksum }
const runXoverIndexed = (map, results, countOnly) => { const out = [], work = { visits: 0 }; let checksum = 0
  for (const key of selectedXoverKeys) { let hash = 0; for (const xo of map.get(key) ?? []) { work.visits++; hash += xo.id }
    if (results) out.push(hash); checksum = (checksum + hash) | 0 }
  return countOnly ? work : results ? out : checksum }

// 47: nick point, domain-owner, and terminal ligation lookups share indexes.
const nickQueries = Array.from({ length: 4_000 }, (_, i) => { const d = domains[(i * 3571) % domains.length]
  return { domain: d, key: trackKey(d.helix, d.direction), bp: d.lo + i % (d.hi - d.lo + 1) } })
const buildNickState = () => { const search = buildTrackSearch(), byDomain = new Map(), terminals = new Map()
  for (const strand of strands) for (let di = 0; di < strand.domains.length; di++) byDomain.set(strand.domains[di].id, [strand.id, di])
  for (const strand of strands) { const first = strand.domains[0], last = strand.domains.at(-1)
    for (const [d, end] of [[first, d => d.lo], [last, d => d.hi]]) { const key = trackKey(d.helix, d.direction)
      let bucket = terminals.get(key); if (!bucket) terminals.set(key, bucket = []); bucket.push(end(d)) } }
  return { search, byDomain, terminals }
}
const runNickLegacy = (_state, results, countOnly) => { const out = [], work = { visits: 0 }; let checksum = 0
  for (const q of nickQueries) { let covering = null, owner = -1, terminalCount = 0
    for (const strand of strands) { for (let di = 0; di < strand.domains.length; di++) { work.visits++; const d = strand.domains[di]
      if (!covering && trackKey(d.helix, d.direction) === q.key && d.lo <= q.bp && q.bp <= d.hi) covering = d
      if (d.id === q.domain.id) owner = strand.id * 4 + di }
      const first = strand.domains[0], last = strand.domains.at(-1)
      work.visits += 2
      if (trackKey(first.helix, first.direction) === q.key && first.lo === q.bp) terminalCount++
      if (trackKey(last.helix, last.direction) === q.key && last.hi === q.bp) terminalCount++ }
    const value = (covering?.id ?? -1) + owner * 3 + terminalCount * 17
    if (results) out.push(value); checksum = (checksum + value) | 0 }
  return countOnly ? work : results ? out : checksum }
const runNickIndexed = (state, results, countOnly) => { const out = [], work = { visits: 0 }; let checksum = 0
  for (const q of nickQueries) { const covering = firstAt(state.search, q.key, q.bp, work)
    work.visits++; const [si, di] = state.byDomain.get(q.domain.id) ?? [-1, 0]
    let terminalCount = 0; for (const bp of state.terminals.get(q.key) ?? []) { work.visits++; if (bp === q.bp) terminalCount++ }
    const value = (covering?.id ?? -1) + (si * 4 + di) * 3 + terminalCount * 17
    if (results) out.push(value); checksum = (checksum + value) | 0 }
  return countOnly ? work : results ? out : checksum }

// 48: cylinder visibility reads a domain bucket rather than filtering all geometry.
const assignedGeometry = Array.from({ length: 60_000 }, (_, id) => ({ id,
  key: `${id % 6_000}:${id % domainsPerStrand}`, hidden: id % 19 === 0 }))
const cylinderQueries = Array.from({ length: 600 }, (_, i) => `${i * 3571 % 6_000}:${i % domainsPerStrand}`)
const buildAssignedMap = () => { const map = new Map(); for (const nuc of assignedGeometry) {
  let bucket = map.get(nuc.key); if (!bucket) map.set(nuc.key, bucket = []); bucket.push(nuc) } return map }
const runVisibility = candidates => (state, results, countOnly) => { const out = [], work = { visits: 0 }; let checksum = 0
  for (const key of cylinderQueries) { const nucs = candidates(state, key, work); let allHidden = nucs.length > 0
    for (const nuc of nucs) { work.visits++; if (!nuc.hidden) { allHidden = false; break } }
    const value = allHidden ? 0 : 1; if (results) out.push(value); checksum += value }
  return countOnly ? work : results ? out : checksum }
const visibilityBefore = runVisibility((_state, key, work) => { const out = []
  for (const nuc of assignedGeometry) { work.visits++; if (nuc.key === key) out.push(nuc) } return out })
const visibilityAfter = runVisibility((map, key, work) => { work.visits++; return map.get(key) ?? [] })

// 49: glow resolves selected refs directly to cylinder entries.
const glowEntries = Array.from({ length: 24_000 }, (_, id) => ({ id, key: `${id % 6_000}:${id % 4}`,
  kind: id % 5 ? 0 : id % 2 ? 1 : 2 }))
const glowRefs = Array.from({ length: 700 }, (_, i) => `${i * 3571 % 6_000}:${i % 4}`)
const buildGlowMap = () => { const map = new Map(); for (const entry of glowEntries) {
  let bucket = map.get(entry.key); if (!bucket) map.set(entry.key, bucket = []); bucket.push(entry) } return map }
const glowResult = entries => { const sets = [new Set(), new Set(), new Set()]
  for (const entry of entries) sets[entry.kind].add(entry.id)
  return sets.map(set => [...set].reduce((sum, id) => (sum + id * 31) | 0, set.size)) }
const runGlowLegacy = (_state, results, countOnly) => { const work = { visits: 0 }, selected = new Set(glowRefs), matches = []
  for (const entry of glowEntries) { work.visits++; if (selected.has(entry.key)) matches.push(entry) }
  const out = glowResult(matches); return countOnly ? work : results ? out : out.reduce((a, b) => a ^ b, 0) }
const runGlowIndexed = (map, results, countOnly) => { const work = { visits: 0 }, matches = []
  for (const key of glowRefs) for (const entry of map.get(key) ?? []) { work.visits++; matches.push(entry) }
  const out = glowResult(matches); return countOnly ? work : results ? out : out.reduce((a, b) => a ^ b, 0) }

const fingerprint = values => hashInts(values)
const report = {
  environment: { node: process.version, runs: RUNS },
  fixture: { helices: helixCount, strands: strandCount, domains: domains.length,
    arcs: arcs.length, xovers: xovers.length, assignedNucleotides: assignedGeometry.length,
    cylinderEntries: glowEntries.length },
  antiGamingProtocol: {
    pairedFunctionsConsumeSameFixtureObjects: true,
    resultVectorsComparedOutsideTimedRegions: true,
    queryFingerprintsRecorded: true,
    candidateVisitsRecorded: true,
    coldTotalIncludesIndexConstructionAndFirstQueryBatch: true,
    steadyStateUsesPrebuiltProductionEquivalentIndexes: true,
  },
  rowBandLookup: auditedPair({ beforeBuild: () => null, afterBuild: () => [...rows],
    runBefore: runRowLegacy, runAfter: runRowIndexed, queryFingerprint: fingerprint(rowQueries.map(Math.floor)),
    cardinality: state => state.length }),
  trackIntervalLookup: auditedPair({ beforeBuild: () => null, afterBuild: buildTrackSearch,
    runBefore: runIntervalLegacy, runAfter: runIntervalIndexed,
    queryFingerprint: fingerprint(intervalQueries.flatMap(([key, left, right]) => [key, left, right])), cardinality: state => state.size }),
  lassoCandidateIndex: auditedPair({ beforeBuild: () => null, afterBuild: () => ({ rows: [...rows], search: buildTrackSearch() }),
    runBefore: runLassoLegacy, runAfter: runLassoIndexed,
    queryFingerprint: fingerprint(lassoQueries.flatMap(q => [q.x0, q.x1, q.y0, q.y1])),
    cardinality: state => state.rows.length + state.search.size }),
  forcedLigationArcHitBins: auditedPair({ beforeBuild: () => null, afterBuild: buildArcBins,
    runBefore: arcPointBefore, runAfter: arcPointAfter,
    queryFingerprint: fingerprint(arcPointQueries.flatMap(q => [q.x, q.y])), cardinality: state => state.size }),
  arcLassoDescriptorReuse: auditedPair({ beforeBuild: () => null, afterBuild: buildArcBins,
    runBefore: arcLassoBefore, runAfter: arcLassoAfter,
    queryFingerprint: fingerprint(arcLassoQueries.flatMap(q => [q.x0, q.x1, q.y0, q.y1])), cardinality: state => state.size }),
  selectedCrossoverRecordMap: auditedPair({ beforeBuild: () => null, afterBuild: buildXoverMap,
    runBefore: runXoverLegacy, runAfter: runXoverIndexed,
    queryFingerprint: fingerprint(selectedXoverKeys.map(key => Number(key.slice(3)))), cardinality: state => state.size }),
  nickToolIndexes: auditedPair({ beforeBuild: () => null, afterBuild: buildNickState,
    runBefore: runNickLegacy, runAfter: runNickIndexed,
    queryFingerprint: fingerprint(nickQueries.flatMap(q => [q.domain.id, q.bp])),
    cardinality: state => state.search.size + state.byDomain.size + state.terminals.size }),
  cylinderVisibilityDomainMap: auditedPair({ beforeBuild: () => null, afterBuild: buildAssignedMap,
    runBefore: visibilityBefore, runAfter: visibilityAfter,
    queryFingerprint: fingerprint(cylinderQueries), cardinality: state => state.size }),
  selectedCylinderGlowEntries: auditedPair({ beforeBuild: () => null, afterBuild: buildGlowMap,
    runBefore: runGlowLegacy, runAfter: runGlowIndexed,
    queryFingerprint: fingerprint(glowRefs), cardinality: state => state.size }),
}

console.log(JSON.stringify(report, null, 2))
if (process.env.NADOC_PERF_OUTPUT) {
  const output = resolve(process.cwd(), process.env.NADOC_PERF_OUTPUT)
  mkdirSync(dirname(output), { recursive: true })
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
}
