import * as THREE from 'three'
import { buildStapleColorMap, buildNucLetterMap, STAPLE_PALETTE } from './helix_renderer/palette.js'
import { computeAtomStrandColors, computeAtomNucColors, atomColorsFromLetters } from './color_util.js'
import { resolveAtomColor } from './atomistic_renderer/color_resolver.js'

/** Source-local adapter for the same color maps/resolver used by part atoms.
 * Never consult the open part's global strand maps: IDs can overlap across sources.
 */
export function assemblyAtomColorContext(source, mode) {
  const design = source.design ?? {}, nucleotides = source.nucleotides ?? []
  const strandColors = { ...Object.fromEntries((design.strands ?? [])
    .filter(s => s.color).map(s => [s.id, s.color])), ...source.customColors }
  const state = { currentDesign: design, coloringMode: mode, strandColors }
  let hash = 0
  for (const ch of source.sourceKey ?? source.group?.userData.sharedSource ?? '') hash = (hash * 31 + ch.charCodeAt(0)) | 0
  const strands = computeAtomStrandColors(state, buildStapleColorMap(nucleotides, design))
  const sourceColor = STAPLE_PALETTE[Math.abs(hash) % STAPLE_PALETTE.length]
  return {
    colorMode: mode === 'base' ? 'base' : ['strand', 'cluster', 'source'].includes(mode) ? 'strand' : 'cpk',
    strandColors: strands,
    baseColors: mode === 'base' ? atomColorsFromLetters(buildNucLetterMap(design, nucleotides), nucleotides) : new Map(),
    clusterColors: computeAtomNucColors(state),
    sourceColor: mode === 'source' ? sourceColor : null,
  }
}

export function assemblyAtomRGB(atoms, ctx) {
  const out = new Float32Array(atoms.length * 3), cache = new Map()
  for (let i = 0; i < atoms.length; i++) {
    const hex = ctx.sourceColor ?? resolveAtomColor(ctx, atoms[i], null, false)
    if (!cache.has(hex)) cache.set(hex, new THREE.Color(hex).toArray())
    out.set(cache.get(hex), i * 3)
  }
  return out
}

/** Both atoms and bonds repaint retained textures; no geometry rebuild or fetch. */
export function repaintAssemblyAtoms(source, mode) {
  const ctx = assemblyAtomColorContext(source, mode)
  for (const batch of [...(source.atomBatch ?? []), ...(source.atomBondLod ? [{
    atomList: source.atomBondLod.colorAtoms, colorTex: source.atomBondLod.segColorTex,
  }] : [])]) {
    const rgb = assemblyAtomRGB(batch.atomList, ctx), data = batch.colorTex.image.data
    for (let i = 0; i < batch.atomList.length; i++) data.set(rgb.subarray(i * 3, i * 3 + 3), i * 4)
    batch.colorTex.needsUpdate = true
  }
}

export function applyInstanceAtomColors(entry, mode) {
  const renderer = entry.atomisticRenderer
  if (!renderer) return
  const ctx = assemblyAtomColorContext(entry, mode)
  if (ctx.sourceColor != null) for (const strand of entry.design?.strands ?? []) ctx.strandColors.set(strand.id, ctx.sourceColor)
  renderer.setClusterDisplay(new Map(), ctx.clusterColors)
  renderer.setColorMode(ctx.colorMode, ctx.strandColors, ctx.baseColors)
}
