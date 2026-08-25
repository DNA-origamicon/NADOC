/**
 * md_panel.test.js — representation-persistence of the live "Display MD" controller.
 *
 * The controller stops a live display through THREE entry points (`stopDisplayKeepWarm`,
 * `stopAndRestore`, and the WebSocket `onclose`), all of which funnel into the private
 * `_restoreDesign`.  The invariant these tests pin: stopping a display must revert to the
 * design's equilibrium pose WITHOUT changing the user's chosen scene representation —
 * an atomistic/surface scene must NOT fall back to the CG bead-and-slab model (the bug),
 * and a CG scene must show the native design.
 *
 * We drive the real factory with mock renderers + a stubbed scene representation (set via
 * the `nadoc:representation-change` event the panel already listens to), and assert which
 * renderer calls fire on stop.  DOM is the minimal by-id set the factory touches unguarded.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initMdPanel } from './md_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

function setSceneRepr(repr) {
  window.dispatchEvent(new CustomEvent('nadoc:representation-change', {
    detail: { representation: repr },
  }))
}

function makeDeps() {
  return {
    designRenderer: {
      setDesignVisible: vi.fn(),
      applyFemPositions: vi.fn(),
    },
    mdOverlay: { dispose: vi.fn() },
    atomisticRenderer: {
      setMode: vi.fn(),
      getMode: vi.fn(() => 'ballstick'),
      update: vi.fn(),
    },
    onRestoreDesignHeavy: vi.fn(),
  }
}

let store, deps, ctrl, dom

beforeEach(() => {
  dom = mountIds({
    'md-panel': 'div',
    'md-panel-heading': 'div',
    'md-panel-body': 'div',
    'md-panel-arrow': 'div',
    'md-show-nadoc': 'input',
  })
  dom['md-show-nadoc'].type = 'checkbox'
  store = createMockStore({ currentDesign: { id: 'd1' } })
  deps = makeDeps()
  ctrl = initMdPanel(store, deps)
})

afterEach(() => clearDom())

// Both explicit stop entry points funnel into the same _restoreDesign; assert both.
for (const stop of ['stopDisplayKeepWarm', 'stopAndRestore']) {
  describe(`${stop} — representation persists`, () => {
    it('atomistic scene: keeps the heavy rep (rebuild), never shows native CG beads', () => {
      setSceneRepr('ballstick')
      deps.designRenderer.setDesignVisible.mockClear()
      deps.atomisticRenderer.setMode.mockClear()

      ctrl[stop]()

      // The chosen atomistic rep is rebuilt from the design at equilibrium…
      expect(deps.onRestoreDesignHeavy).toHaveBeenCalledTimes(1)
      // …the CG bead design stays hidden…
      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(false)
      expect(deps.designRenderer.setDesignVisible).not.toHaveBeenCalledWith(true)
      // …and the atomistic renderer is NOT turned off (that was the revert bug).
      expect(deps.atomisticRenderer.setMode).not.toHaveBeenCalledWith('off')
      // MD-displaced positions are always dropped.
      expect(deps.designRenderer.applyFemPositions).toHaveBeenCalledWith(null)
    })

    it('surface scene: keeps the heavy rep (rebuild), hides native CG beads', () => {
      setSceneRepr('surface')
      deps.designRenderer.setDesignVisible.mockClear()

      ctrl[stop]()

      expect(deps.onRestoreDesignHeavy).toHaveBeenCalledTimes(1)
      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(false)
      expect(deps.designRenderer.setDesignVisible).not.toHaveBeenCalledWith(true)
    })

    it('CG scene (full): shows the native design, turns atomistic off, no heavy rebuild', () => {
      setSceneRepr('full')
      deps.designRenderer.setDesignVisible.mockClear()
      deps.atomisticRenderer.setMode.mockClear()

      ctrl[stop]()

      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(true)
      expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('off')
      expect(deps.onRestoreDesignHeavy).not.toHaveBeenCalled()
    })

    it('hull-prism scene: treated as a design-renderer CG rep (native shown, no heavy rebuild)', () => {
      // hull-prism is drawn by the design renderer, so stopping must show the native
      // design — NOT hide it as if it were a heavy rep.
      setSceneRepr('hull-prism')
      deps.designRenderer.setDesignVisible.mockClear()

      ctrl[stop]()

      expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(true)
      expect(deps.onRestoreDesignHeavy).not.toHaveBeenCalled()
    })
  })
}

describe('representation switch while stopped keeps the scene repr in sync', () => {
  it('a later stop reflects the most-recent representation choice', () => {
    // Start atomistic, switch to CG, then stop → CG behaviour (native shown).
    setSceneRepr('ballstick')
    setSceneRepr('full')
    ctrl.stopDisplayKeepWarm()
    expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(true)
    expect(deps.onRestoreDesignHeavy).not.toHaveBeenCalled()
  })
})

// ── Live solvent side-channel ────────────────────────────────────────────────
//
// The solvent/periodic-cell payload arrives as BINARY next to the JSON frames (a
// whole-cell frame is millions of coordinates). This panel owns the socket but not
// the overlay, so its whole job is to route ArrayBuffers straight back out, and to
// replay the request when the socket is rebuilt — a representation change tears the
// socket down and the overlay must not silently go dark because of it.
describe('live solvent side-channel', () => {
  let sockets, RealWS

  class MockSocket {
    static OPEN = 1
    constructor(url) {
      this.url = url
      this.readyState = 0
      this.sent = []
      sockets.push(this)
    }

    send(s) { this.sent.push(JSON.parse(s)) }
    close() { this.readyState = 3 }

    /** Pretend the handshake completed. */
    open() { this.readyState = 1; this.onopen?.() }

    actions() { return this.sent.map((m) => m.action) }
    lastOf(action) { return [...this.sent].reverse().find((m) => m.action === action) }
  }

  beforeEach(() => {
    sockets = []
    RealWS = globalThis.WebSocket
    globalThis.WebSocket = MockSocket
    globalThis.WebSocket.OPEN = 1
    globalThis.WebSocket.CONNECTING = 0
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    globalThis.WebSocket = RealWS
  })

  /** Open a socket and complete its handshake. `_openWebSocket` debounces by
   *  120 ms to coalesce bursty reopens, so the timers have to be advanced. */
  function connected(extraDeps = {}) {
    const c = initMdPanel(store, { ...makeDeps(), ...extraDeps })
    c.displayLatest('/tmp/run.json', { forceReload: true, live: true, jobId: 'j1' })
    vi.advanceTimersByTime(200)
    const ws = sockets.at(-1)
    ws.open()
    return { c, ws }
  }

  it('sends set_solvent over an open socket', () => {
    const { c, ws } = connected()
    expect(c.setSolvent({ water: true, ions: true, box: false, shell_ang: 5 })).toBe(true)
    const msg = ws.lastOf('set_solvent')
    expect(msg).toMatchObject({ water: true, ions: true, box: false, shell_ang: 5 })
  })

  // Turning the overlay off must be an explicit all-false request, not silence —
  // the server keeps streaming solvent until told otherwise.
  it('sends an explicit all-false request when switched off', () => {
    const { c, ws } = connected()
    c.setSolvent(null)
    expect(ws.lastOf('set_solvent')).toMatchObject({ water: false, ions: false, box: false })
  })

  it('remembers the request and replays it on reconnect', () => {
    const { c } = connected()
    c.setSolvent({ water: true, ions: false, box: true })
    // A representation change rebuilds the socket; the new one must re-request.
    setSceneRepr('ballstick')
    c.displayLatest('/tmp/run.json', { forceReload: true, live: true, jobId: 'j1' })
    vi.advanceTimersByTime(200)
    const fresh = sockets.at(-1)
    expect(fresh).not.toBe(sockets[0])
    expect(fresh.actions()).not.toContain('set_solvent')   // nothing sent pre-handshake
    fresh.open()
    expect(fresh.lastOf('set_solvent')).toMatchObject({ water: true, box: true })
  })

  it('force-reloads an open socket when the refreshed DCD keeps the same path', () => {
    const { c, ws: old } = connected()
    expect(sockets).toHaveLength(1)

    c.displayLatest('/tmp/run.json', { forceReload: true, live: false, jobId: 'j1' })
    vi.advanceTimersByTime(200)

    expect(sockets).toHaveLength(2)
    expect(old.readyState).toBe(3)
    const fresh = sockets.at(-1)
    fresh.open()
    expect(fresh.lastOf('load')).toMatchObject({
      config_path: '/tmp/run.json',
      job_id: 'j1',
    })
  })

  it('reapplies the last downloaded frame on toggle-on without reopening', () => {
    const applyFemPositions = vi.fn()
    const states = []
    const processes = []
    const onState = e => states.push(e.detail)
    const onProcess = e => processes.push(e.detail)
    window.addEventListener('nadoc:md-display-state', onState)
    window.addEventListener('nadoc:md-display-process', onProcess)
    const { c, ws } = connected({
      designRenderer: {
        setDesignVisible: vi.fn(),
        applyFemPositions,
      },
    })
    ws.onmessage({ data: JSON.stringify({
      type: 'ready', n_frames: 1, n_p_atoms: 1,
      dt_ps: 0.004, nstxout_comp: 5000,
    }) })
    const frame = {
      type: 'frame', frame_idx: 0, n_frames: 1,
      positions: [{ helix_id: 'h1', bp_index: 0, direction: 'FORWARD', x: 1, y: 2, z: 3 }],
    }
    ws.onmessage({ data: JSON.stringify(frame) })
    applyFemPositions.mockClear()

    expect(c.stopDisplayKeepWarm()).toBe(true)
    applyFemPositions.mockClear() // ignore the toggle-off equilibrium restore
    c.displayLatest('/tmp/run.json', { forceReload: false, live: false, jobId: 'j1' })

    expect(sockets).toHaveLength(1)
    expect(applyFemPositions).toHaveBeenCalledTimes(1)
    expect(applyFemPositions.mock.calls[0][0]).toEqual([
      expect.objectContaining({
        helix_id: 'h1', bp_index: 0, direction: 'FORWARD',
        backbone_position: [1, 2, 3],
      }),
    ])
    expect(processes.at(-1)).toMatchObject({
      phase: 'frame-applied', jobId: 'j1', source: 'memory-cache',
    })
    expect(states.at(-1)).toMatchObject({
      state: 'frame', jobId: 'j1', source: 'memory-cache',
    })
    window.removeEventListener('nadoc:md-display-state', onState)
    window.removeEventListener('nadoc:md-display-process', onProcess)
  })

  it('does not send anything when the overlay was never turned on', () => {
    const { ws } = connected()
    expect(ws.actions()).not.toContain('set_solvent')
  })

  it('reports false when there is no open socket to send on', () => {
    const c = initMdPanel(store, makeDeps())
    expect(c.setSolvent({ water: true, ions: true, box: true })).toBe(false)
  })

  // A binary message must reach the overlay sink and must NEVER reach the JSON
  // frame handler — JSON.parse on an ArrayBuffer yields garbage, not an error.
  it('routes a binary message to onSolventBlob', () => {
    const onSolventBlob = vi.fn()
    const { ws } = connected({ onSolventBlob })
    const buf = new ArrayBuffer(32)
    ws.onmessage({ data: buf })
    expect(onSolventBlob).toHaveBeenCalledWith(buf)
  })

  it('still routes JSON messages to the frame handler', () => {
    const onSolventBlob = vi.fn()
    const { ws } = connected({ onSolventBlob })
    ws.onmessage({ data: JSON.stringify({ type: 'log', message: 'hi' }) })
    expect(onSolventBlob).not.toHaveBeenCalled()
  })

  it('asks for arraybuffer framing, not blobs', () => {
    const { ws } = connected()
    expect(ws.binaryType).toBe('arraybuffer')
  })

  it('negotiates and applies a topology-stable binary atom frame', () => {
    const localDeps = makeDeps()
    localDeps.atomisticRenderer.updateFrame = vi.fn(() => 'incremental')
    const { c } = connected(localDeps)

    // Entering an atomistic scene rebuilds the stream with binary negotiation.
    setSceneRepr('ballstick')
    vi.advanceTimersByTime(200)
    const ws = sockets.at(-1)
    ws.open()
    expect(ws.lastOf('load')).toMatchObject({
      mode: 'ballstick', binary_atom_frames: true,
    })
    ws.onmessage({ data: JSON.stringify({
      type: 'ready', n_frames: 8, binary_atom_frames: true,
      atom_serials: [10, 21], atom_elements: ['P', 'C'], atom_bonds: [10, 21],
      atom_ident: {
        strands: ['s0'], helices: ['h0'], dirs: ['FORWARD'],
        strand_idx: [0, 0], helix_idx: [0, 0], dir_idx: [0, 0], bp: [3, 3],
        names: ['P', "C1'"], copy_k: [0, 0],
        scalar_keys: ['h0:3:FORWARD:0', 'h0:3:FORWARD:0'],
        base_keys: ['h0:3:FORWARD', 'h0:3:FORWARD'],
      },
    }) })

    const buffer = new ArrayBuffer(36 + 2 * 12)
    const bytes = new Uint8Array(buffer)
    bytes.set([...'NADOCMDA'].map(c => c.charCodeAt(0)))
    const view = new DataView(buffer)
    view.setUint32(8, 1, true); view.setUint32(12, 36, true)
    view.setUint32(16, 4, true); view.setUint32(20, 8, true)
    view.setUint32(24, 2, true); view.setFloat64(28, 80, true)
    new Float32Array(buffer, 36).set([1, 4, 2, 5, 3, 6])
    ws.onmessage({ data: buffer })

    expect(localDeps.atomisticRenderer.updateFrame).toHaveBeenCalledTimes(1)
    const payload = localDeps.atomisticRenderer.updateFrame.mock.calls[0][0]
    expect(payload).toMatchObject({ columnar: true, count: 2 })
    expect(Array.from(payload.bonds)).toEqual([10, 21])
    expect(Array.from(payload.serial)).toEqual([10, 21])
    expect(Array.from(payload.x)).toEqual([1, 4])
    expect(Array.from(payload.y)).toEqual([2, 5])
    expect(Array.from(payload.z)).toEqual([3, 6])
    expect(c.trajectoryState()).toMatchObject({ frame_idx: 4, n_frames: 8 })
  })

  it('scopes display events to the job and ignores messages drained from an old socket', () => {
    const seen = []
    const onState = e => seen.push(e.detail)
    window.addEventListener('nadoc:md-display-state', onState)
    try {
      const { c, ws: old } = connected()
      expect(seen.at(-1)).toMatchObject({ state: 'loading', jobId: 'j1' })

      c.displayLatest('/tmp/run.json', { forceReload: true, live: true, jobId: 'parent' })
      vi.advanceTimersByTime(200)
      const fresh = sockets.at(-1)
      fresh.open()
      expect(seen.at(-1)).toMatchObject({ state: 'loading', jobId: 'parent' })

      const before = seen.length
      old.onmessage?.({ data: JSON.stringify({ type: 'error', message: 'stale child error' }) })
      expect(seen).toHaveLength(before)
    } finally {
      window.removeEventListener('nadoc:md-display-state', onState)
    }
  })

  it('signals prewarmed only after the requested frame is cached without applying it', () => {
    const seen = []
    const processes = []
    const onState = e => seen.push(e.detail)
    const onProcess = e => processes.push(e.detail)
    window.addEventListener('nadoc:md-display-state', onState)
    window.addEventListener('nadoc:md-display-process', onProcess)
    try {
      const localDeps = makeDeps()
      const c = initMdPanel(store, localDeps)
      c.prewarmLatest('/tmp/run.json', { forceReload: true, jobId: 'alpine-r1' })
      vi.advanceTimersByTime(200)
      const ws = sockets.at(-1)
      ws.open()
      ws.onmessage({ data: JSON.stringify({ type: 'ready', n_frames: 1 }) })
      expect(seen.some(e => e.state === 'prewarmed')).toBe(false)
      expect(seen.at(-1)).toMatchObject({
        state: 'topology-ready', jobId: 'alpine-r1',
      })

      ws.onmessage({ data: JSON.stringify({
        type: 'frame', frame_idx: 0, n_frames: 1,
        positions: [{ helix_id: 'h1', bp_index: 0, direction: 'FORWARD', x: 1, y: 2, z: 3 }],
      }) })

      expect(seen.at(-1)).toMatchObject({ state: 'prewarmed', jobId: 'alpine-r1' })
      expect(processes.some(e => e.phase === 'frame-cached')).toBe(true)
      expect(localDeps.designRenderer.applyFemPositions).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('nadoc:md-display-state', onState)
      window.removeEventListener('nadoc:md-display-process', onProcess)
    }
  })

  it('applies sequenced VR play/pause/seek commands to the desktop timeline', () => {
    const trajectoryEvents = []
    const localDeps = makeDeps()
    let frameApplied = false
    localDeps.designRenderer.applyFemPositions.mockImplementation(() => {
      frameApplied = true
    })
    const onTrajectory = event => {
      if (event.detail.coordinatesReady) expect(frameApplied).toBe(true)
      trajectoryEvents.push(event.detail)
    }
    window.addEventListener('nadoc:md-trajectory-state', onTrajectory)
    try {
      const c = initMdPanel(store, localDeps)
      c.displayLatest('/tmp/run.json', { forceReload: true, live: false, jobId: 'run-1' })
      vi.advanceTimersByTime(200)
      const ws = sockets.at(-1)
      ws.open()
      ws.onmessage({ data: JSON.stringify({
        type: 'ready', n_frames: 20, dt_ps: 2, nstxout_comp: 10,
      }) })
      ws.onmessage({ data: JSON.stringify({
        type: 'frame', frame_idx: 0, n_frames: 20,
        positions: [{ helix_id: 'h1', bp_index: 0, direction: 'FORWARD', x: 1, y: 2, z: 3 }],
      }) })

      expect(c.trajectoryState()).toMatchObject({
        active: true, frame_idx: 0, n_frames: 20, playing: false,
      })
      expect(trajectoryEvents.at(-1)).toMatchObject({
        frame_idx: 0, coordinatesReady: true,
      })

      expect(c.applyTrajectoryCommand({ action: 'seek', frameIdx: 7 })).toBe(true)
      expect(ws.lastOf('seek')).toEqual({ action: 'seek', frame_idx: 7 })
      expect(c.trajectoryState()).toMatchObject({ frame_idx: 7, playing: false })
      expect(trajectoryEvents.at(-1)).toMatchObject({
        frame_idx: 7, coordinatesReady: false,
      })

      expect(c.applyTrajectoryCommand({ action: 'play' })).toBe(true)
      expect(c.trajectoryState().playing).toBe(true)
      expect(c.applyTrajectoryCommand({ action: 'pause' })).toBe(true)
      expect(c.trajectoryState().playing).toBe(false)
    } finally {
      window.removeEventListener('nadoc:md-trajectory-state', onTrajectory)
    }
  })
})

