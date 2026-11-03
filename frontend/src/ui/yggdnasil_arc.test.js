import { it, expect } from 'vitest'
import { arcEnvelope, arcPreview } from './yggdnasil_arc.js'
const entry = { helices: 2, points: [{ x: -0.5 }, { x: 0.5 }] }
it('shows straight length and closes both sides of a full-circle envelope', () => {
  expect(arcEnvelope(entry, 100, 0)).toEqual([[-2.125, 0], [2.125, 0], [2.125, 33.4], [-2.125, 33.4]])
  const p = arcEnvelope(entry, 100, 2 * Math.PI), half = p.length / 2
  expect(p[0][0]).toBeCloseTo(p[half - 1][0]); expect(p[0][1]).toBeCloseTo(p[half - 1][1])
  expect(p[half][0]).toBeCloseTo(p.at(-1)[0]); expect(p[half][1]).toBeCloseTo(p.at(-1)[1])
  expect(arcPreview(entry, 100, Math.PI)).toContain('Nominal uniform planar arc')
})
