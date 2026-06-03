import { describe, it, expect, vi } from 'vitest'
import { BDNA_RISE_PER_BP } from '../constants.js'
import { sliceTargetKeys, initSliceHighlighter } from './slice_highlighter.js'

const helix = (id, axis_start, bp_start, length_bp) => ({ id, axis_start, bp_start, length_bp })

describe('sliceTargetKeys', () => {
  const design = { helices: [
    helix('h1', { x: 0, y: 0, z: 0 }, 0, 10),
    helix('h2', { x: 0, y: 0, z: 0 }, 0, 4),
  ] }

  it('maps an XY-plane offset to the crossed bp per helix (plane normal = z)', () => {
    const keys = sliceTargetKeys(design, 5 * BDNA_RISE_PER_BP, 'XY')
    expect(keys.has('h1::5')).toBe(true)   // bp 5 in [0,10)
    expect(keys.has('h2::5')).toBe(false)  // bp 5 out of h2's [0,4)
  })

  it('excludes helices the plane does not cross (bp out of range)', () => {
    expect(sliceTargetKeys(design, 20 * BDNA_RISE_PER_BP, 'XY').size).toBe(0)
  })

  it('uses the x axis for the YZ plane', () => {
    const d = { helices: [helix('hx', { x: 0, y: 0, z: 0 }, 0, 10)] }
    expect(sliceTargetKeys(d, 3 * BDNA_RISE_PER_BP, 'YZ').has('hx::3')).toBe(true)
  })

  it('empty for a null design', () => {
    expect(sliceTargetKeys(null, 0, 'XY').size).toBe(0)
  })
})

describe('initSliceHighlighter', () => {
  function setup() {
    const calls = []
    const beads = [
      { nuc: { helix_id: 'h1', bp_index: 5 }, defaultColor: 0xaaaaaa },
      { nuc: { helix_id: 'h1', bp_index: 6 }, defaultColor: 0xbbbbbb },
    ]
    const designRenderer = {
      getBackboneEntries: () => beads,
      getSlabEntries: () => [],
      setEntryColor: (entry, color) => calls.push([entry.nuc.bp_index, color]),
    }
    const design = { helices: [helix('h1', { x: 0, y: 0, z: 0 }, 0, 10)] }
    const tool = initSliceHighlighter({ designRenderer, getDesign: () => design })
    return { tool, calls, beads }
  }

  it('paints only the crossed bead white on update', () => {
    const { tool, calls } = setup()
    tool.update(5 * BDNA_RISE_PER_BP, 'XY')
    expect(calls).toEqual([[5, 0xffffff]]) // bp 5 crossed; bp 6 untouched
  })

  it('reverts painted beads to their default colour on clear', () => {
    const { tool, calls } = setup()
    tool.update(5 * BDNA_RISE_PER_BP, 'XY')
    calls.length = 0
    tool.clear()
    expect(calls).toEqual([[5, 0xaaaaaa]])
  })

  it('a second update clears the previous highlight first', () => {
    const { tool, calls } = setup()
    tool.update(5 * BDNA_RISE_PER_BP, 'XY')
    calls.length = 0
    tool.update(6 * BDNA_RISE_PER_BP, 'XY')
    // first reverts bp5 to default, then paints bp6 white.
    expect(calls).toEqual([[5, 0xaaaaaa], [6, 0xffffff]])
  })
})
