import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createVRViewTools, VR_VIEW_KEYS } from './vr_view_tools.js'
import { broadcastFingerprint } from '../viewer/broadcast_fingerprint.js'

vi.mock('../viewer/broadcast_fingerprint.js', () => ({ broadcastFingerprint: vi.fn(() => 'same-scene') }))
let state, controller
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
  vi.stubGlobal('requestAnimationFrame', callback => setTimeout(callback, 0))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })))
  vi.mocked(broadcastFingerprint).mockClear()
  document.body.innerHTML = VR_VIEW_KEYS.map(key => `<button data-vt="${key}" class="${key === 'deform' ? 'active' : ''}"></button>`).join('')
  const context = { fillRect() {}, strokeRect() {}, fillText() {}, drawImage() {},
    measureText: text => ({ width: text.length * 8 }),
    getImageData: () => ({ data: new Uint8ClampedArray(2048 * 2048 * 4) }) }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
  state = { currentGeometry: [], currentDesign: { deformations: [{}] } }
  controller = createVRViewTools({ scene: new THREE.Scene(), getState: () => state })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })
async function publishSettled() {
  // First poll discovers a changed input; second runs after the normal debounce.
  const first = controller.publish()
  await vi.runAllTimersAsync(); await first
  await vi.advanceTimersByTimeAsync(1600)
  const second = controller.publish()
  await vi.runAllTimersAsync(); await second
}

it('keeps the unchanged canonical-mode tablet across geometry and metadata edits', async () => {
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(1)
  for (let i = 0; i < 3; i++) {
    state = { currentGeometry: [{ x: i }], currentDesign: { deformations: [{}], revision: i } }
    await publishSettled()
  }
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(broadcastFingerprint).not.toHaveBeenCalled()
})

it('still republishes overlay geometry and transitions back to the canonical scene', async () => {
  await publishSettled()
  document.querySelector('[data-vt="sequences"]').classList.add('active')
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(2)
  state = { ...state, currentGeometry: [{ x: 4 }] }
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(broadcastFingerprint).toHaveBeenCalled()
  document.querySelector('[data-vt="sequences"]').classList.remove('active')
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(4)
  state = { ...state, currentDesign: { deformations: [{}], revision: 8 } }
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(4)
})

it('publishes explicit tablet acknowledgements and a new viewer after reset', async () => {
  await publishSettled()
  await controller.activate(0, 7)
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(2)
  controller.reset()
  await publishSettled()
  expect(fetch).toHaveBeenCalledTimes(3)
})
