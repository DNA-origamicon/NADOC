/** Paired legacy/current microbenchmarks for responsiveness campaign batch four. */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { performance } from 'node:perf_hooks'

import { domainEndKey, domainLineKey } from '../src/cadnano-editor/element_keys.js'

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
    const started = performance.now()
    checksum ^= fn()
    raw.push(performance.now() - started)
  }
  return { raw, summary: summarize(raw), checksum }
}
const paired = (before, after) => {
  const b = before(), a = after()
  if (b !== a) throw new Error(`paired checksum mismatch: ${b} !== ${a}`)
  return { before: measure(before), after: measure(after) }
}

const direction = n => n % 2 ? 'FORWARD' : 'REVERSE'
const trackKey = (helix, dir) => `${helix}_${dir}`
const strandCount = 6_000
const helixCount = 240
const strands = Array.from({ length: strandCount }, (_, si) => ({
  id: `strand_${si}`,
  is_reference: si % 13 === 0,
  domains: Array.from({ length: 4 }, (_, di) => ({
    helix_id: `h${(si + di) % helixCount}`,
    start_bp: si * 6 + di * 40,
    end_bp: si * 6 + di * 40 + 31,
    direction: direction(si + di),
  })),
}))

const domainsByTrack = new Map()
const ownerByKey = new Map()
const keysByStrand = new Map()
const transitions = new Map()
const transitionKey = (a, b) =>
  `${a.helix_id}\0${a.end_bp}\0${a.direction}\0${b.helix_id}\0${b.start_bp}\0${b.direction}`
for (const strand of strands) {
  const keys = []
  for (let di = 0; di < strand.domains.length; di++) {
    const dom = strand.domains[di]
    const entry = { strand, di, dom, lo: Math.min(dom.start_bp, dom.end_bp), hi: Math.max(dom.start_bp, dom.end_bp) }
    let track = domainsByTrack.get(trackKey(dom.helix_id, dom.direction))
    if (!track) domainsByTrack.set(trackKey(dom.helix_id, dom.direction), track = [])
    track.push(entry)
    for (const key of [domainLineKey(dom), domainEndKey(dom, '5p'), domainEndKey(dom, '3p')]) {
      let owners = ownerByKey.get(key)
      if (!owners) ownerByKey.set(key, owners = new Set())
      owners.add(strand.id)
      keys.push(key)
    }
    if (di + 1 < strand.domains.length) transitions.set(
      transitionKey(dom, strand.domains[di + 1]),
      { strand, di },
    )
  }
  keysByStrand.set(strand.id, keys)
}

// 31: crossover-sprite hit circles — full scan versus world-space bins.
const sprites = Array.from({ length: 12_000 }, (_, id) => ({
  id, cx: (id % 600) * 8, indY: Math.floor(id / 600) * 16, order: id,
}))
const spriteBucketSize = 16
const spriteBins = new Map()
for (const sprite of sprites) {
  const key = `${Math.floor(sprite.cx / spriteBucketSize)}:${Math.floor(sprite.indY / spriteBucketSize)}`
  let bucket = spriteBins.get(key)
  if (!bucket) spriteBins.set(key, bucket = [])
  bucket.push(sprite)
}
const spriteQueries = Array.from({ length: 2_000 }, (_, i) => {
  const sprite = sprites[(i * 3571) % sprites.length]
  return { x: sprite.cx + 1, y: sprite.indY + 1, r: 8 }
})
function spriteChecksum(candidatesFor) {
  let checksum = 0
  for (const query of spriteQueries) {
    let first = null
    for (const sprite of candidatesFor(query)) {
      const dx = query.x - sprite.cx, dy = query.y - sprite.indY
      if (dx * dx + dy * dy <= query.r * query.r && (!first || sprite.order < first.order)) first = sprite
    }
    checksum = (checksum + (first?.id ?? -1)) | 0
  }
  return checksum
}
const legacySpriteHit = () => spriteChecksum(() => sprites)
const indexedSpriteHit = () => spriteChecksum(query => {
  const out = []
  const bx0 = Math.floor((query.x - query.r) / spriteBucketSize)
  const bx1 = Math.floor((query.x + query.r) / spriteBucketSize)
  const by0 = Math.floor((query.y - query.r) / spriteBucketSize)
  const by1 = Math.floor((query.y + query.r) / spriteBucketSize)
  for (let bx = bx0; bx <= bx1; bx++) for (let by = by0; by <= by1; by++) {
    out.push(...(spriteBins.get(`${bx}:${by}`) ?? []))
  }
  return out
})

