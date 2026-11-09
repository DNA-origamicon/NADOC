import { describe, it, expect, vi } from 'vitest'
import { initLivePlayback, liveFrameBlend, initLivePlaybackPopup } from './oxdna_live_playback.js'

const frame = x => [{ helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [x, 0, 0], cm_position: [x, 1, 0], nx: 1, ny: 0, nz: 0 }]
function harness(options = { bufferFrames: 2, maxBufferedFrames: 2 }) {
  let time = 0, id = 0
  const callbacks = new Map(), values = []
  const player = initLivePlayback({ ...options, now: () => time, draw: p => values.push(p[0].backbone_position[0]),
    request: cb => { callbacks.set(++id, cb); return id }, cancel: id => callbacks.delete(id) })
  return { player, values, callbacks, at(t) { time = t }, tick(t) {
    time = t
    const batch = [...callbacks.values()]; callbacks.clear(); batch.forEach(cb => cb(t))
  } }
}
describe('live frame playback', () => {
  it('uses the trajectory two-frame interpolation without mutating endpoints', () => {
    const a = frame(0), b = frame(10), blend = liveFrameBlend(a, b)
    expect(blend(.25)[0].backbone_position).toEqual([2.5, 0, 0])
    expect(blend(.5)[0].cm_position).toEqual([5, 1, 0])
    expect(a).toEqual(frame(0)); expect(b).toEqual(frame(10))
    expect(liveFrameBlend(a, [{ ...b[0], copy: 1 }])).toBeNull()
    expect(liveFrameBlend(a, [])).toBeNull()
  })
  it('uses all four knots and matches tangents across adjacent segments', () => {
    const first = liveFrameBlend(frame(0), frame(10), null, frame(30))
    const second = liveFrameBlend(frame(10), frame(30), frame(0), frame(60))
    expect(first(.5)[0].backbone_position[0]).toBe(4.375)
    expect(second(.5)[0].backbone_position[0]).toBe(18.75)
    const left = (10 - first(.999)[0].backbone_position[0]) / .001
    const right = (second(.001)[0].backbone_position[0] - 10) / .001
    expect(Math.abs(left - right)).toBeLessThan(.03)
    // Never borrow a tangent from another particle after recomposition.
    expect(liveFrameBlend(frame(0), frame(10), null,
      [{ ...frame(30)[0], copy: 1 }])(.5)[0].backbone_position[0]).toBe(5)
  })
  it('buffers lookahead, uses the previous knot, and holds endpoints during stalls', () => {
    const h = harness(); h.player.setSmooth(true)
    h.player.push(frame(0), 1)
    h.at(500); h.player.push(frame(10), 2)
    expect(h.callbacks.size).toBe(0)
    h.at(1000); h.player.push(frame(30), 3)
    h.tick(1250); expect(h.values.at(-1)).toBe(4.375)
    h.at(1500); h.player.push(frame(60), 4)
    h.tick(1500); expect(h.values.at(-1)).toBe(10)
    h.tick(1750); expect(h.values.at(-1)).toBe(18.75)
    h.tick(2000); expect(h.values.at(-1)).toBe(30)
    expect(h.callbacks.size).toBe(0)
    h.tick(4000); expect(h.values.at(-1)).toBe(30)
    h.at(5000); h.player.push(frame(100), 5)
    h.tick(5250); expect(h.values.at(-1)).toBe(43.75)
    h.tick(5500); expect(h.values.at(-1)).toBe(60)
    expect(h.callbacks.size).toBe(0)
  })
  it('carries the segment deadline across render jitter without accumulating pauses', () => {
    const h = harness(); h.player.setSmooth(true)
    h.player.push(frame(0), 1)
    h.at(500); h.player.push(frame(10), 2)
    h.at(1000); h.player.push(frame(30), 3)
    h.at(1500); h.player.push(frame(60), 4)
    h.tick(1510); expect(h.values.at(-1)).toBeCloseTo(10.302, 4)
    h.tick(1760); expect(h.values.at(-1)).toBeCloseTo(19.152, 4)
  })
  it('pins the active lookahead and coalesces later arrivals without a backlog', () => {
    const h = harness(); h.player.setSmooth(true)
    h.player.push(frame(0), 1)
    h.at(500); h.player.push(frame(10), 2)
    h.at(1000); h.player.push(frame(30), 3)
    h.at(1100); h.player.push(frame(60), 4)
    h.at(1200); h.player.push(frame(100), 5)
    h.tick(1250); expect(h.values.at(-1)).toBe(4.375)
    h.tick(1500); expect(h.values.at(-1)).toBe(10)
    h.tick(1750); expect(h.values.at(-1)).toBe(16.25)
    h.tick(2000); expect(h.values.at(-1)).toBe(30)
    expect(h.callbacks.size).toBe(0)
    // A suspended renderer completes only one segment and starts the next now.
    h.at(2500); h.player.push(frame(110), 6)
    h.at(3000); h.player.push(frame(120), 7)
    h.tick(10000); expect(h.values.at(-1)).toBe(100)
    h.tick(10250); expect(h.values.at(-1)).toBeGreaterThan(100)
  })
  it('ignores repeated generations and cancels animation on toggle and teardown', () => {
    const h = harness(); h.player.push(frame(0), 1); h.player.setSmooth(true)
    h.at(500); h.player.push(frame(10), 2)
    h.at(1000); h.player.push(frame(20), 3)
    h.tick(1250); h.player.push(frame(20), 3)
    h.player.setSmooth(false)
    expect(h.values.at(-1)).toBe(20); expect(h.callbacks.size).toBe(0)
    h.player.setSmooth(true); h.player.push(frame(30), 4)
    h.player.push(frame(40), 5)
    h.player.reset(); h.tick(2000)
    expect(h.values.at(-1)).toBe(20)
    h.player.push(frame(30), 1); expect(h.values.at(-1)).toBe(30)
  })
  it('keeps a reserve through a late frame, then refills after a sustained outage', () => {
    const h = harness({}); h.player.setSmooth(true); h.player.push(frame(0), 0)
    for (let i = 1; i <= 3; i++) { h.at(i * 500); h.player.push(frame(i * 10), i) }
    expect(h.callbacks.size).toBe(0)
    expect(h.player.diagnostics()).toMatchObject({ buffering: true, buffered: 3, bufferTarget: 4 })
    h.at(2000); h.player.push(frame(40), 4)
    h.tick(2250); expect(h.values.at(-1)).toBe(5)
    // No new frames for a full second: reserve still keeps motion continuous.
    h.tick(2500); h.tick(2750); expect(h.values.at(-1)).toBe(15)
    expect(h.player.diagnostics().underruns).toBe(0)
    h.tick(3000); h.tick(3500)
    expect(h.values.at(-1)).toBe(30)
    expect(h.player.diagnostics()).toMatchObject({ buffering: true, buffered: 1, underruns: 1 })
    h.at(4000); h.player.push(frame(50), 5)
    h.at(4500); h.player.push(frame(60), 6)
    expect(h.callbacks.size).toBe(0)
    h.at(5000); h.player.push(frame(70), 7)
    expect(h.callbacks.size).toBe(1)
    h.tick(5250); expect(h.values.at(-1)).toBeGreaterThan(30)
  })
  it('caps memory while a hidden renderer falls behind', () => {
    const h = harness({}); h.player.setSmooth(true); h.player.push(frame(0), 0)
    for (let i = 1; i <= 30; i++) { h.at(i * 500); h.player.push(frame(i * 10), i) }
    expect(h.player.diagnostics()).toMatchObject({ buffered: 8, coalescedFrames: 21 })
    h.tick(15500); expect(h.values.at(-1)).toBe(10)
    h.tick(16000); expect(h.values.at(-1)).toBe(20)
  })
  it('low-passes arrival jitter instead of abruptly changing segment speed', () => {
    const h = harness({}); h.player.push(frame(0), 0)
    h.at(500); h.player.push(frame(10), 1)
    h.at(1500); h.player.push(frame(20), 2)
    expect(h.player.diagnostics()).toMatchObject({ arrivalMs: 1000, cadenceMs: 550 })
  })
  it('mounts a hidden upper-left control and reports the checkbox state', () => {
    const host = document.createElement('div'); host.id = 'canvas-area'; document.body.append(host)
    const onSmooth = vi.fn(), popup = initLivePlaybackPopup({ onSmooth })
    const node = host.querySelector('#oxdna-live-playback')
    expect(node.hidden).toBe(true); popup.show(true); expect(node.hidden).toBe(false)
    node.querySelector('input').click(); expect(onSmooth).toHaveBeenLastCalledWith(true)
    popup.show(false); expect(node.hidden).toBe(true)
    host.remove()
  })
})
