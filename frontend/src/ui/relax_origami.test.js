import { afterEach, expect, it, vi } from 'vitest'
import { showRelaxOrigami } from './relax_origami.js'
let modal
afterEach(() => { modal?.close(); document.body.replaceChildren() })
it('runs the minimizer, prevents duplicate runs, and reports residual stretch', async () => {
  let finish
  const api = { relaxOrigami: vi.fn(() => new Promise(resolve => { finish = resolve })) }
  modal = showRelaxOrigami({ api })
  const button = modal.root.querySelector('.modal__body button') || [...modal.root.querySelectorAll('button')].find(b => b.textContent === 'Relax current design')
  button.click(); button.click()
  expect(api.relaxOrigami).toHaveBeenCalledTimes(1)
  expect(button.disabled).toBe(true)
  finish({ before: { max_excess_nm: 10 }, after: { max_excess_nm: .3, stretched_bonds: 2 }, optimizer_converged: false, clashes: { before: { overlapping_body_pairs: 6 }, after: { overlapping_body_pairs: 0 } } })
  await vi.waitFor(() => expect(button.disabled).toBe(false))
  expect(modal.root.textContent).toContain('10.00 → 0.30 nm')
  expect(modal.root.textContent).toContain('2 inter-cluster bonds remain stretched')
  expect(modal.root.textContent).toContain('Overlapping body envelopes: 6 → 0')
  expect(modal.root.textContent).toContain('optimizer did not converge')
})
it('shows a failed request without claiming a pose was applied', async () => {
  modal = showRelaxOrigami({ api: { relaxOrigami: async () => { throw new Error('Design changed') } } })
  ;[...modal.root.querySelectorAll('button')].find(b => b.textContent === 'Relax current design').click()
  await vi.waitFor(() => expect(modal.root.textContent).toContain('Design changed'))
})