// 32: selected element keys → owner strands.
const selectedKeys = Array.from({ length: 800 }, (_, i) => {
  const strand = strands[(i * 313) % strands.length]
  const dom = strand.domains[i % 4]
  return i % 2 ? domainLineKey(dom) : domainEndKey(dom, i % 3 ? '3p' : '5p')
})
const legacySelectionOwners = () => {
  const selected = new Set(selectedKeys), owners = new Set()
  for (const strand of strands) for (const dom of strand.domains) {
    if (selected.has(domainLineKey(dom)) || selected.has(domainEndKey(dom, '5p')) ||
        selected.has(domainEndKey(dom, '3p'))) { owners.add(strand.id); break }
  }
  let checksum = owners.size
  for (const id of owners) checksum = (checksum + id.length) | 0
  return checksum
}
const indexedSelectionOwners = () => {
  const owners = new Set()
  for (const key of selectedKeys) for (const owner of ownerByKey.get(key) ?? []) owners.add(owner)
  let checksum = owners.size
  for (const id of owners) checksum = (checksum + id.length) | 0
  return checksum
}

// 33: consecutive-domain transition resolution for crossover drags.
const transitionQueries = []
for (let i = 0; i < 200; i++) {
  const strand = strands[(i * 997) % strands.length]
  const di = i % 3
  transitionQueries.push([strand.domains[di], strand.domains[di + 1]])
}
const legacyTransitionLookup = () => {
  let checksum = 0
  for (const [a, b] of transitionQueries) {
    outer: for (const strand of strands) for (let di = 0; di < strand.domains.length - 1; di++) {
      const d0 = strand.domains[di], d1 = strand.domains[di + 1]
      if (transitionKey(d0, d1) === transitionKey(a, b)) {
        checksum = (checksum + strand.id.length + di) | 0
        break outer
      }
    }
  }
  return checksum
}
const indexedTransitionLookup = () => {
  let checksum = 0
  for (const [a, b] of transitionQueries) {
    const match = transitions.get(transitionKey(a, b))
    if (match) checksum = (checksum + match.strand.id.length + match.di) | 0
  }
  return checksum
}

// 34: crossover-drag range validation — all domains versus two track buckets.
const rangeQueries = Array.from({ length: 500 }, (_, i) => {
  const dom = strands[(i * 313) % strands.length].domains[i % 4]
  return { helix: dom.helix_id, direction: dom.direction, lo: dom.start_bp - 80, hi: dom.end_bp + 80 }
})
const countOverlaps = (entries, query) => {
  let count = 0
  for (const entry of entries) if (entry.hi >= query.lo && entry.lo <= query.hi) count++
  return count
}
const legacyValidRanges = () => {
  let checksum = 0
  for (const query of rangeQueries) {
    const entries = []
    for (const strand of strands) for (const dom of strand.domains) {
      if (dom.helix_id === query.helix && dom.direction === query.direction) {
        entries.push({ lo: Math.min(dom.start_bp, dom.end_bp), hi: Math.max(dom.start_bp, dom.end_bp) })
      }
    }
    checksum = (checksum + countOverlaps(entries, query)) | 0
  }
  return checksum
}
const indexedValidRanges = () => {
  let checksum = 0
  for (const query of rangeQueries) {
    checksum = (checksum + countOverlaps(domainsByTrack.get(trackKey(query.helix, query.direction)) ?? [], query)) | 0
  }
  return checksum
}

