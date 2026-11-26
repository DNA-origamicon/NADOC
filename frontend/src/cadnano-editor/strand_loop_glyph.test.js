import { it, expect, vi } from 'vitest'
import { drawStrandLoops } from './strand_loop_glyph.js'
import { sequenceColumns, skipMapFromHelices } from './sequence_layout.js'
import { strandLengthNtFromDesign } from '../scene/strand_length.js'
import { strandSequenceDisplay } from '../ui/strand_sequence_display.js'
const dom = { helix_id: 'h', start_bp: 3, end_bp: 0, direction: 'REVERSE' }
const strand = { id: 's', domains: [dom], sequence: 'AC' + 'N'.repeat(30) + 'GT',
  loops: [{ helix_id: 'h', direction: 'REVERSE', bp_index: 2, length: 30 }] }
const design = { helices: [{ id: 'h' }], strands: [strand] }
it('draws one counted glyph on the owning track', () => {
  const ctx = Object.fromEntries(['save', 'restore', 'beginPath', 'moveTo', 'bezierCurveTo', 'stroke', 'fillText'].map(k => [k, vi.fn()]))
  drawStrandLoops(ctx, design, new Map([['h', { fwdY: 10, revY: 20 }]]), bp => bp * 5, 10, 1)
  expect(ctx.moveTo).toHaveBeenCalledWith(10, 20)
  expect(ctx.fillText.mock.calls[0][0]).toBe('30')
  expect(ctx.stroke).toHaveBeenCalledTimes(1)
})
it('consumes loop bases without shifting subsequent cadnano columns', () => {
  expect([...sequenceColumns(strand, skipMapFromHelices(design.helices))].map(c => c.seqIndex)).toEqual([0, 1, 32, 33])
  expect(strandLengthNtFromDesign(strand, design)).toBe(34)
  expect(strandSequenceDisplay(strand, design).text).toBe(strand.sequence)
})
