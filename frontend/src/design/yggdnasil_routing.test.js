import { it, expect } from 'vitest'
import { enumerateRods } from './yggdnasil.js'
import { routingScreen, routingTotals, routingExport } from './yggdnasil_routing.js'
import report from './yggdnasil_routing.json'

it('covers every atlas footprint and preserves every candidate across routing categories', () => {
  for (const scaffold of [7249, 7560, 8064]) {
    const atlas = enumerateRods({ scaffold })
    expect(atlas.entries.every(e => routingScreen(e).status !== 'not_screened')).toBe(true)
    const t = routingTotals(atlas.entries)
    expect(t.excluded + t.path_found + t.unresolved).toBe(atlas.count)
    const summary = report.summaries.find(s => s.scaffold === scaffold).totals.all
    expect(t.excluded).toBe(summary.parity_obstruction.candidates + summary.no_path.candidates)
    expect(t.path_found).toBe(summary.path_found.candidates)
    expect(t.unresolved).toBe(summary.unresolved.candidates)
  }
})
it('does not reject unresolved searches and exports the scope with the evidence', () => {
  const atlas = enumerateRods()
  const entry = atlas.entries.find(e => routingScreen(e).status === 'unresolved')
  expect(routingScreen(entry).excluded).toBe(false)
  const output = routingExport(atlas)
  expect(output.routingScreen.scope).toContain('Hamiltonian')
  expect(output.entries.every(e => e.routing.label)).toBe(true)
  const smaller = enumerateRods({ minLength: 200, reserve: 500 })
  expect(smaller.entries.every(e => routingScreen(e).status !== 'not_screened')).toBe(true)
})
