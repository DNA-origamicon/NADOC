import { afterEach, expect, it } from 'vitest'
import { showCpdProgress } from './cpd_progress.js'
import { elementStatus, projectAtoms, validateSnapshot } from './cpd_progress_model.js'

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
