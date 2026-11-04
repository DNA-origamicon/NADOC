import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { showScaffoldRegister } from './scaffold_register.js'

let modal
const candidate = { cut_index: 5, q: -.2, delta_q: .1, helix_id: 'h0', bp: 14, direction: 'FORWARD' }
const data = { best: candidate, current: { ...candidate, cut_index: 0, q: -.3, delta_q: 0 }, top: [candidate],
  scores: [{ cut_index: 0, q: -.3 }, { cut_index: 5, q: -.2 }], candidate_count: 126, scaffold_nt: 128,
  staple_count: 4, elapsed_seconds: .02, conditions: {}, revision: 1, design_id: 'd', doc_id: 'doc' }
const button = label => [...document.querySelectorAll('button')].find(b => b.textContent === label)
beforeEach(() => { vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null) })
afterEach(() => { modal?.close(); document.body.replaceChildren(); vi.restoreAllMocks() })

it('evaluates, displays scores, and applies the selected start with its source context', async () => {
  const api = { sweepScaffoldRegister: vi.fn().mockResolvedValue(data), applyScaffoldRegister: vi.fn().mockResolvedValue({ design: {} }) }
  modal = showScaffoldRegister({ api })
  expect(document.body.textContent).toContain('not a physical break')
  expect(button('Apply selected start').disabled).toBe(true)
  button('Evaluate all starts').click()
  await vi.waitFor(() => expect(button('Apply selected start').disabled).toBe(false))
  expect(api.sweepScaffoldRegister).toHaveBeenCalledWith({ temperature_c: 50, scaffold_nM: 10, staple_nM: 100, magnesium_mM: 12.5, tris_mM: 40 })
  expect(document.body.textContent).toContain('126 eligible starts')
  button('Apply selected start').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Undo restores'))
  expect(api.applyScaffoldRegister).toHaveBeenCalledWith(data, 5)
  expect(button('Apply selected start').disabled).toBe(true)
})

it('invalidates evaluated results when conditions change', async () => {
  const api = { sweepScaffoldRegister: vi.fn().mockResolvedValue(data) }
  modal = showScaffoldRegister({ api })
  button('Evaluate all starts').click()
  await vi.waitFor(() => expect(button('Apply selected start').disabled).toBe(false))
  const temperature = document.querySelector('input')
  temperature.value = '60'; temperature.dispatchEvent(new Event('input'))
  expect(button('Apply selected start').disabled).toBe(true)
})

it('reports unsupported designs without enabling apply', async () => {
  modal = showScaffoldRegister({ api: { sweepScaffoldRegister: vi.fn().mockResolvedValue(null), lastErrorMessage: () => 'Model the full scaffold.' } })
  button('Evaluate all starts').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Model the full scaffold.'))
  expect(button('Apply selected start').disabled).toBe(true)
})
