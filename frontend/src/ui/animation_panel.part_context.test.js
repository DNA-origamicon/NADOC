import { afterEach, it, expect, vi } from 'vitest'
import { initAnimationPanel } from './animation_panel.js'

afterEach(() => { document.body.replaceChildren(); localStorage.clear() })

it('selecting a part is read-only; explicit New creates its first animation exactly once', async () => {
  document.body.innerHTML = `
    <section id="animation-panel"><button id="animation-panel-heading"></button>
      <div id="animation-panel-body"><select id="animation-select"></select>
        <button id="animation-new-btn"></button><div id="animation-kf-list"></div>
      </div>
    </section>`
  const state = { currentDesign: null, currentAssembly: null }
  const api = { ensureDefaultAnimation: vi.fn(), createAssemblyAnimation: vi.fn() }
  const panel = initAnimationPanel({ getState: () => state, subscribeSlice: vi.fn() }, {
    api, player: { stop: vi.fn(), isPlaying: () => false, setLoopMode: vi.fn() },
  })
  let design = { id: 'part-source', animations: [] }
  const patch = vi.fn(async modify => {
    design = structuredClone(design)
    modify(design)
    panel.setPartContext('a', design, patch)
  })
  panel.setPartContext('a', design, patch)
  panel.setPartContext('a', design, patch)
  await Promise.resolve()
  expect(patch).not.toHaveBeenCalled()
  expect(design.animations).toEqual([])
  expect(document.getElementById('animation-select').textContent).toContain('No animations')

  document.getElementById('animation-new-btn').click()
  await vi.waitFor(() => expect(patch).toHaveBeenCalledOnce())
  expect(design.animations).toHaveLength(1)
  expect(design.animations[0]).toMatchObject({ name: 'animation 1', keyframes: [], fps: 30, loop: false })
  expect(document.getElementById('animation-select').textContent).toBe('animation 1')
  expect(api.ensureDefaultAnimation).not.toHaveBeenCalled()
  expect(api.createAssemblyAnimation).not.toHaveBeenCalled()
})
