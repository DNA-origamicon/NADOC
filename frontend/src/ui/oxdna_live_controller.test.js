import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initOxdnaLive, liveJobEligible, liveButtonState,
         backendLabel, liveStatusLine, liveFallbackNotice, reconfigSig,
         liveStartBody } from './oxdna_live_controller.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
vi.mock('../api/client.js', () => ({
  oxdnaLiveAvailable:   vi.fn(),
  startOxdnaLive:       vi.fn(),
  getOxdnaLiveFrame:    vi.fn(),
  updateOxdnaLiveField: vi.fn(),
  reconfigureOxdnaLive: vi.fn(),
  stopOxdnaLive:        vi.fn(),
  lastErrorMessage:     vi.fn(() => null),
}))
import * as api from '../api/client.js'

const IDS = { 'oxdna-jobs-live-btn': 'button', 'oxdna-jobs-live-status': 'div' }
const flush = () => new Promise((r) => setTimeout(r, 0))
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

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
  it('accepts prepared and previously run jobs, including continuations', () => {
    expect(liveJobEligible({ status: 'completed' })).toBe(true)
    expect(liveJobEligible({ status: 'queued' })).toBe(true)
    expect(liveJobEligible({ status: 'stopped', parent_job_id: 'p' })).toBe(true)
    expect(liveJobEligible({ status: 'running' })).toBe(false)
    expect(liveJobEligible({ status: 'completed', parent_job_id: 'p' })).toBe(true)
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
    expect(s.reason).toMatch(/prepared or previously run/)
  })
  it('enabled when available + eligible job', () => {
    const s = liveButtonState({ available: true, job: { status: 'completed' } })
    expect(s.enabled).toBe(true)
  })
})

describe('backendLabel', () => {
  it('maps CUDA→GPU, CPU→CPU, unknown→empty', () => {
    expect(backendLabel('CUDA')).toBe('GPU (CUDA)')
    expect(backendLabel('CPU')).toBe('CPU')
    expect(backendLabel(null)).toBe('')
    expect(backendLabel(undefined)).toBe('')
  })
})

describe('liveStatusLine', () => {
  it('warming up before the first frame is ready', () => {
    expect(liveStatusLine({ ready: false })).toMatch(/warming up/)
  })
  it('includes nt, burst count, and the active backend', () => {
    expect(liveStatusLine({ ready: true, nPositions: 504, nBursts: 3, backend: 'CUDA' }))
      .toBe('Live · 504 nt · 3 bursts stepped · GPU (CUDA)')
  })
  it('singularizes a single burst and omits an unknown backend', () => {
    expect(liveStatusLine({ ready: true, nPositions: 100, nBursts: 1 }))
      .toBe('Live · 100 nt · 1 burst stepped')
  })
})

describe('liveFallbackNotice', () => {
  it('fires once when the frame reports a GPU→CPU fallback', () => {
    const msg = liveFallbackNotice({ backend_fell_back: true }, false)
    expect(msg).toMatch(/GPU out of memory/)
    expect(msg).toMatch(/fell back to CPU/)
  })
  it('suppressed once already shown', () => {
    expect(liveFallbackNotice({ backend_fell_back: true }, true)).toBeNull()
  })
  it('null when no fallback occurred', () => {
    expect(liveFallbackNotice({ backend_fell_back: false }, false)).toBeNull()
    expect(liveFallbackNotice({}, false)).toBeNull()
    expect(liveFallbackNotice(null, false)).toBeNull()
  })
})

