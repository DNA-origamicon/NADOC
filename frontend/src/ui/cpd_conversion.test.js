import { beforeEach, expect, it, vi } from 'vitest'
import { showCpdConversion } from './cpd_conversion.js'
const viewer = vi.hoisted(() => ({ setData: vi.fn(), setBefore: vi.fn(), dispose: vi.fn() }))
vi.mock('./cpd_context_preview.js', () => ({ createCpdContextPreview: () => viewer }))
beforeEach(() => { document.body.replaceChildren(); vi.clearAllMocks() })
const template = { positions: [[0, 0, 0], [.15, 0, 0]], relationship: 'different strands', revision: 17,
  glycosidic_distances_nm: [.15, .16], qualification: 'Backbone fixed' }
const apiFor = () => ({
  getCpdConversionOptions: vi.fn().mockResolvedValue({ products: [
    { label: 'cis-syn-I', stereochemistry: 'cis-syn' },
    { label: 'trans-syn-I', stereochemistry: 'trans-syn-I' },
  ] }), previewCpdConversion: vi.fn().mockResolvedValue(template), convertThyminesToCpd: vi.fn().mockResolvedValue({ design: {} }),
})
it('previews the selected context and commits the captured pair and preview revision', async () => {
  const api = apiFor(), keys = ['__xb__:a:0', 'h:2:FORWARD']
  const modal = await showCpdConversion({ api, baseKeys: keys })
  expect(viewer.setData).toHaveBeenCalledWith(template)
  expect(document.querySelectorAll('option')[1].disabled).toBe(false)
  expect(document.body.textContent).toContain('Different strands')
  keys.pop()
  const select = document.querySelector('select'); select.value = 'trans-syn-I'; select.dispatchEvent(new Event('change'))
  await vi.waitFor(() => expect(api.previewCpdConversion).toHaveBeenLastCalledWith(['__xb__:a:0', 'h:2:FORWARD'], 'trans-syn-I', 17))
  await vi.waitFor(() => expect(document.querySelector('.primary-btn').disabled).toBe(false))
  document.querySelector('.primary-btn').click()
  await vi.waitFor(() => expect(modal.isOpen()).toBe(false))
  expect(api.convertThyminesToCpd).toHaveBeenCalledWith(['__xb__:a:0', 'h:2:FORWARD'], 'trans-syn-I', 17)
  expect(viewer.dispose).toHaveBeenCalled()
})
it('leaves conversion disabled if contextual preview fails', async () => {
  const api = apiFor(); api.previewCpdConversion.mockRejectedValue(new Error('Design changed'))
  const modal = await showCpdConversion({ api, baseKeys: [] })
  expect(document.querySelector('.primary-btn').disabled).toBe(true)
  expect(document.body.textContent).toContain('Design changed')
  modal.close()
})
it('keeps the dialog open when conversion is rejected', async () => {
  const api = apiFor(); api.convertThyminesToCpd.mockResolvedValue(null)
  const modal = await showCpdConversion({ api, baseKeys: [] })
  document.querySelector('.primary-btn').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Conversion failed'))
  expect(modal.isOpen()).toBe(true)
  modal.close()
})
it('discards an older isomer preview that arrives late', async () => {
  const api = apiFor()
  const modal = await showCpdConversion({ api, baseKeys: ['a', 'b'] })
  let finish
  api.previewCpdConversion.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const select = document.querySelector('select')
  select.value = 'trans-syn-I'; select.dispatchEvent(new Event('change'))
  select.value = 'cis-syn'; select.dispatchEvent(new Event('change'))
  await vi.waitFor(() => expect(document.querySelector('.primary-btn').disabled).toBe(false))
  finish({ ...template, relationship: 'same strand' })
  await Promise.resolve()
  expect(document.body.textContent).toContain('Different strands')
  modal.close()
})

it('requires a fresh preview after a stale commit instead of reusing old coordinates', async () => {
  const api = apiFor()
  api.convertThyminesToCpd.mockRejectedValueOnce(new Error('Design changed'))
  const modal = await showCpdConversion({ api, baseKeys: ['a', 'b'] })
  document.querySelector('.primary-btn').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Refresh the preview'))
  expect(document.querySelector('.primary-btn').disabled).toBe(true)
  api.previewCpdConversion.mockResolvedValue({ ...template, revision: 18 })
  ;[...document.querySelectorAll('button')].find(b => b.textContent === 'Refresh preview').click()
  await vi.waitFor(() => expect(document.querySelector('.primary-btn').disabled).toBe(false))
  document.querySelector('.primary-btn').click()
  await vi.waitFor(() => expect(modal.isOpen()).toBe(false))
  expect(api.convertThyminesToCpd).toHaveBeenLastCalledWith(['a', 'b'], 'cis-syn', 18)
})
