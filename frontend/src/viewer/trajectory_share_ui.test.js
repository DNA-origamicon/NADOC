import { it, expect, vi } from 'vitest'
import { mountTrajectoryShare, appendTrajectoryControls } from './trajectory_share_ui.js'
import { prepareTrajectory } from './prepare_trajectory.js'
vi.mock('./prepare_trajectory.js', () => ({ prepareTrajectory: vi.fn() }))

it('cancels preparation and rejects unsupported representation before capture', async () => {
  document.body.innerHTML = '<dialog><div data-links></div></dialog>'
  const source = { representation: 'surface' }
  const ui = mountTrajectoryShare({ dialog: document.querySelector('dialog'), getSource: () => source })
  await expect(ui.prepare()).rejects.toThrow('Choose Full')
  expect(prepareTrajectory).not.toHaveBeenCalled()
  source.representation = 'full'
  prepareTrajectory.mockImplementation(({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('Cancelled')))))
  const pending = ui.prepare()
  document.querySelector('[data-cancel-clip]').click()
  await expect(pending).rejects.toThrow('Cancelled')
  expect(document.querySelector('[data-cancel-clip]').disabled).toBe(true)
  ui.dispose(); expect(document.querySelector('fieldset')).toBeNull()
})
it('reopened host controls pause at the current server frame, not the original frame', async () => {
  document.body.innerHTML = '<section></section><p data-status></p>'
  const api = vi.fn(async (_, options) => options ? { trajectory: JSON.parse(options.body) } : { serverTime: 2500, trajectory: { frame: 0, at: 1000, playing: true, fps: 4 } })
  appendTrajectoryControls({ section: document.querySelector('section'), status: document.querySelector('[data-status]'), share: { id: 'room', trajectory: { id: 'clip', fps: 4, count: 20 } }, api })
  document.querySelector('[data-clip-pause]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toContain('sample 7'))
  expect(JSON.parse(api.mock.calls[1][1].body)).toMatchObject({ frame: 6, playing: false })
})
it('adds trajectory settings to one publish flow instead of creating a second link action', () => {
  document.body.innerHTML = '<dialog><div data-links></div></dialog>'
  const ui = mountTrajectoryShare({ dialog: document.querySelector('dialog'), getSource: () => ({}) })
  expect(ui.enabled).toBe(false)
  expect(document.querySelector('[data-clip-settings]').hidden).toBe(true)
  document.querySelector('[data-include-clip]').click()
  expect(ui.enabled).toBe(true)
  expect(document.querySelector('[data-clip-settings]').hidden).toBe(false)
  expect(document.querySelector('[data-create-clip]')).toBeNull()
  ui.setBusy(true); expect(document.querySelector('[data-include-clip]').disabled).toBe(true)
  ui.setBusy(false); expect(document.querySelector('[data-include-clip]').disabled).toBe(false)
  ui.dispose()
})
