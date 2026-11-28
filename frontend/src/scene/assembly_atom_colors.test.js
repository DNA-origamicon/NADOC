import { describe, it, expect, vi } from 'vitest'
import { assemblyAtomColorContext, assemblyAtomRGB, applyInstanceAtomColors } from './assembly_atom_colors.js'
import * as THREE from 'three'

const source = color => ({ design: { strands: [{ id: 'same-id', strand_type: 'scaffold', color, domains: [] }] }, nucleotides: [] })
const atom = { element: 'C', strand_id: 'same-id' }

describe('source-local atom colors', () => {
  it('honors explicit scaffold colors independently across sources with identical IDs', () => {
    for (const color of ['#883344', '#22aa88']) {
      const ctx = assemblyAtomColorContext(source(color), 'strand')
      const rgb = assemblyAtomRGB([atom], ctx)
      new THREE.Color(color).toArray().forEach((v, i) => expect(rgb[i]).toBeCloseTo(v, 6))
    }
  })
  it('keeps source tint deterministic, including atoms with no strand', () => {
    const s = { ...source('#883344'), sourceKey: 'file:part.nadoc' }
    const ctx = assemblyAtomColorContext(s, 'source')
    expect(assemblyAtomRGB([atom], ctx)).toEqual(assemblyAtomRGB([{ element: 'O' }], ctx))
    expect(assemblyAtomColorContext(s, 'source').sourceColor).toBe(ctx.sourceColor)
  })
  it('updates the independent per-instance renderer and clears old cluster/base maps', () => {
    const entry = { ...source('#883344'), atomisticRenderer: { setClusterDisplay: vi.fn(), setColorMode: vi.fn() } }
    applyInstanceAtomColors(entry, 'strand')
    expect(entry.atomisticRenderer.setColorMode).toHaveBeenLastCalledWith('strand', new Map([['same-id', 0x883344]]), new Map())
    applyInstanceAtomColors(entry, 'cpk')
    expect(entry.atomisticRenderer.setClusterDisplay).toHaveBeenLastCalledWith(new Map(), new Map())
    expect(entry.atomisticRenderer.setColorMode.mock.lastCall[0]).toBe('cpk')
  })
})
