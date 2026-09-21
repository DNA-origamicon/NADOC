import { afterEach, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { showCpdProgress } from './cpd_progress.js'
import { attachmentDirections, attachmentMetrics, contextAtoms, elementStatus, projectAtoms, validateSnapshot } from './cpd_progress_model.js'

const catalog = () => JSON.parse(readFileSync('public/cpd-progress.json', 'utf8'))

const checks = [{ label: 'Bond geometry', state: 'pass', value: '0.01 Å' }]
const fixture = () => ({ schema: 1, generatedAt: '2026-09-19T12:00:00Z', summary: 'Not released', sources: {}, models: [{ id: 'syn', label: 'cis-syn', geometry: 'Research minimum', atoms: [{ id: '1:C5', element: 'C', position: [0, 0, 0], checks }, { id: '2:C5', element: 'C', position: [1.5, 0, 0], checks: [] }], bonds: [{ id: 'crosslink', atoms: ['1:C5', '2:C5'], checks }], checks: [{ label: 'DNA validation', state: 'pending' }] }] })
const settle = () => new Promise(resolve => setTimeout(resolve, 0))
afterEach(() => { document.querySelector('.modal__close')?.click(); document.body.replaceChildren() })
it('never paints missing evidence as solved, and distinguishes failure counts', () => {
  expect(elementStatus([], false)).toBe('unknown')
  expect(elementStatus(checks, true)).toBe('pending')
  expect(elementStatus(checks, false)).toBe('pass')
  expect(elementStatus([{ state: 'fail' }])).toBe('warning')
  expect(elementStatus([{ state: 'fail' }, { state: 'fail' }])).toBe('fail')
})
it('projects rotations and validates bond endpoints', () => {
  const atoms = fixture().models[0].atoms
  expect(projectAtoms(atoms)).toHaveLength(2)
  expect(projectAtoms(atoms, Math.PI / 2)[0].x).toBeCloseTo(330)
  expect(projectAtoms([])).toEqual([])
  const bad = fixture(); bad.models[0].bonds[0].atoms[1] = 'missing'
  expect(() => validateSnapshot(bad)).toThrow('Invalid bond endpoints')
})
it('renders structures, exposes bond details and shared pending checks, switches scope, closes', async () => {
  const modal = showCpdProgress({ load: async () => fixture() }); await settle()
  expect(document.querySelectorAll('[data-atom]')).toHaveLength(2)
  const bond = document.querySelector('[data-bond]'); bond.dispatchEvent(new Event('pointerenter'))
  expect(document.querySelector('.cpd-progress__details').textContent).toContain('Bond: crosslink')
  expect(document.querySelector('.cpd-progress__details').textContent).toContain('DNA validation')
  const scope = document.querySelector('[aria-label="Validation scope"]'); scope.value = 'local'; scope.dispatchEvent(new Event('change'))
  expect(document.querySelector('[data-bond]').getAttribute('stroke')).toBe('#35bd7c')
  modal.close(); expect(modal.isOpen()).toBe(false)
})
it('shows recoverable errors and ignores results after closing', async () => {
  let finish
  const modal = showCpdProgress({ load: () => new Promise(resolve => { finish = resolve }) })
  modal.close(); finish(fixture()); await settle(); expect(document.querySelector('[data-atom]')).toBeNull()
  const failed = showCpdProgress({ load: async () => { throw new Error('offline') } }); await settle()
  expect(document.body.textContent).toContain('offline'); expect(document.querySelector('.cpd-progress button').disabled).toBe(false); failed.close()
})
it('shows all eight isomers, both attachments, correct crosslinks, and preserves study checks', async () => {
  const data = catalog()
  const modal = showCpdProgress({ load: async () => data }); await settle()
  expect(document.querySelectorAll('[data-isomer]')).toHaveLength(8)
  const svg = document.querySelector('[aria-label="Interactive CPD atomic structure"]')
  const select = document.querySelector('[aria-label="Photoproduct structure"]')
  for (const model of data.isomers) {
    document.querySelector(`[data-isomer="${model.id}"]`).click()
    expect(select.value).toBe(model.id)
    expect(svg.querySelectorAll('[data-direction]')).toHaveLength(4)
    expect(svg.querySelectorAll('[data-backbone-bead]')).toHaveLength(2)
    expect(svg.querySelectorAll('[data-sugar]')).toHaveLength(2)
    expect([...svg.querySelectorAll('[data-crosslink]')].map(n => n.dataset.bond)).toEqual(model.bonds.filter(b => b.crosslink).map(b => b.id))
    expect(document.querySelector('.cpd-progress__details').textContent).toContain(model.qualification)
  }
  const slider = document.querySelector('[aria-label="Endpoint 1 sugar rotation"]')
  const before = svg.querySelector("[data-atom=\"1:O5'\"]").getAttribute('cx')
  slider.value = 90; slider.dispatchEvent(new Event('input'))
  expect(svg.querySelector("[data-atom=\"1:O5'\"]").getAttribute('cx')).not.toBe(before)
  document.querySelector('.cpd-progress__context input[type=checkbox]').click()
  expect(svg.querySelectorAll('[data-direction]')).toHaveLength(0)
  expect(svg.querySelectorAll('[data-crosslink]')).toHaveLength(2)
  select.value = 'syn-core-corrected'; select.dispatchEvent(new Event('change'))
  expect(svg.querySelectorAll('[data-atom]')).toHaveLength(36)
  expect(document.querySelector('[aria-label="Validation scope"]').disabled).toBe(false)
  modal.close()
})
it('rotates only the chosen backbone with its glycosidic bond and core fixed', () => {
  for (const model of catalog().isomers) {
    const original = new Map(model.atoms.map(a => [a.id, a.position]))
    const changed = contextAtoms(model, [95, 0])
    const map = new Map(changed.map(a => [a.id, a.position]))
    for (const a of changed) if (a.endpoint === 2 || a.region === 'base' || a.id === "1:C1'") {
      a.position.forEach((v, i) => expect(v).toBeCloseTo(original.get(a.id)[i], 9))
    }
    const length = (m, [a, b]) => Math.hypot(...m.get(a).map((v, i) => v - m.get(b)[i]))
    for (const bond of model.bonds) expect(length(map, bond.atoms)).toBeCloseTo(length(original, bond.atoms), 9)
    for (const d of attachmentDirections(changed)) expect(Math.hypot(...d.position.map((v, i) => v - map.get(d.anchor)[i]))).toBeCloseTo(2.4)
    expect(attachmentMetrics(changed).angle).toBeGreaterThanOrEqual(0)
    expect(attachmentMetrics(changed).angle).toBeLessThanOrEqual(180)
  }
})
it('rejects incomplete attachment context and duplicate identities before rendering', () => {
  const incomplete = catalog(); incomplete.isomers[0].atoms = incomplete.isomers[0].atoms.filter(a => a.id !== '1:P')
  incomplete.isomers[0].bonds = incomplete.isomers[0].bonds.filter(b => !b.atoms.includes('1:P'))
  expect(() => validateSnapshot(incomplete)).toThrow('Incomplete DNA attachment context')
  const duplicate = catalog(); duplicate.isomers.push(duplicate.isomers[0])
  expect(() => validateSnapshot(duplicate)).toThrow('Duplicate structure identity')
})
