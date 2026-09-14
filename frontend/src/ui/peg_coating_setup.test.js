import { beforeEach, expect, it, vi } from 'vitest'
import { initPegCoatingSetup } from './peg_coating_setup.js'

let reviewSetup, surface, coating
beforeEach(() => {
  document.body.innerHTML = `<div id="oxdna-floor-body"><div id="oxdna-peg-controls">
    <input id="segments" type="number" min="2" max="64" value="8">
    <button id="oxdna-peg-review"></button><div id="oxdna-peg-review-result"></div>
    </div></div>`
  surface = { enabled: true, dir: [0, 1, 0], positionNm: -7, offsetNm: 7, stiff: 100 }
  coating = { enabled: true, material: 'PEG', segments: 8, seed: 17, count: 4, built: {} }
  reviewSetup = vi.fn().mockResolvedValue({ summary: { requested_chains: 4, requested_beads: 36 },
    barriers: [{ message: 'Calibration incomplete.' }] })
  initPegCoatingSetup({ reviewSetup, getSurface: () => surface, getCoating: () => coating })
})
const button = () => document.getElementById('oxdna-peg-review')
const result = () => document.getElementById('oxdna-peg-review-result').textContent

it('reviews a request fragment and renders remaining barriers', async () => {
  button().click()
  await vi.waitFor(() => expect(result()).toContain('36 beads'))
  const body = reviewSetup.mock.calls[0][0]
  expect(body.surface).toEqual({ dir: [0, 1, 0], position_nm: -7, offset_nm: 7, stiff: 100 })
  expect(body.surface_strands).not.toHaveProperty('built')
  expect(body.surface_strands).not.toHaveProperty('count')
  expect(result()).toContain('No job created.')
  expect(result()).toContain('Calibration incomplete.')
})

it('rejects invalid raw input before the preview can silently clamp it', () => {
  document.getElementById('segments').value = '65'
  button().click()
  expect(reviewSetup).not.toHaveBeenCalled()
  expect(result()).toContain('Enter valid values')
})

it('requires the surface and coating', () => {
  surface.enabled = false
  button().click()
  expect(reviewSetup).not.toHaveBeenCalled()
  expect(result()).toContain('Enable the hard surface')
})

it('discards a response after the user edits and allows retry', async () => {
  let resolve
  reviewSetup.mockReturnValue(new Promise(r => { resolve = r }))
  button().click()
  expect(button().disabled).toBe(true)
  document.getElementById('segments').dispatchEvent(new Event('input', { bubbles: true }))
  resolve({ summary: { requested_chains: 4, requested_beads: 36 }, barriers: [] })
  await vi.waitFor(() => expect(button().disabled).toBe(false))
  expect(result()).toBe('')
})

it('shows failed requests and re-enables review', async () => {
  reviewSetup.mockRejectedValue(new Error('Network unavailable'))
  button().click()
  await vi.waitFor(() => expect(result()).toBe('Network unavailable'))
  expect(button().disabled).toBe(false)
})
