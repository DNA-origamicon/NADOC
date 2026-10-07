import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { instancesInRect, initAssemblyLasso, toggleInstanceSelection } from './assembly_lasso.js'

function camera() {
  const cam = new THREE.PerspectiveCamera(50, 1, 0.1, 100)
  cam.position.set(0, 0, 10)
  cam.lookAt(0, 0, 0)
  cam.updateMatrixWorld(); cam.updateProjectionMatrix()
  return cam
}
const size = { width: 200, height: 200 }
const at = (id, c, s = { x: 1, y: 1, z: 1 }) => ({ id, center: { x: c[0], y: c[1], z: c[2] }, size: s })

describe('instancesInRect', () => {
  it('selects a part fully inside the rect', () => {
    expect(instancesInRect([at('a', [0, 0, 0])], camera(), size, 0, 0, 200, 200)).toEqual(['a'])
  })
  it('excludes a part outside the rect', () => {
    // origin projects to ~screen-centre (100,100); a tiny top-left rect misses it.
    expect(instancesInRect([at('a', [0, 0, 0])], camera(), size, 0, 0, 5, 5)).toEqual([])
  })
  it('skips parts with no size and parts behind the camera', () => {
    expect(instancesInRect([{ id: 'a', center: { x: 0, y: 0, z: 0 } }], camera(), size, 0, 0, 200, 200)).toEqual([])
    expect(instancesInRect([at('z', [0, 0, 100])], camera(), size, 0, 0, 200, 200)).toEqual([]) // behind cam
  })
})

describe('toggleInstanceSelection (Ctrl+click semantics — ISSUE-3)', () => {
  it('adds a pick to an empty selection (3a)', () => {
    expect(toggleInstanceSelection([], null, 'a')).toEqual(['a'])
    expect(toggleInstanceSelection(undefined, undefined, 'a')).toEqual(['a'])
  })
  it('folds the prior single (active) pick in so a 2nd Ctrl+click selects BOTH (decision 1 / 3c)', () => {
    expect(toggleInstanceSelection([], 'a', 'b').sort()).toEqual(['a', 'b'])
  })
  it('removes a part already in the multi-set (decision 2)', () => {
    expect(toggleInstanceSelection(['a', 'b'], null, 'b')).toEqual(['a'])
  })
  it('Ctrl+click the only (active) selected part toggles it off → empty (3b)', () => {
    expect(toggleInstanceSelection([], 'a', 'a')).toEqual([])
  })
  it('removing the active part when others are multi-selected keeps the rest', () => {
    expect(toggleInstanceSelection(['b'], 'a', 'a')).toEqual(['b'])
  })
  it('does not duplicate when the active part is also in the multi-set', () => {
    expect(toggleInstanceSelection(['a'], 'a', 'b').sort()).toEqual(['a', 'b'])
  })
})

describe('initAssemblyLasso', () => {
  function setup() {
    const handlers = {}
    const canvas = {
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 200 }),
      addEventListener: (t, h) => { handlers[t] = h },
      removeEventListener: (t) => { delete handlers[t] },
    }
    const controls = { enabled: true }
    const onSelect = vi.fn()
    const lasso = initAssemblyLasso({
      canvas, camera: camera(), controls,
      getInstanceCenters: () => [at('a', [0, 0, 0])],
      onSelect,
    })
    return { lasso, controls, onSelect, handlers }
  }

  it('start() ignores navigation buttons', () => {
    const { lasso, controls } = setup()
    expect(lasso.start({ button: 2, clientX: 10, clientY: 10 })).toBe(false)
    expect(controls.enabled).toBe(true)
  })

  it('Left-drag selects the contained instances on pointerup', () => {
    const { lasso, controls, onSelect, handlers } = setup()
    expect(lasso.start({ button: 0, shiftKey: false, clientX: 5, clientY: 5 })).toBe(true)
    expect(controls.enabled).toBe(true)            // selection does not own navigation controls
    handlers.pointerup({ clientX: 195, clientY: 195 }) // big rect → contains origin part
    expect(onSelect).toHaveBeenCalledWith(['a'], false)
    expect(controls.enabled).toBe(true)             // re-enabled after finalize
  })

  it('a tiny drag is treated as a click (no selection)', () => {
    const { lasso, onSelect, handlers } = setup()
    lasso.start({ ctrlKey: true, clientX: 50, clientY: 50 })
    handlers.pointerup({ clientX: 52, clientY: 52 }) // <4px
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('shift makes the selection additive', () => {
    const { lasso, onSelect, handlers } = setup()
    lasso.start({ button: 0, shiftKey: true, clientX: 5, clientY: 5 })
    handlers.pointerup({ clientX: 195, clientY: 195 })
    expect(onSelect).toHaveBeenCalledWith(['a'], true)
  })

  it('cancel() aborts an in-flight drag and re-enables controls', () => {
    const { lasso, controls } = setup()
    lasso.start({ ctrlKey: true, clientX: 5, clientY: 5 })
    lasso.cancel()
    expect(controls.enabled).toBe(true)
  })
})

