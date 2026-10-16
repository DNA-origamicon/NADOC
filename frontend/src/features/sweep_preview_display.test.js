import { expect, it, vi } from 'vitest'
import { validateSweepPreviewDisplay } from './sweep_preview_display.js'
import { sweepPacket } from '../test-helpers/sweep_preview.js'

it.each([{ prepare: true }, { prepare: false }, { prepare: false, geometry: false }])('accepts bounded native Sweep packet %j without copying its graph', options => {
  const packet = sweepPacket(options), original = structuredClone(packet)
  const clone = vi.spyOn(globalThis, 'structuredClone').mockImplementation(() => { throw new Error('Graph clone') })
  try { expect(validateSweepPreviewDisplay(packet, options)).toBe(packet) } finally { clone.mockRestore() }
  expect(packet).toEqual(original)
})
it('requires the complete host envelope for controller use', () => {
  expect(() => validateSweepPreviewDisplay(sweepPacket(), { prepare: true, requireEnvelope: true })).toThrow()
  const value = sweepPacket({ envelope: true })
  expect(validateSweepPreviewDisplay(value, { prepare: true, requireEnvelope: true })).toBe(value)
})
it.each([
  ['false proof', d => { d.downstream_evaluated = true }], ['unknown pane', d => { d.design = {} }],
  ['missing controls', d => { delete d.control_context }], ['foreign source', d => { d.control_context.inputs.source_helix_id = 'missing' }],
  ['frame missing', d => { d.control_context.helices[0].lattice_frame_id = 'missing' }],
  ['coordinate mismatch', d => { d.control_context.helices[0].length_bp = 9 }],
  ['missing nucleotide', d => { d.candidate.nucleotides.pop() }],
  ['nonfinite path', d => { d.sweep_preview.path_nm[0][0] = Infinity }],
  ['invalid warning', d => { d.sweep_preview.feasibility.warning_segments = [999] }],
  ['unbounded knots', d => { d.sweep_preview.points_nm = Array.from({ length: 257 }, () => [0, 0, 0]) }],
  ['basis mismatch', d => { d.sweep_preview.point_bases.pop() }],
  ['unknown preview field', d => { d.sweep_preview.recovery = 'not an input' }],
])('refuses %s', (_, alter) => {
  const value = sweepPacket(); alter(value)
  expect(() => validateSweepPreviewDisplay(value, { prepare: true })).toThrow()
})
