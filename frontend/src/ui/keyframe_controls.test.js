import { afterEach, expect, it, vi } from 'vitest'
import { initKeyframeControls } from './keyframe_controls.js'

let controls
function setup() {
  document.body.innerHTML = '<div data-kf-id="b"><div><span style="flex:1"></span><button title="Delete keyframe">×</button></div><input class="body"></div>'
  const row = document.body.firstChild
  let time = 0
  document.body.insertAdjacentHTML('beforeend', '<div id="canvas-area"><canvas></canvas></div>')
  const player = { stop: vi.fn(), play: vi.fn(async () => {}), pause: vi.fn(), seekTo: vi.fn(t => { time = t }),
    settleFrame: vi.fn(async () => true), getCurrentTime: () => time, getKeyframeRange: () => ({ start: 2, end: 4 }) }
  const save = vi.fn(async () => {})
  const animation = { keyframes: ['a', 'b', 'future'].map(id => ({ id, transition_duration_s: 1, hold_duration_s: 1 })) }
  controls = initKeyframeControls({ player, getAnimation: () => animation,
    getAnnotations: () => [{ id: 'one', name: 'Opening' }, { id: 'two', name: 'Closing' }],
    getViewVolumes: () => [{ id: 'v', name: 'Detail' }], getZoomVolumes: () => [{ id: 'z', name: 'Inset' }],
    stopPreview: vi.fn(), save, onError: error => { throw error } })
  controls.decorate(row, animation.keyframes[1], 1, [])
  return { row, player, save }
}
afterEach(() => { controls?.dispose(); vi.restoreAllMocks(); document.body.replaceChildren() })
it('collapses controls while keeping selectable title, preview and delete in the header', async () => {
  const { row, player } = setup()
  row.querySelector('[title="Collapse keyframe"]').click()
  expect(row.classList.contains('is-collapsed')).toBe(true)
  expect(row.firstChild.querySelector('[title="Delete keyframe"]')).toBeTruthy()
  row.querySelector('.anim-keyframe-title').click()
  await vi.waitFor(() => expect(player.seekTo).toHaveBeenLastCalledWith(4))
  expect(row.classList.contains('is-selected')).toBe(true)
  expect(player.play.mock.calls[0][0].keyframes.map(k => k.id)).toEqual(['a', 'b'])
})
it('previews only the selected interval and settles at its end', async () => {
  let tick
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(fn => { tick = fn; return 1 })
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
  vi.spyOn(performance, 'now').mockReturnValue(0)
  const { row, player } = setup()
  row.querySelector('[title="Preview keyframe"]').click()
  await vi.waitFor(() => expect(tick).toBeTypeOf('function'))
  expect(player.seekTo.mock.calls[0][0]).toBeCloseTo(2)
  await tick(2000)
  expect(player.seekTo).toHaveBeenLastCalledWith(4)
})
it('checkbox menu saves any subset, all, and none', async () => {
  const { row, save } = setup()
  const details = row.querySelector('details'); details.open = true; details.dispatchEvent(new Event('toggle'))
  const choices = details.querySelectorAll('input')
  expect(choices).toHaveLength(2)
  choices[0].click()
  await vi.waitFor(() => expect(save).toHaveBeenLastCalledWith(expect.anything(), { annotation_ids: ['two'] }))
  await Promise.resolve()
  const buttons = [...details.querySelectorAll('button')]
  buttons.find(b => b.textContent === 'None').click()
  await vi.waitFor(() => expect(save).toHaveBeenLastCalledWith(expect.anything(), { annotation_ids: [] }))
  await Promise.resolve()
  ;[...details.querySelectorAll('button')].find(b => b.textContent === 'All').click()
  await vi.waitFor(() => expect(save).toHaveBeenLastCalledWith(expect.anything(), { annotation_ids: ['one', 'two'] }))
})

it('does not seek after another playback cancels an unfinished preparation', async () => {
  const { player } = setup()
  let ready
  player.play.mockImplementation(() => new Promise(resolve => { ready = resolve }))
  const pending = controls.show('b', false)
  controls.onPlayerEvent({ type: 'stopped' })
  ready()
  await pending
  expect(player.seekTo).not.toHaveBeenCalled()
})

it('returns the viewport to editing when a selected keyframe is dismissed by a 3D click', async () => {
  const { row, player } = setup()
  await controls.show('b', false)
  expect(row.classList.contains('is-selected')).toBe(true)
  document.querySelector('canvas').dispatchEvent(new Event('pointerdown', { bubbles: true }))
  expect(row.classList.contains('is-selected')).toBe(false)
  expect(player.stop).toHaveBeenCalledOnce()
  document.querySelector('canvas').dispatchEvent(new Event('pointerdown', { bubbles: true }))
  expect(player.stop).toHaveBeenCalledOnce()
})

it.each([['view_volume_ids', 'v'], ['zoom_volume_ids', 'z']])('saves independent %s selections with the annotation controls', async (field, id) => {
  const { row, save } = setup()
  const picker = row.querySelector(`[data-field="${field}"]`)
  picker.open = true; picker.dispatchEvent(new Event('toggle'))
  picker.querySelector('input').click()
  await vi.waitFor(() => expect(save).toHaveBeenLastCalledWith(expect.anything(), { [field]: [] }))
  await Promise.resolve()
  ;[...picker.querySelectorAll('button')].find(b => b.textContent === 'All').click()
  await vi.waitFor(() => expect(save).toHaveBeenLastCalledWith(expect.anything(), { [field]: [id] }))
})