describe('initAssemblyLasso — Ctrl-click toggle + Esc-cancel (new UX)', () => {
  function setup() {
    const handlers = {}
    const canvas = {
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 200 }),
      addEventListener: (t, h) => { handlers[t] = h },
      removeEventListener: (t) => { delete handlers[t] },
    }
    const controls = { enabled: true }
    const onSelect = vi.fn(); const onClick = vi.fn()
    const lasso = initAssemblyLasso({
      canvas, camera: camera(), controls,
      getInstanceCenters: () => [at('a', [0, 0, 0])], onSelect, onClick,
    })
    return { lasso, controls, onSelect, onClick, handlers }
  }

  it('a tiny Ctrl-drag fires onClick (toggle), not onSelect', () => {
    const { lasso, onSelect, onClick, handlers } = setup()
    lasso.start({ ctrlKey: true, clientX: 50, clientY: 50 })
    handlers.pointerup({ clientX: 52, clientY: 52 })   // <4px → click
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('a Ctrl-drag does nothing', () => {
    const { lasso, onSelect, onClick, handlers } = setup()
    lasso.start({ ctrlKey: true, clientX: 5, clientY: 5 })
    handlers.pointerup({ clientX: 195, clientY: 195 })
    expect(onSelect).not.toHaveBeenCalled()
    expect(onClick).not.toHaveBeenCalled()
  })

  it('Esc during a drag cancels it: controls re-enabled, no selection on release', () => {
    const { lasso, controls, onSelect, handlers } = setup()
    lasso.start({ ctrlKey: true, clientX: 5, clientY: 5 })
    expect(controls.enabled).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(controls.enabled).toBe(true)          // cancelled
    expect(handlers.pointerup).toBeUndefined()   // pointer + key listeners detached
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('detaches the Esc listener after finalize (no late cancel / leak)', () => {
    const { lasso, handlers } = setup()
    lasso.start({ ctrlKey: true, clientX: 5, clientY: 5 })
    handlers.pointerup({ clientX: 195, clientY: 195 })   // finalize detaches keydown
    expect(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))).not.toThrow()
  })
})

it('switches solid/dashed styles with direction and selects partially overlapped parts only when crossing', async () => {
  const canvas = document.createElement('canvas')
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 200 })
  const onSelect = vi.fn(), onPlainClick = vi.fn()
  const lasso = initAssemblyLasso({ canvas, camera: camera(), controls: { enabled: true },
    getInstanceCenters: () => [at('a', [0, 0, 0])], onSelect, onPlainClick })
  lasso.start({ button: 0, clientX: 50, clientY: 50 })
  canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 100, clientY: 150 }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(document.body.lastElementChild.style.borderStyle).toBe('solid')
  canvas.dispatchEvent(new MouseEvent('pointerup', { clientX: 100, clientY: 150 }))
  expect(onSelect).toHaveBeenLastCalledWith([], undefined)
  lasso.start({ button: 0, clientX: 100, clientY: 50 })
  canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 50, clientY: 150 }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(document.body.lastElementChild.style.borderStyle).toBe('dashed')
  canvas.dispatchEvent(new MouseEvent('pointerup', { clientX: 50, clientY: 150 }))
  expect(onSelect).toHaveBeenLastCalledWith(['a'], undefined)
  lasso.start({ button: 0, clientX: 100, clientY: 100 })
  canvas.dispatchEvent(new MouseEvent('pointerup', { clientX: 100, clientY: 100 }))
  expect(onPlainClick).toHaveBeenCalledOnce()
})

it.each(['pointerdown', 'pointermove'])('never shows a rectangle or selects when a later tool claims %s', async claimAt => {
  const canvas = document.createElement('canvas')
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 200 })
  const controls = { enabled: true }, onSelect = vi.fn(), onPlainClick = vi.fn()
  const lasso = initAssemblyLasso({ canvas, camera: camera(), controls,
    getInstanceCenters: () => [at('a', [0,0,0])], onSelect, onPlainClick })
  canvas.addEventListener('pointerdown', e => lasso.start(e))
  if (claimAt === 'pointerdown') canvas.addEventListener(claimAt, () => { controls.enabled = false })
  canvas.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 5, clientY: 5 }))
  const overlay = document.body.lastElementChild
  if (claimAt === 'pointermove') canvas.addEventListener(claimAt, () => { controls.enabled = false })
  canvas.dispatchEvent(new MouseEvent('pointermove', { buttons: 1, clientX: 195, clientY: 195 }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(overlay.isConnected).toBe(false)
  expect(controls.enabled).toBe(false) // cancelling selection must not release the tool's lock
  controls.enabled = true
  canvas.dispatchEvent(new MouseEvent('pointerup', { button: 0, clientX: 195, clientY: 195 }))
  expect(onSelect).not.toHaveBeenCalled(); expect(onPlainClick).not.toHaveBeenCalled()
  lasso.dispose()
})
