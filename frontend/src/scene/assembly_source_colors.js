import * as THREE from 'three'
import {
  C, BASE_COLORS, buildStapleColorMap, buildNucLetterMap, buildClusterColorLookup,
  nucColor, nucSlabColor, nucArrowColor,
} from './helix_renderer/palette.js'

/** Repaint retained source slots, never rebuilding molecular or tube geometry.
 * The controller entries retain their source-local mesh/index identity after
 * shared instancing replaces instanceColor with one RGBA texture per mesh. */
export function repaintAssemblySourceColors(source, mode = 'strand') {
  const ctrl = source?.helixCtrl
  if (!ctrl || !source.design) return
  const custom = source.customColors ?? {}
  const palette = source.stapleColorMap ??= buildStapleColorMap(source.nucleotides ?? [], source.design)
  const loop = new Set()
  const letters = mode === 'base'
    ? buildNucLetterMap(source.design, ctrl.backboneEntries.map(entry => entry.nuc).filter(Boolean))
    : null
  const cluster = mode === 'cluster' ? buildClusterColorLookup(source.design) : null
  const perNuc = nuc => cluster?.(nuc) ?? (letters ? BASE_COLORS[letters.get(nuc)] : null)
    ?? ((mode === 'overhang-only' && nuc?.overhang_id == null) ? C.dim_gray : null)
  const strandHex = id => custom[id] ?? palette.get(id) ?? C.unassigned
  const natural = (nuc, kind, strandId) => {
    // The strand mode historically uses the builder's binder-specific palette;
    // other modes use applyColoring's strand fallback (including scaffold hues).
    if (mode === 'strand' && nuc) {
      return [nucColor, nucSlabColor, nucArrowColor][kind](nuc, palette, custom, loop)
    }
    const id = nuc?.strand_id ?? strandId
    if (!id) return C.unassigned
    if (nuc?.strand_type === 'scaffold') {
      return [C.scaffold_backbone, C.scaffold_slab, C.scaffold_arrow][kind]
    }
    return strandHex(id)
  }
  const domainHex = (domain, overhang) => {
    if (mode === 'overhang-only' && !overhang) return C.dim_gray
    return cluster?.({ helix_id: domain.helixId, strand_id: domain.strandId,
      domain_index: domain.domainIndex ?? 0 }) ?? strandHex(domain.strandId)
  }
  const activeByMesh = new Map((source.activeMeshes ?? []).map(active => [active.mesh, active]))
  const rgbCache = new Map()
  const color = new THREE.Color()
  const rgb = hex => {
    let value = rgbCache.get(hex)
    if (!value) { color.setHex(hex); value = [color.r, color.g, color.b]; rgbCache.set(hex, value) }
    return value
  }
  const write = (data, index, hex, alpha = true) => {
    const values = rgb(hex), offset = index * 4
    data[offset] = values[0]; data[offset + 1] = values[1]; data[offset + 2] = values[2]
    if (alpha) data[offset + 3] = 1
  }
  const dirty = new Set()
  const writeMesh = (mesh, index, hex) => {
    const active = activeByMesh.get(mesh)
    if (!active?.bpColorData || index < 0 || index >= active.baseCount) return
    write(active.bpColorData, index, hex, false)
    dirty.add(active.bpColorTex)
  }
  const paint = (entries, kind) => {
    for (const entry of entries ?? []) {
      const nuc = kind === 2 ? entry.fromNuc : entry.nuc
      const hex = (nuc ? perNuc(nuc) : null) ?? natural(nuc, kind, entry.strandId)
      entry.defaultColor = hex
      writeMesh(entry.instMesh, entry.id, hex)
      if (entry.connectorMesh && entry.connectorId != null) writeMesh(entry.connectorMesh, entry.connectorId, hex)
    }
  }
  paint(ctrl.backboneEntries, 0)
  paint(ctrl.slabEntries, 1)
  paint(ctrl.coneEntries, 2)
  for (const texture of dirty) if (texture) texture.needsUpdate = true

  // The mid tier averages the same domain colors into its existing intervals.
  // Interval transforms and membership are fixed until a source rebuild.
  const mid = source.midLod
  if (mid?.segColorTex && mid.intervals) {
    for (let i = 0; i < mid.intervals.length; i++) {
      const domains = mid.intervals[i].domains
      const offset = i * 4
      let r = 0, g = 0, b = 0
      for (const domain of domains) {
        const values = rgb(domainHex(domain, false))
        r += values[0]; g += values[1]; b += values[2]
      }
      const count = domains.length
      mid.segColorData[offset] = count ? r / count : 1
      mid.segColorData[offset + 1] = count ? g / count : 1
      mid.segColorData[offset + 2] = count ? b / count : 1
      mid.segColorData[offset + 3] = 1
    }
    mid.segColorTex.needsUpdate = true
  }
  const overhang = source.overhangLod
  if (overhang?.segColorTex) {
    for (const domain of ctrl.overhangCylData ?? []) {
      if (!!domain.fullCylinder !== !!overhang.fullCylinder || domain.cylIdx >= overhang.numSegments) continue
      write(overhang.segColorData, domain.cylIdx, domainHex(domain, true))
    }
    overhang.segColorTex.needsUpdate = true
  }

  // Tube vertices were concatenated once at build time. Remembered ranges let
  // each domain repaint its existing color attribute without cloning/merging.
  const curved = source.curvedCylLod?.mesh?.geometry
  const attribute = curved?.getAttribute('color')
  if (attribute) {
    for (const range of source.curvedColorRanges ?? []) {
      // Match the part renderer's existing curved-domain coloring convention.
      const values = rgb(domainHex({ ...range.domain, domainIndex: 0 }, range.overhang))
      const end = (range.start + range.count) * 3
      for (let i = range.start * 3; i < end; i += 3) {
        attribute.array[i] = values[0]; attribute.array[i + 1] = values[1]; attribute.array[i + 2] = values[2]
      }
    }
    attribute.needsUpdate = true
  }
}
