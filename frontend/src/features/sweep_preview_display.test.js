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
  ['unexpected nucleotide candidate', d => { d.candidate = d.before }],
  ['nonfinite path', d => { d.sweep_preview.path_nm[0][0] = Infinity }],
  ['invalid warning', d => { d.sweep_preview.feasibility.warning_segments = [999] }],
  ['unbounded knots', d => { d.sweep_preview.points_nm = Array.from({ length: 257 }, () => [0, 0, 0]) }],
  ['basis mismatch', d => { d.sweep_preview.point_bases.pop() }],
  ['unknown preview field', d => { d.sweep_preview.recovery = 'not an input' }],
])('refuses %s', (_, alter) => {
  const value = sweepPacket(); alter(value)
  expect(() => validateSweepPreviewDisplay(value, { prepare: true })).toThrow()
})

it('accepts ordinary Sweep extent above the obsolete tiny-fixture limits', () => {
  const packet = sweepPacket({ prepare: false, geometry: false })
  packet.sweep_preview.length_bp = 504
  packet.sweep_preview.total_new_bp = 18 * 504
  packet.sweep_preview.helix_paths_nm = Array.from({ length: 18 }, () => [[0, 0, 0], [0, 0, 171]])
  packet.sweep_preview.cross_section_nm = Array.from({ length: 18 }, (_, i) => [i, 0])
  expect(validateSweepPreviewDisplay(packet, { prepare: false })).toBe(packet)
})
it.each(['length_bp', 'total_new_bp'])('still refuses native extent beyond the builder limit: %s', key => {
  const packet = sweepPacket({ prepare: false, geometry: false })
  packet.sweep_preview[key] = 200_001
  expect(() => validateSweepPreviewDisplay(packet, { prepare: false })).toThrow('invalid native Sweep extent')
})
it('still refuses too many Sweep helix paths', () => {
  const packet = sweepPacket({ prepare: false, geometry: false })
  packet.sweep_preview.helix_paths_nm = Array.from({ length: 513 }, () => [])
  expect(() => validateSweepPreviewDisplay(packet, { prepare: false })).toThrow('display allowance exceeded')
})