// 35: immutable reference-only membership + active strand extent.
function deriveReferenceAndExtent() {
  const ref = new Set(), active = new Set()
  let lo = Infinity, hi = -Infinity
  for (const strand of strands) for (const dom of strand.domains) {
    ;(strand.is_reference ? ref : active).add(dom.helix_id)
    if (!strand.is_reference) {
      lo = Math.min(lo, dom.start_bp, dom.end_bp)
      hi = Math.max(hi, dom.start_bp, dom.end_bp)
    }
  }
  for (const helix of active) ref.delete(helix)
  return { ref, lo, hi }
}
const referenceExtent = deriveReferenceAndExtent()
const referenceChecksum = value => value.ref.size * 31 + value.lo * 7 + value.hi
const legacyReferenceExtent = () => {
  let checksum = 0
  for (let i = 0; i < 50; i++) checksum = (checksum + referenceChecksum(deriveReferenceAndExtent())) | 0
  return checksum
}
const indexedReferenceExtent = () => {
  let checksum = 0
  for (let i = 0; i < 50; i++) checksum = (checksum + referenceChecksum(referenceExtent)) | 0
  return checksum
}

// 36: loop/skip marker hit testing by helix and bp.
const markers = Array.from({ length: helixCount }, (_, hi) => ({
  id: `h${hi}`,
  loop_skips: Array.from({ length: 80 }, (_, mi) => ({ bp_index: mi * 17 + hi, delta: mi % 2 ? 1 : -1 })),
}))
const markerIndex = new Map(markers.map(helix => [helix.id,
  new Map(helix.loop_skips.map(marker => [marker.bp_index, marker]))]))
const markerQueries = Array.from({ length: 800 }, (_, i) => {
  const helix = markers[(i * 37) % markers.length]
  const marker = helix.loop_skips[(i * 17) % helix.loop_skips.length]
  return { helixId: helix.id, bp: marker.bp_index }
})
const legacyMarkerHit = () => {
  let checksum = 0
  for (const query of markerQueries) {
    let found = null
    outer: for (const helix of markers) for (const marker of helix.loop_skips) {
      if (helix.id === query.helixId && marker.bp_index === query.bp) { found = marker; break outer }
    }
    checksum = (checksum + (found ? found.bp_index * 3 + found.delta : -1)) | 0
  }
  return checksum
}
const indexedMarkerHit = () => {
  let checksum = 0
  for (const query of markerQueries) {
    const found = markerIndex.get(query.helixId)?.get(query.bp)
    checksum = (checksum + (found ? found.bp_index * 3 + found.delta : -1)) | 0
  }
  return checksum
}

// 37: overhang cylinder instance getters.
const cylinders = Array.from({ length: 20_000 }, (_, i) => ({
  cylIdx: i >> 1, fullCylinder: !!(i & 1), strandId: `s${i}`,
}))
const halfCylinders = new Map(), fullCylinders = new Map()
for (const cylinder of cylinders) (cylinder.fullCylinder ? fullCylinders : halfCylinders)
  .set(cylinder.cylIdx, cylinder)
const cylinderQueries = Array.from({ length: 4_000 }, (_, i) => ({ id: (i * 7919) % 10_000, full: !!(i & 1) }))
const legacyCylinderGetter = () => {
  let checksum = 0
  for (const query of cylinderQueries) {
    checksum = (checksum + (cylinders.find(item => item.fullCylinder === query.full && item.cylIdx === query.id)?.strandId.length ?? 0)) | 0
  }
  return checksum
}
const indexedCylinderGetter = () => {
  let checksum = 0
  for (const query of cylinderQueries) {
    checksum = (checksum + ((query.full ? fullCylinders : halfCylinders).get(query.id)?.strandId.length ?? 0)) | 0
  }
  return checksum
}

// 39: strand/component selection-key expansion.
const selectedStrandIds = Array.from({ length: 800 }, (_, i) => `strand_${(i * 313) % strandCount}`)
const selectedStrandSet = new Set(selectedStrandIds)
const legacySelectionExpansion = () => {
  const keys = new Set()
  for (const strand of strands) {
    if (!selectedStrandSet.has(strand.id)) continue
    for (const dom of strand.domains) {
      keys.add(domainLineKey(dom)); keys.add(domainEndKey(dom, '5p')); keys.add(domainEndKey(dom, '3p'))
    }
  }
  let checksum = keys.size
  for (const key of keys) checksum = (checksum + key.length) | 0
  return checksum
}
const indexedSelectionExpansion = () => {
  const keys = new Set()
  for (const strandId of selectedStrandIds) for (const key of keysByStrand.get(strandId) ?? []) keys.add(key)
  let checksum = keys.size
  for (const key of keys) checksum = (checksum + key.length) | 0
  return checksum
}

