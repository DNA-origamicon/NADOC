import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initOxdnaLive, liveJobEligible, liveButtonState } from './oxdna_live_controller.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
vi.mock('../api/client.js', () => ({
  oxdnaLiveAvailable:   vi.fn(),
  startOxdnaLive:       vi.fn(),
  getOxdnaLiveFrame:    vi.fn(),
  updateOxdnaLiveField: vi.fn(),
  stopOxdnaLive:        vi.fn(),
  lastErrorMessage:     vi.fn(() => null),
}))
import * as api from '../api/client.js'

const IDS = { 'oxdna-jobs-live-btn': 'button', 'oxdna-jobs-live-status': 'div' }
const flush = () => new Promise((r) => setTimeout(r, 0))

function makeDisplay() {
  let mode = 'live'
  return {
    displayLiveFrame: vi.fn(() => true),
    stopAndRestore:   vi.fn(() => { mode = null }),
    mode: () => mode,
    isActive: () => mode != null,
  }
}

describe('liveJobEligible', () => {
  it('true only for a completed ROOT relaxation', () => {
    expect(liveJobEligible({ status: 'completed' })).toBe(true)
    expect(liveJobEligible({ status: 'running' })).toBe(false)
    expect(liveJobEligible({ status: 'completed', parent_job_id: 'p' })).toBe(false)  // field/prod child
    expect(liveJobEligible(null)).toBe(false)
  })
})

describe('liveButtonState', () => {
  it('disabled with reason when oxpy unavailable', () => {
    const s = liveButtonState({ available: false, availReason: 'oxpy not built', job: { status: 'completed' } })
    expect(s.enabled).toBe(false)
    expect(s.reason).toBe('oxpy not built')
  })
  it('disabled when no eligible job is selected', () => {
    const s = liveButtonState({ available: true, job: null })
    expect(s.enabled).toBe(false)
    expect(s.reason).toMatch(/completed relaxed job/)
  })
  it('enabled when available + eligible job', () => {
    const s = liveButtonState({ available: true, job: { status: 'completed' } })
    expect(s.enabled).toBe(true)
  })
})