describe('reconfigSig', () => {
  it('is stable across field magnitude/direction changes (re-aimed in place)', () => {
    const a = reconfigSig({ field: { enabled: true, field_pN: 4, dir: [0, 1, 0] }, anchors: [{ id: 'o1' }] })
    const b = reconfigSig({ field: { enabled: true, field_pN: 9, dir: [1, 0, 0] }, anchors: [{ id: 'o1' }] })
    expect(a).toBe(b)
  })
  it('changes when the field is toggled on/off', () => {
    const off = reconfigSig({ field: { enabled: false }, anchors: [{ id: 'o1' }] })
    const on = reconfigSig({ field: { enabled: true, field_pN: 4, dir: [0, 1, 0] }, anchors: [{ id: 'o1' }] })
    expect(off).not.toBe(on)
  })
  it('changes when the surface is toggled or its params change', () => {
    const off = reconfigSig({ surface: { enabled: false } })
    const on = reconfigSig({ surface: { enabled: true, dir: [0, 0, 1], offsetNm: 0, stiff: 1 } })
    const moved = reconfigSig({ surface: { enabled: true, dir: [0, 0, 1], offsetNm: 5, stiff: 1 } })
    expect(off).not.toBe(on)
    expect(on).not.toBe(moved)
  })
  it('changes when anchors change', () => {
    expect(reconfigSig({ anchors: [{ id: 'o1' }] })).not.toBe(reconfigSig({ anchors: [{ id: 'o1' }, { id: 'o2' }] }))
  })
})

describe('liveStartBody', () => {
  it('carries every current continuation card while retaining the selected job', () => {
    expect(liveStartBody({ job_id: 'selected' }, {
      field: { enabled: true, field_pN: 7, dir: [1, 0, 0] },
      surface: { enabled: true, dir: [0, 0, 1], offsetNm: 2, positionNm: -4, stiff: 5 },
      anchors: [{ kind: 'overhang', id: 'o1' }],
      surfaceAnchors: [{ kind: 'domain', strandId: 's1', domainIndex: 0 }],
      surfaceStrands: { enabled: true, subjectToField: false },
    })).toEqual({
      job_id: 'selected',
      field: { field_pN: 7, dir: [1, 0, 0] },
      surface: { dir: [0, 0, 1], offset_nm: 2, position_nm: -4, stiff: 5 },
      anchors: [{ kind: 'overhang', id: 'o1' }],
      surface_anchors: [{ kind: 'domain', strandId: 's1', domainIndex: 0 }],
      surface_strands: { enabled: true, subjectToField: false },
    })
  })
})

