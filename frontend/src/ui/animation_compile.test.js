import { afterEach, expect, it, vi } from 'vitest'
import { initAnimationCompile } from './animation_compile.js'
let ui
function setup(compile) {
  document.body.innerHTML = '<button id="start">Start Presentation</button>'
  const animation = { name: 'Talk', keyframes: [{ id: 'a' }, { id: 'b' }] }
  const player = { cancelBake: vi.fn() }
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
  URL.createObjectURL = vi.fn(() => 'blob:compiled')
  URL.revokeObjectURL = vi.fn()
  ui = initAnimationCompile({ anchor: document.getElementById('start'), player, getAnimation: () => animation, compile, library: { save: vi.fn(async () => ({ notice: 'Saved to presentation library.' })) } })
  return { animation, player }
}
afterEach(() => { ui?.dispose(); document.body.replaceChildren(); vi.restoreAllMocks() })
it('places compile below presentation, reports each clip, and offers the complete offline file', async () => {
  setup(async ({ onProgress }) => {
    onProgress({ phase: 'capture', index: 0, total: 2, name: 'A', done: 5, frames: 10 })
    expect(document.querySelector('[aria-label="Video 1 progress"]').value).toBe(.5)
    expect(document.querySelector('.compile-videos').textContent).toContain('5/10')
    return new Blob(['offline'])
  })
  expect(document.getElementById('start').nextElementSibling.className).toBe('animation-compile')
  await ui.start()
  expect(document.querySelector('.compile-result').hidden).toBe(false)
  expect(document.querySelector('a').download).toBe('Talk.html')
  expect(document.querySelector('.compile-summary').textContent).toContain('No server or Wi-Fi needed')
})
it('cancels in-flight preparation without publishing a partial file', async () => {
  let finish
  const { player } = setup(() => new Promise(resolve => { finish = resolve }))
  const pending = ui.start()
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  document.querySelector('.compile-cancel').click()
  finish(new Blob(['partial'])); await pending
  expect(player.cancelBake).toHaveBeenCalled()
  expect(document.querySelector('.compile-result').hidden).toBe(true)
  expect(document.querySelector('.compile-summary').textContent).toContain('cancelled')
  expect(document.getElementById('anim-compile-presentation-btn').disabled).toBe(false)
})
it('marks an earlier successful compilation stale after edits', async () => {
  const { animation } = setup(async () => new Blob(['ready']))
  await ui.start(); animation.keyframes.push({ id: 'c' }); ui.refresh()
  expect(document.querySelector('.compile-summary').textContent).toContain('previous version')
})

it('shares the icon and keeps the full presentation when compiling one trajectory', async () => {
  const compile = vi.fn(async () => new Blob(['ready']))
  const { animation } = setup(compile)
  animation.keyframes[1].trajectory_job_id = 'md'
  await ui.start()
  const full = document.querySelector('.compile-download').href
  const button = ui.keyframeButton(animation.keyframes[1])
  expect(button.querySelector('svg').outerHTML).toBe(document.querySelector('#anim-compile-presentation-btn svg').outerHTML)
  await ui.start('b')
  expect(compile.mock.calls[1][0].keyframeId).toBe('b')
  expect(document.querySelector('.compile-download').href).toBe(full)
  expect(document.querySelector('.compile-result').hidden).toBe(false)
  expect(document.querySelector('.compile-preview-result')).toBeNull()
  expect(document.querySelector('.compile-summary').textContent).not.toContain('Keyframe ready')
  expect(ui.keyframeButton({ id: 'empty' }).disabled).toBe(true)
})
