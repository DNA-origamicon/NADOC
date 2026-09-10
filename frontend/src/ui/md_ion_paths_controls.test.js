// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { initMdIonPathsControls } from './md_ion_paths_controls.js'

function setup(request = vi.fn().mockResolvedValue({ crossings: 2, frames: 30, paths: [] }), display = null, apiExtra = {}) {
  document.body.innerHTML = `<label><input id="md-ion-paths-toggle" type="radio" disabled></label><div id="md-ion-paths-options"></div><progress id="md-ion-paths-progress" max="100" hidden></progress><div id="md-ion-paths-status"></div><input id="md-ion-paths-before" value="3"><input id="md-ion-paths-after" value="5"><input id="md-ion-paths-width" value="2"><input id="md-ion-paths-percentage" type="range" min="0" max="100" value="100"><output id="md-ion-paths-percentage-label"></output><button id="md-ion-paths-retry">Reload</button>`
  const overlay = { clear: vi.fn(), setData: vi.fn(), setWidth: vi.fn(), setPercentage: vi.fn(value => ({ percentage: value, shown: Math.round(2 * value / 100), total: 2 })) }
  const activate = vi.fn()
  const controls = initMdIonPathsControls({ api: { getMdIonPaths: request, ...apiExtra }, getDisplay: () => display, getOverlay: () => overlay, getJobId: () => 'P1', activate })
  const toggle = document.getElementById('md-ion-paths-toggle')
  const start = () => { controls.setEnabled(true); toggle.checked = true; toggle.dispatchEvent(new Event('change')) }
  return { controls, overlay, request, activate, toggle, start }
}
const tick = () => new Promise(resolve => setTimeout(resolve, 15))
describe('nanopore ion path controls', () => {
  it('loads asymmetric windows and changes thickness without fetching', async () => {
    const s = setup(); s.start(); await tick()
    expect(s.request).toHaveBeenCalledWith('P1', 3, 5, expect.any(AbortSignal), expect.objectContaining({ requestId: expect.any(String), onProgress: expect.any(Function) }))
    expect(s.overlay.setData).toHaveBeenCalledOnce()
    const width = document.getElementById('md-ion-paths-width'); width.value = '6'; width.dispatchEvent(new Event('input'))
    expect(s.overlay.setWidth).toHaveBeenLastCalledWith('6')
    expect(s.request).toHaveBeenCalledOnce()
    s.controls.setEnabled(false)
    expect(s.toggle.disabled).toBe(true)
    expect(s.controls.isActive()).toBe(false)
  })
  it('updates path percentage without fetching or rebuilding the scene', async () => {
    const s = setup(); s.start(); await tick()
    const slider = document.getElementById('md-ion-paths-percentage')
    slider.value = '50'; slider.dispatchEvent(new Event('input'))
    expect(s.overlay.setPercentage).toHaveBeenLastCalledWith(50)
    expect(document.getElementById('md-ion-paths-percentage-label').textContent).toBe('50% · 1 / 2 paths')
    expect(s.request).toHaveBeenCalledOnce()
    expect(s.overlay.setData).toHaveBeenCalledOnce()
    slider.value = '0'; slider.dispatchEvent(new Event('input'))
    expect(s.overlay.setPercentage).toHaveBeenLastCalledWith(0)
  })
  it('accepts 200 and much larger windows without clamping to 1000', async () => {
    const s = setup()
    document.getElementById('md-ion-paths-before').value = '10000'
    document.getElementById('md-ion-paths-after').value = '200'
    s.start(); await tick()
    expect(s.request).toHaveBeenCalledWith('P1', 10000, 200, expect.any(AbortSignal), expect.objectContaining({ requestId: expect.any(String), onProgress: expect.any(Function) }))
  })
  it.each([null, new Error('Trajectory download failed')])('keeps the scene and controls available after a failed reload: %s', async failure => {
    const s = setup(); s.start(); await tick()
    s.overlay.clear.mockClear()
    if (failure) s.request.mockRejectedValueOnce(failure)
    else s.request.mockResolvedValueOnce(null)
    const after = document.getElementById('md-ion-paths-after')
    after.value = '200'; after.dispatchEvent(new Event('change')); await tick()
    expect(s.toggle.checked).toBe(true)
    expect(s.controls.isActive()).toBe(true)
    expect(document.getElementById('md-ion-paths-options').style.display).toBe('block')
    expect(s.overlay.clear).not.toHaveBeenCalled()
    expect(s.overlay.setData).toHaveBeenCalledOnce()
    expect(document.getElementById('md-ion-paths-status').textContent).not.toContain('Cannot read')
    document.getElementById('md-ion-paths-retry').click(); await tick()
    expect(s.overlay.setData).toHaveBeenCalledTimes(2)
  })
  it('discards a response after leaving the mode', async () => {
    let resolve
    const s = setup(vi.fn(() => new Promise(r => { resolve = r })))
    s.start(); s.controls.off(); resolve({ crossings: 1, frames: 2, paths: [] }); await tick()
    expect(s.overlay.setData).not.toHaveBeenCalled()
  })
  it('reports an empty trajectory honestly', async () => {
    const s = setup(vi.fn().mockResolvedValue({ crossings: 0, frames: 10, paths: [] }))
    s.start(); await tick()
    expect(document.getElementById('md-ion-paths-status').textContent).toContain('No ions crossed')
  })
})

it('waits for the shared average and representation, resets on edits and restores on exit', async () => {
  let finish
  const data = { paths: [], frames: 100, crossings: 1, origami: { n_frames: 100, display_rmsf: { ready: true } } }
  const display = { displayRmsf: vi.fn(() => new Promise(r => { finish = r })),
    reapplyForRepr: vi.fn().mockResolvedValue(), stopAndRestore: vi.fn() }
  const s = setup(vi.fn().mockResolvedValue(data), display)
  s.start(); await tick()
  const bar = document.getElementById('md-ion-paths-progress')
  expect(bar.value).toBe(85)
  expect(display.displayRmsf).toHaveBeenCalledWith('P1', { response: data.origami.display_rmsf, representations: data.origami, awaitHeavy: true })
  await s.controls.reapplyRepresentation() // changed while first representation is loading
  finish({ ok: true }); await tick()
  expect(display.reapplyForRepr).toHaveBeenCalledOnce()
  expect(bar.value).toBe(100)
  await s.controls.reapplyRepresentation()
  expect(display.reapplyForRepr).toHaveBeenCalledTimes(2)
  expect(s.request).toHaveBeenCalledOnce()
  document.getElementById('md-ion-paths-after').dispatchEvent(new Event('change'))
  expect(bar.value).toBe(0)
  await tick(); s.controls.off(); finish({ ok: true }); await tick()
  expect(display.stopAndRestore).toHaveBeenCalledOnce()
  expect(bar.hidden).toBe(true)
  expect(document.getElementById('md-ion-paths-status').textContent).toBe('')
})