describe('initOxdnaLive factory', () => {
  let els, display, job, field, surface, anchors, surfaceAnchors

  function make() {
    return initOxdnaLive({
      oxdnaDisplay: display,
      getSelectedJob: () => job,
      getRunElements: () => ({ field, surface, anchors, surfaceAnchors }),
    })
  }

  beforeEach(() => {
    els = mountIds(IDS)
    display = makeDisplay()
    job = { job_id: 'j1', status: 'completed' }
    field = { enabled: true, field_pN: 4, dir: [0, 1, 0] }
    surface = { enabled: false }
    anchors = [{ kind: 'overhang', id: 'o1' }]
    surfaceAnchors = [{ kind: 'domain', strandId: 's1', domainIndex: 0 }]
    api.oxdnaLiveAvailable.mockResolvedValue({ available: true, reason: 'ready' })
    api.startOxdnaLive.mockResolvedValue({ session_id: 's1', status: 'starting' })
    api.getOxdnaLiveFrame.mockResolvedValue({ ready: false, status: 'starting', positions: [], n_positions: 0, n_bursts: 0 })
    api.stopOxdnaLive.mockResolvedValue({ ok: true, stopped: true })
    api.updateOxdnaLiveField.mockResolvedValue({ ok: true })
    api.reconfigureOxdnaLive.mockResolvedValue({ ok: true })
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
      expect.objectContaining({
        job_id: 'j1',
        field: { field_pN: 4, dir: [0, 1, 0] },
        anchors,
        surface_anchors: surfaceAnchors,
      }))
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

  it('starts a FIELD without an anchor (COM-drift is warned, not blocked)', async () => {
    anchors = []                               // field enabled, no anchor
    const ctl = make()
    await flush()
    ctl.toggle()
    await flush()
    expect(api.startOxdnaLive).toHaveBeenCalled()
    const body = api.startOxdnaLive.mock.calls[0][0]
    expect(body.field).toEqual({ field_pN: 4, dir: [0, 1, 0] })
    expect(body.anchors).toBeUndefined()       // empty → omitted
    expect(ctl.isOn()).toBe(true)
    ctl.stop()
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

  it('recomposes the live run (seamless) when the floor is toggled on mid-session', async () => {
    field = { enabled: false, field_pN: 0, dir: [0, 1, 0] }   // start without a field
    surface = { enabled: false }
    const ctl = make()
    await flush()
    ctl.toggle()                                              // start (anchors-only)
    await flush()
    expect(ctl.isOn()).toBe(true)

    surface = { enabled: true, dir: [0, 0, 1], offsetNm: 0, stiff: 1 }
    ctl.onElementsChanged()
    expect(api.reconfigureOxdnaLive).not.toHaveBeenCalled()   // debounced — not yet
    await wait(420)
    expect(api.reconfigureOxdnaLive).toHaveBeenCalledWith('s1',
      expect.objectContaining({ surface: { dir: [0, 0, 1], offset_nm: 0, stiff: 1 } }))
    ctl.stop()
  })

  it('recomposes when the E-field is enabled after a fieldless start', async () => {
    field = { enabled: false, field_pN: 0, dir: [0, 1, 0] }
    const ctl = make()
    await flush()
    ctl.toggle()
    await flush()
    field = { enabled: true, field_pN: 5, dir: [1, 0, 0] }    // anchors (o1) still present
    ctl.onElementsChanged()
    await wait(420)
    expect(api.reconfigureOxdnaLive).toHaveBeenCalledWith('s1',
      expect.objectContaining({ field: { field_pN: 5, dir: [1, 0, 0] } }))
    ctl.stop()
  })

  it('re-aims a field magnitude change in place — it does NOT recompose', async () => {
    const ctl = make()                                        // field on by default
    await flush()
    ctl.toggle()
    await flush()
    field = { enabled: true, field_pN: 12, dir: [0, 1, 0] }   // same composition, new magnitude
    ctl.onElementsChanged()
    expect(api.updateOxdnaLiveField).toHaveBeenCalledWith('s1', { field_pN: 12, dir: [0, 1, 0] })
    await wait(420)
    expect(api.reconfigureOxdnaLive).not.toHaveBeenCalled()
    ctl.stop()
  })

  it('aborts start when the stale-design guard cancels (no session started)', async () => {
    const ensureJobCurrent = vi.fn().mockResolvedValue(false)
    const ctl = initOxdnaLive({
      oxdnaDisplay: display, getSelectedJob: () => job,
      getRunElements: () => ({ field, surface, anchors }), ensureJobCurrent,
    })
    await flush()
    ctl.toggle()                       // attempt start
    await flush()
    expect(ensureJobCurrent).toHaveBeenCalledWith('a live session')
    expect(api.startOxdnaLive).not.toHaveBeenCalled()
    expect(ctl.isOn()).toBe(false)
  })

  it('proceeds with start when the stale-design guard passes', async () => {
    const ensureJobCurrent = vi.fn().mockResolvedValue(true)
    const ctl = initOxdnaLive({
      oxdnaDisplay: display, getSelectedJob: () => job,
      getRunElements: () => ({ field, surface, anchors }), ensureJobCurrent,
    })
    await flush()
    ctl.toggle()
    await flush()
    expect(ensureJobCurrent).toHaveBeenCalled()
    expect(api.startOxdnaLive).toHaveBeenCalled()
    expect(ctl.isOn()).toBe(true)
    ctl.stop()
  })

  it('recomposes into a field with no anchor (COM-drift is warned, not blocked)', async () => {
    field = { enabled: false, field_pN: 0, dir: [0, 1, 0] }
    anchors = []
    const ctl = make()
    await flush()
    ctl.toggle()                                              // free dynamics
    await flush()
    field = { enabled: true, field_pN: 5, dir: [1, 0, 0] }    // enabling field, still no anchor
    ctl.onElementsChanged()
    await wait(420)
    expect(api.reconfigureOxdnaLive).toHaveBeenCalledWith('s1',
      expect.objectContaining({ field: { field_pN: 5, dir: [1, 0, 0] } }))
    ctl.stop()
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