// ── Rep-switch progress signal ───────────────────────────────────────────────
//
// Switching representation while a live display is up changes the WIRE FORMAT, so the
// socket is torn down and reloaded (re-parsing the PSF — seconds on a big system). Two
// changes conspire to make that window invisible: atom_surface_display now defers its own
// design build to this controller, so it shows none of its own toast; and the previous
// geometry is deliberately left on screen until the new frame lands. Without a signal the
// user presses F7 and nothing at all happens for several seconds.
describe('rep-switch progress signal', () => {
  let sockets, RealWS, seen

  class MockSocket {
    static OPEN = 1
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this) }
    send(s) { this.sent.push(JSON.parse(s)) }
    close() { this.readyState = 3 }
    open() { this.readyState = 1; this.onopen?.() }
    msg(o) { this.onmessage?.({ data: JSON.stringify(o) }) }
  }

  const onHeavy = (e) => seen.push(e.detail)

  beforeEach(() => {
    sockets = []; seen = []
    RealWS = globalThis.WebSocket
    globalThis.WebSocket = MockSocket
    globalThis.WebSocket.OPEN = 1
    globalThis.WebSocket.CONNECTING = 0
    window.addEventListener('nadoc:md-heavy-status', onHeavy)
    vi.useFakeTimers()
  })
  afterEach(() => {
    window.removeEventListener('nadoc:md-heavy-status', onHeavy)
    vi.useRealTimers()
    globalThis.WebSocket = RealWS
  })

  function live() {
    const c = initMdPanel(store, deps)
    c.displayLatest('/tmp/run.json', { forceReload: true, live: true, jobId: 'j1' })
    vi.advanceTimersByTime(200)
    sockets.at(-1).open()
    seen.length = 0
    return c
  }

  // requestAnimationFrame is how the listener defers past the renderer's own rebuild.
  const flushRaf = () => { vi.advanceTimersByTime(50) }

  it('announces the wait when CG → atomistic reloads the socket', () => {
    live()
    setSceneRepr('ballstick')
    flushRaf()
    expect(seen).toContainEqual(expect.objectContaining({ kind: 'atomistic', building: true }))
  })

  it('keeps CG visible during an ordinary CG → atomistic payload reload', () => {
    const c = live()
    deps.designRenderer.setDesignVisible.mockClear()

    setSceneRepr('ballstick')

    expect(deps.designRenderer.setDesignVisible).not.toHaveBeenCalledWith(false)
    expect(c.renderedRepresentation()).toBe('full')
    flushRaf()
    const atomWs = sockets.at(-1); atomWs.open()
    atomWs.msg({ type: 'ready', n_frames: 1 })
    atomWs.msg({ type: 'frame', frame_idx: 0, n_frames: 1, atoms: [] })
    expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(false)
    expect(c.renderedRepresentation()).toBe('ballstick')
  })

  // The reverse direction refreshes the authoritative coarse payload while holding
  // the atomistic renderer on screen.
  it('announces the wait when atomistic → CG reloads the socket', () => {
    const c = live()
    setSceneRepr('ballstick'); flushRaf()
    sockets.at(-1).open()
    seen.length = 0
    setSceneRepr('full'); flushRaf()
    expect(seen).toContainEqual(expect.objectContaining({ kind: 'cg', building: true }))
    expect(c).toBeTruthy()
  })

  it('holds atomistic → CG until the authoritative coarse frame is applied', () => {
    const c = live()
    setSceneRepr('ballstick'); flushRaf()
    const atomWs = sockets.at(-1); atomWs.open()
    atomWs.msg({
      type: 'ready', n_frames: 20, atom_ident: {
        strands: ['s'], helices: ['h0'], dirs: ['FORWARD'],
        strand_idx: [0, 0], helix_idx: [0, 0], dir_idx: [0, 0], bp: [3, 3],
      },
    })
    atomWs.msg({
      type: 'frame', frame_idx: 17, n_frames: 20,
      atoms: [
        { serial: 0, element: 'P', x: 8, y: 9, z: 10 },
        { serial: 1, element: 'C', x: 9, y: 9, z: 10 },
      ],
    })
    deps.designRenderer.applyFemPositions.mockClear()
    deps.designRenderer.setDesignVisible.mockClear()
    deps.atomisticRenderer.setMode.mockClear()

    setSceneRepr('full')

    expect(deps.designRenderer.applyFemPositions).not.toHaveBeenCalled()
    expect(deps.designRenderer.setDesignVisible).toHaveBeenCalledWith(false)
    expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('ballstick')
    expect(c.renderedRepresentation()).toBe('ballstick')

    flushRaf()
    const cgWs = sockets.at(-1); cgWs.open()
    cgWs.msg({ type: 'ready', n_frames: 20 })
    cgWs.msg({
      type: 'frame', frame_idx: 17, n_frames: 20,
      positions: [{
        helix_id: 'h0', bp_index: 3, direction: 'FORWARD',
        x: 1, y: 2, z: 3, bx: 4, by: 5, bz: 6,
        nx: 0, ny: 1, nz: 0, tx: 1, ty: 0, tz: 0,
      }],
    })
    expect(deps.designRenderer.applyFemPositions).toHaveBeenCalledWith([
      expect.objectContaining({
        backbone_position: [1, 2, 3], base_position: [4, 5, 6],
        nx: 0, ny: 1, nz: 0, tx: 1, ty: 0, tz: 0,
      }),
    ], 1)
    expect(deps.atomisticRenderer.setMode).toHaveBeenLastCalledWith('off')
    expect(deps.designRenderer.setDesignVisible).toHaveBeenLastCalledWith(true)
    expect(c.renderedRepresentation()).toBe('full')
  })

  it('clears it when a frame in the new format lands', () => {
    live()
    setSceneRepr('ballstick'); flushRaf()
    const ws = sockets.at(-1); ws.open()
    ws.msg({ type: 'frame', frame_idx: 0, n_frames: 10, atoms: [] })
    expect(seen.at(-1)).toMatchObject({ building: false })
  })

  // A dead load must not strand a persistent toast over the app forever.
  it('clears it when the load errors', () => {
    live()
    setSceneRepr('ballstick'); flushRaf()
    const ws = sockets.at(-1); ws.open()
    ws.msg({ type: 'error', message: 'no such config' })
    expect(seen.at(-1)).toMatchObject({ building: false })
  })

  it('clears it when the display is stopped mid-switch', () => {
    const c = live()
    setSceneRepr('ballstick'); flushRaf()
    seen.length = 0
    c.stopAndRestore()
    expect(seen).toContainEqual(expect.objectContaining({ building: false }))
  })

  // Only the rep-switch reload is announced. _openWebSocket runs for many other reasons
  // and toasting all of them would flash on every 5 s live poll.
  it('stays silent on a same-format reload', () => {
    const c = live()
    c.displayLatest('/tmp/run.json', { forceReload: true, live: true, jobId: 'j1' })
    vi.advanceTimersByTime(200)
    expect(seen.filter(d => d.building)).toEqual([])
  })
})