describe('initOxdnaLive factory', () => {
  let els, display, job, field, surface, anchors

  function make() {
    return initOxdnaLive({
      oxdnaDisplay: display,
      getSelectedJob: () => job,
      getRunElements: () => ({ field, surface, anchors }),
    })
  }

  beforeEach(() => {
    els = mountIds(IDS)
    display = makeDisplay()
    job = { job_id: 'j1', status: 'completed' }
    field = { enabled: true, field_pN: 4, dir: [0, 1, 0] }
    surface = { enabled: false }
    anchors = [{ kind: 'overhang', id: 'o1' }]
    api.oxdnaLiveAvailable.mockResolvedValue({ available: true, reason: 'ready' })
    api.startOxdnaLive.mockResolvedValue({ session_id: 's1', status: 'starting' })
    api.getOxdnaLiveFrame.mockResolvedValue({ ready: false, status: 'starting', positions: [], n_positions: 0, n_bursts: 0 })
    api.stopOxdnaLive.mockResolvedValue({ ok: true, stopped: true })
    api.updateOxdnaLiveField.mockResolvedValue({ ok: true })
  })
  afterEach(() => { clearDom(); vi.clearAllMocks() })

  it('disables the button with a tooltip when oxpy is unavailable', async () => {
    api.oxdnaLiveAvailable.mockResolvedValue({ available: false, reason: 'oxpy not built' })
    make()
    await flush()
    expect(els['oxdna-jobs-live-btn'].disabled).toBe(true)
    expect(els['oxdna-jobs-live-btn'].title).toContain('oxpy not built')
  })

  it('enables the button for a completed relaxed job and starts a session on click', async () => {
    const ctl = make()
    await flush()
    expect(els['oxdna-jobs-live-btn'].disabled).toBe(false)

    let started = false
    const onStart = () => { started = true }
    window.addEventListener('nadoc:oxdna-live-start', onStart)
    els['oxdna-jobs-live-btn'].click()
    await flush()
    window.removeEventListener('nadoc:oxdna-live-start', onStart)

    expect(started).toBe(true)   // panel overlays get cleared before the first live frame
    expect(api.startOxdnaLive).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: 'j1', field: { field_pN: 4, dir: [0, 1, 0] }, anchors }))
    expect(ctl.isOn()).toBe(true)
    expect(els['oxdna-jobs-live-btn'].textContent).toContain('Stop')
    ctl.stop()
  })

  it('starts WITHOUT a field (anchors-only / free dynamics) — field is optional', async () => {
    field = { enabled: false, field_pN: 0, dir: [0, 1, 0] }
    const ctl = make()
    await flush()
    ctl.toggle()
    await flush()
    expect(api.startOxdnaLive).toHaveBeenCalled()
    const body = api.startOxdnaLive.mock.calls[0][0]
    expect(body.job_id).toBe('j1')
    expect(body.field).toBeUndefined()         // no field element
    expect(body.anchors).toEqual(anchors)      // anchors still composed
    expect(ctl.isOn()).toBe(true)
    ctl.stop()
  })

  it('refuses to start a FIELD without an anchor (COM-drift gotcha)', async () => {
    anchors = []                               // field enabled, no anchor
    const ctl = make()
    await flush()
    ctl.toggle()
    await flush()
    expect(api.startOxdnaLive).not.toHaveBeenCalled()
    expect(ctl.isOn()).toBe(false)
  })

  it('allows NO field + NO anchor (free dynamics)', async () => {
    field = { enabled: false, field_pN: 0, dir: [0, 1, 0] }
    anchors = []
    const ctl = make()
    await flush()
    ctl.toggle()
    await flush()
    expect(api.startOxdnaLive).toHaveBeenCalled()
    const body = api.startOxdnaLive.mock.calls[0][0]
    expect(body.field).toBeUndefined()
    expect(body.anchors).toBeUndefined()       // empty → omitted
    expect(ctl.isOn()).toBe(true)
    ctl.stop()
  })

  it('pushes a live field re-aim while running, and stops + restores on toggle off', async () => {
    const ctl = make()
    await flush()
    ctl.toggle()         // start
    await flush()
    expect(ctl.isOn()).toBe(true)

    field = { enabled: true, field_pN: 9, dir: [1, 0, 0] }
    ctl.onFieldChanged()
    expect(api.updateOxdnaLiveField).toHaveBeenCalledWith('s1', { field_pN: 9, dir: [1, 0, 0] })

    ctl.toggle()         // stop
    expect(api.stopOxdnaLive).toHaveBeenCalledWith('s1')
    expect(display.stopAndRestore).toHaveBeenCalled()
    expect(ctl.isOn()).toBe(false)
  })

  it('does not push a field re-aim when off', async () => {
    const ctl = make()
    await flush()
    ctl.onFieldChanged()
    expect(api.updateOxdnaLiveField).not.toHaveBeenCalled()
  })

  it('dispatches oxdna-live-start after the session is running (panel locks its toggles)', async () => {
    const ctl = make()
    await flush()
    let onAtDispatch = null
    const h = () => { onAtDispatch = ctl.isOn() }   // the panel reads isOn() in this handler
    window.addEventListener('nadoc:oxdna-live-start', h)
    ctl.toggle()
    await flush()
    window.removeEventListener('nadoc:oxdna-live-start', h)
    expect(onAtDispatch).toBe(true)   // isOn() is already true when the lock event fires
    ctl.stop()
  })

  it('dispatches oxdna-live-stop on teardown (panel unlocks its toggles)', async () => {
    const ctl = make()
    await flush()
    ctl.toggle()                       // start
    await flush()
    let stopped = false
    const h = () => { stopped = true }
    window.addEventListener('nadoc:oxdna-live-stop', h)
    ctl.stop()
    window.removeEventListener('nadoc:oxdna-live-stop', h)
    expect(stopped).toBe(true)
  })
})
