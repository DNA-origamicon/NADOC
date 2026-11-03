import { it, expect } from 'vitest'
import { enumerateRods, footprintKey, position } from './yggdnasil.js'
it('matches native lattice coordinates and distinguishes embedded graph shapes', () => {
  expect(position('honeycomb', 0, -1)[1]).toBe(0.5)
  const line = [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 2, y: 0 }]
  expect(footprintKey('square', line)).toBe(footprintKey('square', line.map(p => ({ x: 5, y: p.x + 2 }))))
  expect(footprintKey('square', line)).not.toBe(footprintKey('square', [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }]))
})
it('enumerates known shells and every integer length once', () => {
  const atlas = enumerateRods({ minLength: 1000 })
  expect(atlas.entries.filter(e => e.lattice === 'square').map(e => e.helices).sort((a,b) => a-b)).toEqual([1, 2, 4, 5, 6])
  expect(atlas.entries.some(e => e.lattice === 'honeycomb' && e.helices === 6 && e.sources.some(s => s.center === 'Cell'))).toBe(true)
  expect(new Set(atlas.entries.map(e => e.canonical)).size).toBe(atlas.entries.length)
  let count = 0
  for (const e of atlas.entries) {
    for (let length = 1000; length * e.helices <= 7249; length++) count++
    expect(e.maxLength * e.helices).toBeLessThanOrEqual(7249)
    expect((e.maxLength + 1) * e.helices).toBeGreaterThan(7249)
  }
  expect(atlas.count).toBe(count)
})
it('handles exhausted budgets and bounded reserve', () => {
  expect(enumerateRods({ reserve: 7248 }).count).toBe(0)
  expect(enumerateRods({ scaffold: 8064, reserve: 64, minLength: 1000 }).entries.every(e => e.helices * e.maxLength <= 8000)).toBe(true)
  expect(() => enumerateRods({ minLength: 0 })).toThrow()
})