// 40: visible-window indicator candidates — every bp/range scan versus valid
// lattice residues + binary search over merged track ranges.
const indicatorRanges = Array.from({ length: helixCount }, (_, hi) =>
  Array.from({ length: 100 }, (_, ri) => [ri * 40 + hi, ri * 40 + hi + 31]))
const mergeRanges = ranges => {
  const sorted = ranges.map(range => [...range]).sort((a, b) => a[0] - b[0])
  const merged = []
  for (const range of sorted) {
    const last = merged.at(-1)
    if (last && range[0] <= last[1] + 1) last[1] = Math.max(last[1], range[1])
    else merged.push(range)
  }
  return merged
}
const mergedIndicatorRanges = indicatorRanges.map(mergeRanges)
const inRangesBinary = (ranges, bp) => {
  let lo = 0, hi = ranges.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1, range = ranges[mid]
    if (bp < range[0]) hi = mid - 1
    else if (bp > range[1]) lo = mid + 1
    else return true
  }
  return false
}
const validResidues = new Set([0, 6, 7, 13, 14, 20])
const visibleStart = 1_500, visibleEnd = 1_755
const legacyIndicatorCandidates = () => {
  let checksum = 0
  for (let hi = 0; hi < helixCount; hi++) for (let bp = visibleStart; bp <= visibleEnd; bp++) {
    if (!validResidues.has(((bp % 21) + 21) % 21)) continue
    if (indicatorRanges[hi].some(range => range[0] <= bp && bp <= range[1])) checksum = (checksum + bp + hi) | 0
  }
  return checksum
}
const indexedIndicatorCandidates = () => {
  let checksum = 0
  for (let hi = 0; hi < helixCount; hi++) for (const residue of validResidues) {
    const mod = ((visibleStart % 21) + 21) % 21
    for (let bp = visibleStart + ((residue - mod + 21) % 21); bp <= visibleEnd; bp += 21) {
      if (inRangesBinary(mergedIndicatorRanges[hi], bp)) checksum = (checksum + bp + hi) | 0
    }
  }
  return checksum
}

const report = {
  environment: { node: process.version, runs: RUNS },
  fixture: { strands: strandCount, domains: strandCount * 4, helices: helixCount,
    sprites: sprites.length, selectedKeys: selectedKeys.length,
    transitionQueries: transitionQueries.length, rangeQueries: rangeQueries.length,
    loopSkipMarkers: helixCount * 80, cylinders: cylinders.length,
    visibleIndicatorColumns: visibleEnd - visibleStart + 1 },
  crossoverSpriteHitBins: paired(legacySpriteHit, indexedSpriteHit),
  selectionElementOwnerIndex: paired(legacySelectionOwners, indexedSelectionOwners),
  crossoverDomainTransitionIndex: paired(legacyTransitionLookup, indexedTransitionLookup),
  crossoverValidationTrackIndex: paired(legacyValidRanges, indexedValidRanges),
  referenceAndExtentDesignCache: paired(legacyReferenceExtent, indexedReferenceExtent),
  loopSkipHitIndex: paired(legacyMarkerHit, indexedMarkerHit),
  overhangCylinderInstanceMaps: paired(legacyCylinderGetter, indexedCylinderGetter),
  selectionKeyExpansionCache: paired(legacySelectionExpansion, indexedSelectionExpansion),
  visibleIndicatorResidueIndex: paired(legacyIndicatorCandidates, indexedIndicatorCandidates),
}

console.log(JSON.stringify(report, null, 2))
if (process.env.NADOC_PERF_OUTPUT) {
  const output = resolve(process.cwd(), process.env.NADOC_PERF_OUTPUT)
  mkdirSync(dirname(output), { recursive: true })
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
}
