import { afterEach, expect, it } from 'vitest'
import { filterInventory, inventoryCSV, safeExternalURL, showNanobaseInventory } from './nanobase_inventory.js'
let modal
const snapshot = { retrieved_at: '2026-10-27', coverage: '2 public records', records: [
  { id: 1, title: 'MagicDNA gripper', software: ['MagicDNA'], files: [{ name: 'gripper.mat', url: 'https://nanobase.org/file.mat', category: 'design' }], publication: { status: 'Journal article linked', title: 'Assembly paper', url: 'https://doi.org/10.123/a' }, supplement: { status: 'Verified routing figure', evidence: [{ url: 'https://example.org/si.pdf', label: 'SI p. 3' }] }, comparison: 'Not compared', notes: ['Modified overhangs'], source_url: 'https://nanobase.org/structures/1' },
  { id: 2, title: '=unsafe title', software: ['Unclassified JSON'], files: [], publication: { status: 'No publication supplied' }, supplement: { status: 'Unresolved', evidence: [] }, comparison: 'Not compared', notes: [], source_url: 'javascript:alert(1)' },
] }
afterEach(() => { modal?.close(); document.body.replaceChildren() })
it('filters independently by publication, software, and figure evidence', () => {
  expect(filterInventory(snapshot.records, { query: 'overhangs' }).map(r => r.id)).toEqual([1])
  expect(filterInventory(snapshot.records, { software: 'MagicDNA', figures: 'verified' })).toHaveLength(1)
  expect(filterInventory(snapshot.records, { publication: 'none', figures: 'verified' })).toHaveLength(0)
})
it('exports quoted CSV and neutralizes spreadsheet formulas', () => {
  const csv = inventoryCSV(snapshot.records)
  expect(csv).toContain("'=unsafe title")
  expect(csv).toContain('Not compared')
  expect(csv).toContain('gripper.mat')
})
it('only makes HTTP(S) source links clickable', () => {
  expect(safeExternalURL('javascript:alert(1)')).toBeNull()
  expect(safeExternalURL('https://nanobase.org/structures/1')).toBe('https://nanobase.org/structures/1')
})
it('opens without an active design, filters, exposes evidence, and cleans up', () => {
  modal = showNanobaseInventory({ snapshot })
  expect(document.querySelectorAll('tbody tr')).toHaveLength(2)
  expect(document.querySelectorAll('a[href^="javascript:"]')).toHaveLength(0)
  const search = document.querySelector('[data-search]'); search.value = 'gripper'; search.dispatchEvent(new Event('input'))
  expect(document.querySelectorAll('tbody tr')).toHaveLength(1)
  expect(document.querySelector('tbody').textContent).toContain('Modified overhangs')
  expect(showNanobaseInventory({ snapshot })).toBe(modal)
  modal.close(); expect(document.querySelector('.nanobase-inventory')).toBeNull()
})
it('ships source-linked evidence without promoting unreviewed uploads to training truth', async () => {
  const { default: data } = await import('../data/nanobase_inventory.json')
  expect(data.records).toHaveLength(109)
  expect(new Set(data.records.map(r => r.id)).size).toBe(109)
  for (const r of data.records) {
    expect(safeExternalURL(r.source_url)).not.toBeNull()
    expect(r.comparison).toContain('Not compared')
    if (r.supplement.status.startsWith('Verified')) {
      expect(r.supplement.evidence.length).toBeGreaterThan(0)
      for (const e of r.supplement.evidence) {
        expect(e.sha256).toMatch(/^[a-f0-9]{64}$/)
        expect(e.label).toContain('PDF page')
        expect(safeExternalURL(e.url)).not.toBeNull()
      }
    }
  }
})
