/** Paired legacy/current microbenchmarks for responsiveness campaign batch two. */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { performance } from 'node:perf_hooks'

import { connectedCellGroups } from '../src/cadnano-editor/pathview/layout.js'
import {
  buildDomainMapFromDesign,
  buildDomainMapFromGeom,
  buildJunctionMapFromXovers,
} from '../src/scene/overhang_maps.js'
import { baseKey } from '../src/scene/base_ref.js'
import { collectVisibilityBaseKeys } from '../src/scene/visibility_controller.js'
import { buildExtensionArcMap } from '../src/scene/expanded_spacing.js'
import { clusterNucKeysFor } from '../src/scene/cluster_entries.js'

const RUNS = Math.max(5, Number(process.env.NADOC_PERF_RUNS ?? 15))

function summarize(raw) {
  const sorted = [...raw].sort((a, b) => a - b)
  const at = p => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))]
  return { n: raw.length, medianMs: at(0.5), p95Ms: at(0.95), minMs: sorted[0],
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

function legacyConnectedCellGroups(cells) {
  const groups = new Int32Array(cells.length)
  groups.fill(-1)
  let groupId = 0
  for (let seed = 0; seed < cells.length; seed++) {
    if (groups[seed] !== -1) continue
    const queue = [seed]
    groups[seed] = groupId
    while (queue.length) {
      const current = cells[queue.shift()]
      for (let next = 0; next < cells.length; next++) {
        if (groups[next] !== -1) continue
        if (Math.abs(cells[next].row - current.row) <= 1 &&
            Math.abs(cells[next].col - current.col) <= 1) {
          groups[next] = groupId
          queue.push(next)
        }
      }
    }
    groupId++
  }
  return groups
}

function legacyDomainMapFromDesign(design, specMap) {
  const map = new Map()
  for (const spec of specMap.values()) {
    const strand = design.strands?.find(s => s.id === spec.strand_id)
    if (!strand) continue
    const domIdx = strand.domains.findIndex(d => d.overhang_id === spec.id)
    if (domIdx >= 0) map.set(spec.id, { strand, domIdx, domain: strand.domains[domIdx] })
  }
  return map
}

function legacyDomainMapFromGeom(design, backboneEntries) {
  const map = new Map()
  for (const entry of backboneEntries) {
    const id = entry.nuc.overhang_id
    if (!id || map.has(id)) continue
    const strand = design?.strands?.find(s => s.id === entry.nuc.strand_id)
    if (!strand) continue
    const domIdx = entry.nuc.domain_index
    const domain = strand.domains[domIdx]
    if (domain) map.set(id, { strand, domIdx, domain })
  }
  return map
}

function legacyJunctionMapFromXovers(design, specMap, domainMap) {
  const map = new Map()
  for (const [id, spec] of specMap) {
    const domEntry = domainMap.get(id)
    if (!domEntry) continue
    const { strand, domIdx } = domEntry
    const parentDomIdx = domIdx === 0 ? 1 : domIdx - 1
    if (parentDomIdx < 0 || parentDomIdx >= strand.domains.length) continue
    const parentDom = strand.domains[parentDomIdx]
    const xover = design.crossovers?.find(x =>
      (x.half_a?.helix_id === spec.helix_id && x.half_b?.helix_id === parentDom.helix_id) ||
      (x.half_b?.helix_id === spec.helix_id && x.half_a?.helix_id === parentDom.helix_id))
    if (!xover) continue
    const side = xover.half_a?.helix_id === spec.helix_id ? xover.half_a : xover.half_b
    map.set(id, { junctionBp: side.index, junctionDir: side.strand })
  }
  return map
}

function legacyVisibilityBaseKeys(geometry, { strands, extensionIds, domains, clusterSelectors }) {
  const out = new Set()
  for (const nuc of geometry) {
    const key = baseKey(nuc, nuc.copy_k ?? 0)
    if (!key) continue
    if (strands.has(nuc.strand_id) || extensionIds.has(nuc.extension_id) ||
        [...extensionIds].some(id => nuc.helix_id === `__ext_${id}`) ||
        domains.has(`${nuc.strand_id}:${nuc.domain_index}`) ||
        clusterSelectors.has(`h:${nuc.helix_id}`) ||
        clusterSelectors.has(`d:${nuc.strand_id}:${nuc.domain_index}`)) out.add(key)
  }
  return out
}

function legacyConeStrandTypeChecksum(backbone, cones) {
  let checksum = 0
  for (const cone of cones) {
    const type = backbone.find(entry => entry.nuc.strand_id === cone.strandId)?.nuc?.strand_type
    checksum += type === 'scaffold' ? 3 : 1
  }
  return checksum
}

function indexedConeStrandTypeChecksum(strandTypeById, cones) {
  let checksum = 0
  for (const cone of cones) checksum += strandTypeById.get(cone.strandId) === 'scaffold' ? 3 : 1
  return checksum
}

function legacyExtensionArcMap(offsets, design, geometry) {
  const extArcMap = new Map()
  const extNucs = new Map()
  for (const nuc of geometry) {
    if (!nuc.extension_id) continue
    if (!extNucs.has(nuc.extension_id)) extNucs.set(nuc.extension_id, new Map())
    extNucs.get(nuc.extension_id).set(nuc.bp_index, nuc)
  }
  for (const ext of design.extensions) {
    const nucMap = extNucs.get(ext.id)
    if (!nucMap?.size) continue
    const strand = design.strands?.find(s => s.id === ext.strand_id)
    if (!strand) continue
    const termDom = ext.end === 'five_prime' ? strand.domains[0] : strand.domains.at(-1)
    if (!termDom) continue
    const helixOff = offsets.get(termDom.helix_id) ?? { x: 0, y: 0, z: 0 }
    const beadPosMap = new Map()
    for (const [bpIdx, nuc] of nucMap) beadPosMap.set(bpIdx, {
      x: nuc.backbone_position[0] + helixOff.x,
      y: nuc.backbone_position[1] + helixOff.y,
      z: nuc.backbone_position[2] + helixOff.z,
    })
    extArcMap.set(ext.id, beadPosMap)
  }
  return extArcMap
}

function legacyClusterNucKeys(cluster, design) {
  const keys = new Set()
  if (!cluster?.helix_ids?.length) return keys
  const strandIds = new Set()
  const helixIds = new Set()
  const strandMap = new Map((design?.strands ?? []).map(strand => [strand.id, strand]))
  if (cluster.domain_ids?.length) {
    const bridgeHelixIds = new Set()
    for (const domainRef of cluster.domain_ids) {
      const domain = strandMap.get(domainRef.strand_id)?.domains?.[domainRef.domain_index]
      if (domain) bridgeHelixIds.add(domain.helix_id)
      keys.add(`d:${domainRef.strand_id}:${domainRef.domain_index}`)
      strandIds.add(domainRef.strand_id)
    }
    for (const helixId of cluster.helix_ids) {
      if (!bridgeHelixIds.has(helixId)) { keys.add(`h:${helixId}`); helixIds.add(helixId) }
    }
  } else {
    for (const helixId of cluster.helix_ids) { keys.add(`h:${helixId}`); helixIds.add(helixId) }
  }
  for (const ext of design?.extensions ?? []) {
    if (strandIds.has(ext.strand_id)) keys.add(`h:__ext_${ext.id}`)
    else if (helixIds.size) {
      const strand = strandMap.get(ext.strand_id)
      const termDom = strand && (ext.end === 'five_prime' ? strand.domains[0] : strand.domains.at(-1))
      if (termDom && helixIds.has(termDom.helix_id)) keys.add(`h:__ext_${ext.id}`)
    }
  }
  return keys
}

function legacyClusterNucKeysFor(design, idSet) {
  const keys = new Set()
  for (const cluster of design.cluster_transforms ?? []) {
    if (!idSet.has(cluster.id)) continue
    for (const key of legacyClusterNucKeys(cluster, design)) keys.add(key)
  }
  return keys
}

const cells = Array.from({ length: 4_000 }, (_, index) => ({
  row: Math.floor(index / 80), col: index % 80,
}))
const expectedGroups = legacyConnectedCellGroups(cells)
const optimizedGroups = connectedCellGroups(cells)
if (!expectedGroups.every((value, index) => value === optimizedGroups[index])) {
  throw new Error('connectedCellGroups output differs from legacy flood fill')
}
const groupChecksum = fn => () => {
  const groups = fn(cells)
  let checksum = 0
  for (let i = 0; i < groups.length; i++) checksum = (checksum + (i + 1) * (groups[i] + 1)) | 0
  return checksum
}

const strandCount = 3_000
const overhangCount = 1_500
const strands = Array.from({ length: strandCount }, (_, index) => ({
  id: `strand_${index}`,
  domains: [
    { helix_id: `host_${index}`, start_bp: 0, end_bp: 31, direction: 'FORWARD' },
    { helix_id: `overhang_helix_${index}`, start_bp: 31, end_bp: 39,
      direction: 'FORWARD', overhang_id: index < overhangCount ? `overhang_${index}` : undefined },
  ],
}))
const specs = Array.from({ length: overhangCount }, (_, index) => ({
  id: `overhang_${index}`, strand_id: `strand_${index}`, helix_id: `overhang_helix_${index}`,
}))
const specMap = new Map(specs.map(spec => [spec.id, spec]))
const fillerXovers = Array.from({ length: 6_500 }, (_, index) => ({
  half_a: { helix_id: `filler_a_${index}`, index, strand: 'FORWARD' },
  half_b: { helix_id: `filler_b_${index}`, index, strand: 'REVERSE' },
}))
const targetXovers = specs.map((spec, index) => ({
  half_a: { helix_id: spec.helix_id, index: 31 + index, strand: 'FORWARD' },
  half_b: { helix_id: `host_${index}`, index: 31, strand: 'FORWARD' },
}))
const overhangDesign = { strands, crossovers: [...fillerXovers, ...targetXovers] }
const backboneEntries = specs.flatMap((spec, index) => Array.from({ length: 4 }, () => ({
  nuc: { overhang_id: spec.id, strand_id: `strand_${index}`, domain_index: 1 },
})))
const mapChecksum = map => {
  let checksum = map.size
  for (const [id, value] of map) {
    checksum = (checksum + id.length + (value.domIdx ?? value.junctionBp ?? 0)) | 0
  }
  return checksum
}
const visibilityExtensionIds = new Set(Array.from({ length: 500 }, (_, index) => `ext_${index}`))
const visibilityGeometry = Array.from({ length: 20_000 }, (_, index) => ({
  helix_id: index % 20 === 0 ? `__ext_ext_${index % 500}` : `helix_${index % 200}`,
  bp_index: index, direction: index % 2 ? 'FORWARD' : 'REVERSE',
  strand_id: `unselected_${index % 1000}`, domain_index: index % 8,
}))
const visibilitySelectors = {
  strands: new Set(), extensionIds: visibilityExtensionIds,
  domains: new Set(), clusterSelectors: new Set(),
}
const setChecksum = set => {
  let checksum = set.size
  for (const key of set) checksum = (checksum + key.length) | 0
  return checksum
}
const visibilityLegacy = legacyVisibilityBaseKeys(visibilityGeometry, visibilitySelectors)
const visibilityCurrent = collectVisibilityBaseKeys(visibilityGeometry, visibilitySelectors)
if (setChecksum(visibilityLegacy) !== setChecksum(visibilityCurrent)) {
  throw new Error('visibility base-key output differs from legacy')
}
const rendererBackbone = Array.from({ length: 10_000 }, (_, index) => ({ nuc: {
  strand_id: `render_strand_${Math.floor(index / 10)}`,
  strand_type: Math.floor(index / 10) % 5 === 0 ? 'scaffold' : 'staple',
} }))
const rendererCones = Array.from({ length: 3_000 }, (_, index) => ({
  strandId: `render_strand_${(index * 313) % 1000}`,
}))
const rendererStrandTypes = new Map()
for (const entry of rendererBackbone) {
  if (!rendererStrandTypes.has(entry.nuc.strand_id)) {
    rendererStrandTypes.set(entry.nuc.strand_id, entry.nuc.strand_type)
  }
}
if (legacyConeStrandTypeChecksum(rendererBackbone, rendererCones) !==
    indexedConeStrandTypeChecksum(rendererStrandTypes, rendererCones)) {
  throw new Error('renderer cone strand types differ from legacy')
}
const spacingStrands = Array.from({ length: 3_000 }, (_, index) => ({
  id: `spacing_strand_${index}`,
  domains: [{ helix_id: `spacing_helix_${index}` }, { helix_id: `spacing_tail_${index}` }],
}))
const spacingExtensions = Array.from({ length: 1_500 }, (_, index) => ({
  id: `spacing_ext_${index}`, strand_id: `spacing_strand_${index * 2}`,
  end: index % 2 ? 'five_prime' : 'three_prime',
}))
const spacingGeometry = spacingExtensions.flatMap((ext, index) =>
  Array.from({ length: 4 }, (_, bp) => ({ extension_id: ext.id, bp_index: bp,
    backbone_position: [index, bp, index + bp] })))
const spacingOffsets = new Map(spacingStrands.flatMap((strand, index) => [
  [strand.domains[0].helix_id, { x: index % 7, y: 1, z: 2 }],
  [strand.domains[1].helix_id, { x: 3, y: index % 11, z: 4 }],
]))
const spacingDesign = { strands: spacingStrands, extensions: spacingExtensions }
const arcChecksum = map => {
  let checksum = map.size
  for (const beads of map.values()) for (const pos of beads.values()) {
    checksum = (checksum + pos.x + pos.y + pos.z) | 0
  }
  return checksum
}
if (arcChecksum(legacyExtensionArcMap(spacingOffsets, spacingDesign, spacingGeometry)) !==
    arcChecksum(buildExtensionArcMap(spacingOffsets, spacingDesign, spacingGeometry))) {
  throw new Error('extension spacing arc output differs from legacy')
}
const clusterStrands = Array.from({ length: 5_000 }, (_, index) => ({
  id: `cluster_strand_${index}`,
  domains: [{ helix_id: `cluster_helix_${index}`, start_bp: 0, end_bp: 31 }],
}))
const benchmarkClusters = Array.from({ length: 500 }, (_, index) => ({
  id: `cluster_${index}`, helix_ids: [`cluster_helix_${index}`],
  domain_ids: [{ strand_id: `cluster_strand_${index * 7}`, domain_index: 0 }],
}))
const clusterDesign = { strands: clusterStrands, extensions: [], cluster_transforms: benchmarkClusters }
const clusterIds = new Set(benchmarkClusters.map(cluster => cluster.id))
if (setChecksum(legacyClusterNucKeysFor(clusterDesign, clusterIds)) !==
    setChecksum(clusterNucKeysFor(clusterDesign, clusterIds))) {
  throw new Error('cluster nucleotide keys differ from legacy')
}
const designMapLegacy = legacyDomainMapFromDesign(overhangDesign, specMap)
const designMapCurrent = buildDomainMapFromDesign(overhangDesign, specMap)
const geomMapLegacy = legacyDomainMapFromGeom(overhangDesign, backboneEntries)
const geomMapCurrent = buildDomainMapFromGeom(overhangDesign, backboneEntries)
const junctionLegacy = legacyJunctionMapFromXovers(overhangDesign, specMap, designMapLegacy)
const junctionCurrent = buildJunctionMapFromXovers(overhangDesign, specMap, designMapCurrent)
for (const [name, before, after] of [
  ['design domain map', designMapLegacy, designMapCurrent],
  ['geometry domain map', geomMapLegacy, geomMapCurrent],
  ['crossover junction map', junctionLegacy, junctionCurrent],
]) {
  if (mapChecksum(before) !== mapChecksum(after)) throw new Error(`${name} output differs from legacy`)
}

const report = {
  environment: { node: process.version, runs: RUNS },
  fixture: { layoutCells: cells.length, strands: strandCount, overhangs: overhangCount,
    backboneEntries: backboneEntries.length, crossovers: overhangDesign.crossovers.length,
    visibilityGeometry: visibilityGeometry.length, visibilityExtensions: visibilityExtensionIds.size,
    rendererBackbone: rendererBackbone.length, rendererCones: rendererCones.length,
    spacingStrands: spacingStrands.length, spacingExtensions: spacingExtensions.length,
    spacingGeometry: spacingGeometry.length, clusterStrands: clusterStrands.length,
    clusters: benchmarkClusters.length },
  layoutConnectedGroups: {
    before: measure(groupChecksum(legacyConnectedCellGroups)),
    after: measure(groupChecksum(connectedCellGroups)),
  },
  overhangDomainFromDesign: {
    before: measure(() => mapChecksum(legacyDomainMapFromDesign(overhangDesign, specMap))),
    after: measure(() => mapChecksum(buildDomainMapFromDesign(overhangDesign, specMap))),
  },
  overhangDomainFromGeometry: {
    before: measure(() => mapChecksum(legacyDomainMapFromGeom(overhangDesign, backboneEntries))),
    after: measure(() => mapChecksum(buildDomainMapFromGeom(overhangDesign, backboneEntries))),
  },
  overhangJunctionFromCrossovers: {
    before: measure(() => mapChecksum(legacyJunctionMapFromXovers(overhangDesign, specMap, designMapLegacy))),
    after: measure(() => mapChecksum(buildJunctionMapFromXovers(overhangDesign, specMap, designMapCurrent))),
  },
  visibilityExtensionHelices: {
    before: measure(() => setChecksum(legacyVisibilityBaseKeys(visibilityGeometry, visibilitySelectors))),
    after: measure(() => setChecksum(collectVisibilityBaseKeys(visibilityGeometry, visibilitySelectors))),
  },
  rendererConeStrandTypes: {
    before: measure(() => legacyConeStrandTypeChecksum(rendererBackbone, rendererCones)),
    after: measure(() => indexedConeStrandTypeChecksum(rendererStrandTypes, rendererCones)),
  },
  expandedSpacingExtensionHosts: {
    before: measure(() => arcChecksum(legacyExtensionArcMap(spacingOffsets, spacingDesign, spacingGeometry))),
    after: measure(() => arcChecksum(buildExtensionArcMap(spacingOffsets, spacingDesign, spacingGeometry))),
  },
  clusterSharedStrandIndex: {
    before: measure(() => setChecksum(legacyClusterNucKeysFor(clusterDesign, clusterIds))),
    after: measure(() => setChecksum(clusterNucKeysFor(clusterDesign, clusterIds))),
  },
}

console.log(JSON.stringify(report, null, 2))
if (process.env.NADOC_PERF_OUTPUT) {
  const output = resolve(process.cwd(), process.env.NADOC_PERF_OUTPUT)
  mkdirSync(dirname(output), { recursive: true })
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
}
