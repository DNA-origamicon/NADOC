import { afterEach, expect, it } from 'vitest'
import { chooseOrigamiImportOptions, importRelaxationMessage } from './import_origami_options.js'
afterEach(() => document.body.replaceChildren())
it('defaults to ordinary import and allows opting in', async () => {
  let result = chooseOrigamiImportOptions()
  let modal = document.querySelector('.origami-import-options')
  expect(modal.querySelector('input').checked).toBe(false)
  modal.querySelector('.modal__body button').click()
  expect(await result).toEqual({ relaxOrigami: false })
  result = chooseOrigamiImportOptions()
  modal = document.querySelector('.origami-import-options')
  modal.querySelector('input').checked = true
  modal.querySelector('.modal__body button').click()
  expect(await result).toEqual({ relaxOrigami: true })
})
it('cancels without choosing import options', async () => {
  const result = chooseOrigamiImportOptions()
  document.querySelector('.origami-import-options .modal__close').click()
  expect(await result).toBeNull()
})
it('reports partial fits accurately', () => {
  expect(importRelaxationMessage({ status: 'skipped' })).toBeNull()
  expect(importRelaxationMessage({ status: 'applied', rigid_bundle_sizes: [22, 22, 22, 22],
    before: { max_excess_nm: 10 }, after: { max_excess_nm: 12 }, optimizer_converged: false }))
    .toContain('10.00 → 12.00 nm. Partial fit')
})
