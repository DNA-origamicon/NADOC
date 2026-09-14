import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('../api/client.js', () => ({ patchNanoparticle: vi.fn(), createNanoparticleBiotinDNA: vi.fn(), removeNanoparticleBiotinDNA: vi.fn() }))
import { patchNanoparticle } from '../api/client.js'
import { openStreptavidinDialog } from './streptavidin_dialog.js'
beforeEach(() => { document.body.innerHTML = ''; vi.clearAllMocks(); HTMLDialogElement.prototype.showModal = function () { this.open = true } })
const change = (id, value, event = 'change') => { const e = document.getElementById(id); e.value = value; e.dispatchEvent(new Event(event)) }
it('uses publication counts, records an override and resets to the publication', async () => {
  const container = document.createElement('div'); document.body.append(container)
  patchNanoparticle.mockResolvedValue({})
  const saved = vi.fn()
  openStreptavidinDialog({ id: 'gold', diameter_nm: 10 }, { container, onSaved: saved })
  change('strep-reference', 'gurtovenko_2019')
  expect(document.getElementById('strep-count').value).toBe('6')
  change('strep-count', '4', 'input')
  document.getElementById('strep-apply').click()
  await vi.waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(patchNanoparticle.mock.calls[0][1].coating).toMatchObject({ coverage_reference: 'gurtovenko_2019', count_override: 4 })
  openStreptavidinDialog({ id: 'gold', diameter_nm: 10 }, { container })
  change('strep-count', '1.5', 'input')
  expect(document.getElementById('strep-apply').disabled).toBe(true)
  document.getElementById('strep-reset').click()
  expect(document.getElementById('strep-count').value).toBe('7')
  document.getElementById('strep-apply').click()
  expect(patchNanoparticle.mock.calls[1][1].coating.count_override).toBeNull()
})
