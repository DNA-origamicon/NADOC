import { it, expect, vi, afterEach } from 'vitest'
import { mountMeetingPresentation } from './meeting_presentation.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
const cameraDefaults = { target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' }
function setup(role = 'guest', options = {}) {
  document.body.innerHTML = '<header></header><main><canvas></canvas></main><button id="reset"></button><select id="mode"></select>'
  const events = new EventTarget(); events.close = vi.fn()
  const frames = new Set(), viewer = { current: {}, performanceApi: { busy: false }, runtime: { controls: { enabled: true }, addFrameCallback: fn => frames.add(fn), removeFrameCallback: fn => frames.delete(fn) }, captureCamera: vi.fn(() => ({ ...cameraDefaults, position: [2, 3, 4] })), applyCamera: vi.fn() }
  let tick
  viewer.mobile = options.mobile ?? false
  viewer.setViewLocked = vi.fn()
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
  const dispose = mountMeetingPresentation({ viewer, base: '/meeting/room', role, revision: 'rev', room: 'room', document, fetch: request, eventSource: () => events, setInterval: fn => { tick = fn; return 1 }, clearInterval: vi.fn(), ...options })
  const state = (sequence, camera = { position: [10, 0, 30] }, extra = {}) => events.dispatchEvent(new MessageEvent('state', { data: JSON.stringify({ room: 'room', revision: 'rev', sequence, camera: camera && { ...cameraDefaults, ...camera }, presenting: true, ...extra }) }))
  events.dispatchEvent(new Event('open'))
  return { events, viewer, request, state, tick, dispose, frame: () => [...frames].forEach(fn => fn()) }
}
it.each(['pointerdown', 'nadoc:view-navigation'])('leaves camera independent until Follow; %s exits Follow', event => {
  const v = setup(); v.state(1); v.frame(); expect(v.viewer.applyCamera).not.toHaveBeenCalled()
  expect(document.querySelector('[data-jump]')).toBeNull()
  v.state(2); v.frame(); expect(v.viewer.applyCamera).not.toHaveBeenCalled()
  document.querySelector('[data-follow]').click(); v.frame(); expect(v.viewer.applyCamera).toHaveBeenCalledTimes(1)
  document.querySelector('canvas').dispatchEvent(new Event(event))
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('false')
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  v.frame(); expect(v.viewer.applyCamera).toHaveBeenCalledTimes(1); v.dispose()
})
it('ignores stale/cross-snapshot events and releases controls on loss or disposal', () => {
  const v = setup(); v.state(3); document.querySelector('[data-follow]').click()
  v.state(2, { position: [90, 0, 0] }); v.state(4, null, { revision: 'other' }); v.frame()
  expect(v.viewer.applyCamera.mock.calls.at(-1)[0].position[0]).toBeLessThan(10)
  v.events.dispatchEvent(new Event('error')); expect(v.viewer.runtime.controls.enabled).toBe(true)
  v.events.dispatchEvent(new Event('open')); v.state(5); v.frame()
  expect(v.viewer.applyCamera).toHaveBeenCalledTimes(1) // never auto-follow on reconnect
  v.dispose(); expect(v.events.close).toHaveBeenCalledOnce(); expect(document.querySelector('[data-presentation]')).toBeNull()
})
it('coalesces presenter changes with at most one request in flight and pauses explicitly', async () => {
  const v = setup('presenter'); document.querySelector('[data-broadcast]').click()
  await vi.waitFor(() => expect(v.request).toHaveBeenCalledOnce())
  await v.tick(); expect(v.request).toHaveBeenCalledOnce()
  v.viewer.captureCamera.mockReturnValue({ position: [5, 6, 7] })
  await v.tick(); expect(v.request).toHaveBeenCalledTimes(2)
  expect(JSON.parse(v.request.mock.calls[1][1].body).revision).toBe('rev')
  document.querySelector('[data-broadcast]').click()
  await vi.waitFor(() => expect(v.request.mock.calls.at(-1)[0]).toBe('/meeting/room/pause'))
  v.dispose()
})
it('explicit browser offline releases the camera and reconnect never re-enables Follow', () => {
  const v = setup(); v.state(1); document.querySelector('[data-follow]').click()
  window.dispatchEvent(new Event('offline'))
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  expect(document.querySelector('[data-follow]').disabled).toBe(true)
  window.dispatchEvent(new Event('online')); v.events.dispatchEvent(new Event('open')); v.state(2)
  expect(document.querySelector('[data-follow]').disabled).toBe(false)
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('false')
  v.dispose()
})

it('updates an announced scene without taking the guest camera or losing the presentation channel', async () => {
  let finish
  const loadRevision = vi.fn(({ viewer }) => new Promise(resolve => { finish = () => { viewer.current = {}; resolve(true) } }))
  const v = setup('guest', { loadRevision })
  v.state(1, undefined, { revision: 'a'.repeat(64) })
  expect(document.querySelector('[data-follow]').disabled).toBe(true)
  finish(); await vi.waitFor(() => expect(document.querySelector('[data-follow]').disabled).toBe(false))
  v.frame(); expect(v.viewer.applyCamera).not.toHaveBeenCalled()
  expect(v.events.close).not.toHaveBeenCalled()
  document.querySelector('[data-follow]').click(); v.frame()
  expect(v.viewer.applyCamera).toHaveBeenCalled()
  v.dispose()
})

it('does not download room revisions over a privately opened guest file', () => {
  const loadRevision = vi.fn(), v = setup('guest', { loadRevision })
  v.viewer.current = {}
  v.state(1, undefined, { revision: 'a'.repeat(64) }); v.tick()
  expect(loadRevision).not.toHaveBeenCalled(); v.dispose()
})

it.each(['guest', 'presenter'])('remounts playback for updated %s content while preserving the meeting channel', async role => {
  const mounts = [], mountTrajectory = vi.fn(() => { const value = { receive: vi.fn(), dispose: vi.fn() }; mounts.push(value); return value })
  const onSharedView = vi.fn(), loadRevision = vi.fn(async ({ viewer }) => { viewer.current = {}; return true })
  const v = setup(role, { mountTrajectory, onSharedView, loadRevision })
  v.state(1, null, { revision: 'a'.repeat(64), serverTime: 1000, trajectory: { id: 'clip' }, presenting: false })
  await vi.waitFor(() => expect(mounts.length).toBe(2))
  expect(mounts[0].dispose).toHaveBeenCalledOnce()
  expect(mounts[1].receive.mock.calls.at(-1)[0].trajectory.id).toBe('clip')
  expect(onSharedView).toHaveBeenLastCalledWith(v.viewer.current)
  v.state(2, null, { revision: 'b'.repeat(64), serverTime: 2000, trajectory: null, presenting: false })
  await vi.waitFor(() => expect(mounts.length).toBe(3))
  expect(mounts[1].dispose).toHaveBeenCalledOnce()
  expect(mounts[2].receive.mock.calls.at(-1)[0].trajectory).toBeNull()
  expect(v.events.close).not.toHaveBeenCalled(); expect(v.viewer.applyCamera).not.toHaveBeenCalled()
  v.dispose(); expect(mounts[2].dispose).toHaveBeenCalledOnce()
})
it('cancels a pending replacement when the host returns to the already displayed revision', async () => {
  let finish
  const loadRevision = vi.fn(({ viewer, isCurrent }) => new Promise(resolve => { finish = () => { const valid = isCurrent(); if (valid) viewer.current = {}; resolve(valid) } }))
  const v = setup('guest', { loadRevision }), original = v.viewer.current
  v.state(1, null, { revision: 'a'.repeat(64), presenting: false })
  v.state(2, null, { revision: 'rev', presenting: false })
  finish(); await new Promise(resolve => setTimeout(resolve, 0))
  await v.tick()
  expect(v.viewer.current).toBe(original)
  expect(loadRevision).toHaveBeenCalledOnce()
  v.dispose()
})

it('relays loading and recognizes a terminal state without calling it a transient disconnection', () => {
  const onLoading = vi.fn(), onEnded = vi.fn(); const v = setup('guest', { onLoading, onEnded })
  v.state(1, null, { loading: { fraction: .6 } }); expect(onLoading).toHaveBeenLastCalledWith({ fraction: .6 }, false)
  v.events.dispatchEvent(new Event('error')); expect(onEnded).not.toHaveBeenCalled()
  v.state(2, null, { ended: true }); expect(onEnded).toHaveBeenCalledOnce(); v.dispose()
})

it('displays completed snapshots while newer playback snapshots arrive', async () => {
  const pending = [], applied = []
  const loadRevision = vi.fn(({ viewer, revision, isCurrent }) => new Promise(resolve => pending.push(() => {
    const valid = isCurrent()
    if (valid) { viewer.current = {}; applied.push(revision) }
    resolve(valid)
  })))
  const v = setup('guest', { loadRevision })
  v.state(1, null, { revision: 'a'.repeat(64) })
  v.state(2, null, { revision: 'b'.repeat(64) })
  pending.shift()()
  await vi.waitFor(() => expect(loadRevision).toHaveBeenCalledTimes(2))
  expect(applied).toEqual(['a'.repeat(64)])
  pending.shift()()
  await vi.waitFor(() => expect(applied).toEqual(['a'.repeat(64), 'b'.repeat(64)]))
  v.dispose()
})

it('keeps Follow green across presenter handoffs and visualization changes', async () => {
  const loadRevision = vi.fn(async ({ viewer }) => { viewer.current = {}; return true })
  const v = setup('guest', { loadRevision })
  v.state(1); const button = document.querySelector('[data-follow]'); button.click()
  expect(button.style.background).toBe('rgb(35, 134, 54)')
  v.state(2, null, { presenting: false }) // native publisher releases its lease
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(button.disabled).toBe(false) // opting out remains possible during the handoff
  v.state(3, null, { revision: 'a'.repeat(64), presenting: false })
  await vi.waitFor(() => expect(loadRevision).toHaveBeenCalledOnce())
  v.state(4, { position: [50, 0, 30] }, { revision: 'a'.repeat(64) })
  v.frame()
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(v.viewer.applyCamera).toHaveBeenCalled()
  expect(v.viewer.runtime.controls.enabled).toBe(false)
  document.querySelector('canvas').dispatchEvent(new Event('pointerdown'))
  expect(button.style.background).toBe('')
  expect(button.getAttribute('aria-pressed')).toBe('false')
  v.dispose()
})

it('reconnects after a suspended tab returns and removes the lifecycle listener on disposal', () => {
  const v = setup(), hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  document.dispatchEvent(new Event('visibilitychange')); expect(v.events.close).not.toHaveBeenCalled()
  hidden.mockReturnValue(false)
  document.dispatchEvent(new Event('visibilitychange')); expect(v.events.close).toHaveBeenCalledOnce()
  v.dispose()
  document.dispatchEvent(new Event('visibilitychange')); expect(v.events.close).toHaveBeenCalledTimes(2)
})
it('forces late joiners to follow while locked and restores their choice after animation', () => {
  const v = setup()
  v.state(1, undefined, { viewLocked: true, animationActive: true })
  expect(document.querySelector('[data-follow]').disabled).toBe(true)
  expect(document.querySelector('#reset').disabled).toBe(true)
  expect(v.viewer.runtime.controls.enabled).toBe(false)
  document.querySelector('canvas').dispatchEvent(new Event('pointerdown'))
  expect(v.viewer.runtime.controls.enabled).toBe(false)
  document.querySelector('[data-follow]').click()
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('true')
  v.state(2, undefined, { viewLocked: false, animationActive: false })
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  expect(document.querySelector('#reset').disabled).toBe(false)
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('false')
  v.dispose()
})

it('uses identical interpolated camera updates for locked and voluntary following', () => {
  let time = 0
  vi.spyOn(performance, 'now').mockImplementation(() => time)
  const runs = []
  for (const locked of [false, true]) {
    time = 0
    const v = setup(); v.state(1, undefined, { viewLocked: locked })
    if (!locked) document.querySelector('[data-follow]').click()
    time = 450; v.frame()
    time = 1000; v.frame()
    time = 1016; v.state(2, { position: [20, 5, 25] }, { viewLocked: locked }); v.frame()
    runs.push(v.viewer.applyCamera.mock.calls)
    expect(v.viewer.applyCamera.mock.calls[0][2]).toEqual({ resetControls: false })
    expect(v.viewer.applyCamera.mock.calls[2][1]).toBeGreaterThan(0)
    expect(v.viewer.applyCamera.mock.calls[2][1]).toBeLessThan(1)
    expect(v.viewer.runtime.controls.enabled).toBe(false)
    v.dispose()
  }
  expect(runs[1]).toEqual(runs[0])
})

it('holds the mobile drawing pose, restores navigation, and gives host locks priority', () => {
  const v = setup('guest', { mobile: true }); v.state(1)
  const draw = document.querySelector('[data-draw]'), follow = document.querySelector('[data-follow]')
  follow.click(); v.frame()
  draw.click()
  expect(follow.getAttribute('aria-pressed')).toBe('false')
  expect(follow.disabled).toBe(true)
  expect(v.viewer.runtime.controls.enabled).toBe(false)
  expect(v.viewer.setViewLocked).toHaveBeenLastCalledWith(true)
  const calls = v.viewer.applyCamera.mock.calls.length
  v.state(2, { position: [40, 0, 20] }); v.frame()
  expect(v.viewer.applyCamera).toHaveBeenCalledTimes(calls)
  draw.click()
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  expect(document.querySelector('#reset').disabled).toBe(false)
  draw.click(); v.state(3, undefined, { viewLocked: true })
  expect(draw.getAttribute('aria-pressed')).toBe('false')
  expect(draw.disabled).toBe(true)
  expect(v.viewer.runtime.controls.enabled).toBe(false)
  expect(follow.getAttribute('aria-pressed')).toBe('true')
  v.state(4, undefined, { viewLocked: false })
  expect(v.viewer.runtime.controls.enabled).toBe(true)
  expect(draw.disabled).toBe(false)
  v.dispose()
})

it('delivers same-scene selection pings without reloading or interrupting Follow', () => {
  const loadRevision = vi.fn(), v = setup('guest', { loadRevision })
  v.viewer.receiveSelectionPing = vi.fn()
  v.state(1); document.querySelector('[data-follow]').click()
  const selectionPing = { revision: 'rev', target: 'cloud', selectionRevision: 1, ping: { id: 'one', createdAt: Date.now() } }
  v.state(2, undefined, { selectionPing })
  expect(v.viewer.receiveSelectionPing).toHaveBeenCalledWith(selectionPing)
  expect(loadRevision).not.toHaveBeenCalled()
  expect(document.querySelector('[data-follow]').getAttribute('aria-pressed')).toBe('true')
  v.state(3, undefined, { selectionPing: { ...selectionPing, revision: 'stale' } })
  expect(v.viewer.receiveSelectionPing).toHaveBeenCalledOnce()
  v.dispose()
})
