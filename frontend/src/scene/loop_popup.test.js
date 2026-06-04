import { describe, it, expect, vi, beforeEach } from 'vitest'
import { bestLoopNick, initLoopPopup } from './loop_popup.js'

describe('bestLoopNick', () => {
  it('picks the midpoint of the longest domain ≥15 bp', () => {
    const strand = { domains: [
      { helix_id: 1, start_bp: 0, end_bp: 9, direction: 'FORWARD' },   // 10 bp, too short
      { helix_id: 2, start_bp: 0, end_bp: 19, direction: 'REVERSE' },  // 20 bp, winner
    ] }
    expect(bestLoopNick(strand)).toEqual({ helixId: 2, bpIndex: 10, direction: 'REVERSE' })
  })

  it('handles reverse domains (end_bp < start_bp)', () => {
    const strand = { domains: [{ helix_id: 5, start_bp: 19, end_bp: 0, direction: 'FORWARD' }] }
    // lo=0, len=20, mid = 0 + 10
    expect(bestLoopNick(strand)).toEqual({ helixId: 5, bpIndex: 10, direction: 'FORWARD' })
  })

  it('falls back to the longest domain ≥3 bp when none reach 15', () => {
    const strand = { domains: [
      { helix_id: 1, start_bp: 0, end_bp: 4, direction: 'FORWARD' },  // 5 bp
      { helix_id: 2, start_bp: 0, end_bp: 9, direction: 'FORWARD' },  // 10 bp, winner
    ] }
    expect(bestLoopNick(strand)).toEqual({ helixId: 2, bpIndex: 5, direction: 'FORWARD' })
  })

  it('returns null when no domain reaches the 3 bp fallback floor', () => {
    expect(bestLoopNick({ domains: [{ helix_id: 1, start_bp: 0, end_bp: 1, direction: 'FORWARD' }] })).toBeNull()
    expect(bestLoopNick({ domains: [] })).toBeNull()
    expect(bestLoopNick(undefined)).toBeNull()
  })
})

describe('initLoopPopup', () => {
  let store, api, subscriber
  const loopStrand = { id: 's1', domains: [{ helix_id: 2, start_bp: 0, end_bp: 19, direction: 'FORWARD' }] }

  function makeStore() {
    return {
      _state: { lastError: null },
      subscribe: vi.fn(fn => { subscriber = fn }),
      getState() { return this._state },
    }
  }
  const sel = (strand_id) => ({ data: { strand_id } })

  beforeEach(() => {
    document.body.innerHTML = ''
    subscriber = null
    store = makeStore()
    api = { addNick: vi.fn().mockResolvedValue(true) }
  })

  it('mounts a hidden overlay and registers one subscription', () => {
    const { overlay } = initLoopPopup({ store, api, isCtrlHeld: () => false })
    expect(document.getElementById('loop-strand-popup')).toBe(overlay)
    expect(overlay.style.display).toBe('none')
    expect(store.subscribe).toHaveBeenCalledTimes(1)
  })

  it('shows the popup when a circular (loop) strand is selected', () => {
    const { overlay } = initLoopPopup({ store, api, isCtrlHeld: () => false })
    subscriber(
      { selectedObject: sel('s1'), loopStrandIds: ['s1'], currentDesign: { strands: [loopStrand] } },
      { selectedObject: null },
    )
    expect(overlay.style.display).toBe('flex')
  })

  it('stays hidden for a non-loop strand', () => {
    const { overlay } = initLoopPopup({ store, api, isCtrlHeld: () => false })
    subscriber(
      { selectedObject: sel('s1'), loopStrandIds: [], currentDesign: { strands: [loopStrand] } },
      { selectedObject: null },
    )
    expect(overlay.style.display).toBe('none')
  })

  it('is suppressed while Ctrl is held', () => {
    const { overlay } = initLoopPopup({ store, api, isCtrlHeld: () => true })
    subscriber(
      { selectedObject: sel('s1'), loopStrandIds: ['s1'], currentDesign: { strands: [loopStrand] } },
      { selectedObject: null },
    )
    expect(overlay.style.display).toBe('none')
  })

  it('Nick here calls api.addNick with the computed nick and closes', async () => {
    const { overlay } = initLoopPopup({ store, api, isCtrlHeld: () => false })
    subscriber(
      { selectedObject: sel('s1'), loopStrandIds: ['s1'], currentDesign: { strands: [loopStrand] } },
      { selectedObject: null },
    )
    overlay.querySelector('#loop-popup-nick').click()
    await Promise.resolve()
    expect(api.addNick).toHaveBeenCalledWith({ helixId: 2, bpIndex: 10, direction: 'FORWARD' })
    expect(overlay.style.display).toBe('none')
  })

  it('Leave unresolved closes without nicking', () => {
    const { overlay } = initLoopPopup({ store, api, isCtrlHeld: () => false })
    subscriber(
      { selectedObject: sel('s1'), loopStrandIds: ['s1'], currentDesign: { strands: [loopStrand] } },
      { selectedObject: null },
    )
    overlay.querySelector('#loop-popup-leave').click()
    expect(api.addNick).not.toHaveBeenCalled()
    expect(overlay.style.display).toBe('none')
  })
})
