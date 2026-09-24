import { beforeEach, expect, it, vi } from 'vitest'
import { showCpdConversion } from './cpd_conversion.js'
beforeEach(() => { document.body.replaceChildren() })
const template = { positions: [[0, 0, 0], [0.15, 0, 0]], atom_keys: ['1:C5', '2:C5'], bonds: [[0, 1]], qualification: 'Preliminary test template' }
const apiFor = () => ({
  getPhotoproductCatalog: vi.fn().mockResolvedValue({ products: [
    { product: 'TT-CPD', label: 'cis-syn', stereochemistry: 'cis-syn', simulation_supported: true },
    { product: 'TT-CPD', label: 'trans-syn-I', stereochemistry: 'trans-syn-I' },
  ] }), getCpdDesignTemplate: vi.fn().mockResolvedValue(template), convertExtraBasesToCpd: vi.fn().mockResolvedValue({ design: {} }),
})
it('previews the real template, disables development types and converts the captured pair', async () => {
  const api = apiFor(), keys = ['__xb__:a:0', '__xb__:b:0']
  const modal = await showCpdConversion({ api, baseKeys: keys })
  expect(document.querySelectorAll('svg circle')).toHaveLength(2)
  expect(document.querySelectorAll('option')[1].disabled).toBe(true)
  expect(document.body.textContent).toContain('In development')
  keys.pop()
  document.querySelector('.primary-btn').click()
  await vi.waitFor(() => expect(modal.isOpen()).toBe(false))
  expect(api.convertExtraBasesToCpd).toHaveBeenCalledWith(['__xb__:a:0', '__xb__:b:0'], 'cis-syn')
})
it('leaves conversion disabled if the template fails to load', async () => {
  const api = apiFor(); api.getCpdDesignTemplate.mockRejectedValue(new Error('Offline'))
  const modal = await showCpdConversion({ api, baseKeys: [] })
  expect(document.querySelector('.primary-btn').disabled).toBe(true)
  expect(document.body.textContent).toContain('Offline')
  modal.close()
})
it('keeps the dialog open when conversion is rejected', async () => {
  const api = apiFor(); api.convertExtraBasesToCpd.mockResolvedValue(null)
  const modal = await showCpdConversion({ api, baseKeys: [] })
  document.querySelector('.primary-btn').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Conversion failed'))
  expect(modal.isOpen()).toBe(true)
  modal.close()
})
