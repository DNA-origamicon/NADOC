/**
 * Phase-weighted progress for animation video/GIF export.
 *
 * WHY THIS EXISTS
 * ---------------
 * Exporting a trajectory animation at photo quality is the longest thing NADOC
 * does in the browser. On VoltronCoreScad + a full-resolution oxDNA trajectory
 * keyframe in surface representation the wall-clock breaks down roughly as:
 *
 *   player.play()  →  geometry batch fetch        (seconds)
 *                  →  trajectory download          (minutes — 1 GB .dat server-side)
 *                  →  surface frame prebuild       (minutes — 251 meshes)
 *   beginFrameSession()                            (seconds — probe GL, shadow map, passes)
 *   per-frame capture                              (many minutes — tiled render + quantize)
 *   gif.finish() + Blob + download                 (tens of seconds — hundreds of MB)
 *
 * Before this module only the per-frame capture loop reported anything, and the
 * op-progress popup sat at "Preparing…" 0% for everything ahead of it. The user
 * has no way to tell that apart from a hang, so they cancel and retry — which
 * throws away the download and starts the same wait over.
 *
 * The contract this module enforces:
 *
 *   1. EVERY subprocess owns a named slice of the single 0→1 export bar. There is
 *      no unaccounted-for time: the phase list covers the whole run end to end.
 *   2. The overall fraction is MONOTONIC. A phase that never reports (no trajectory
 *      in this animation, CG rep so nothing to prebuild) is jumped over when the
 *      next phase begins — the bar moves forward, never back, never sticks.
 *   3. The status line ALWAYS names the subprocess currently running, as
 *      "Step k/n · <what it is doing> <done> of <total>".
 *   4. When a subprocess goes quiet longer than `stallMs`, the label grows an
 *      elapsed-time tail so the text keeps changing. A frozen label reads as a
 *      hang even when the bar is honest about being mid-phase.
 *
 * Everything except `createExportSession`'s default `ui`/`timer` bindings is pure
 * and unit-tested in `export_progress.test.js`.
 */

import {
  showOpProgress, hideOpProgress, setOpProgressLabel, setOpProgressFraction,
} from '../ui/op_progress.js'

/** Human text for each phase key, in the order the phases run. */
export const PHASE_LABELS = {
  prepare:     'Preparing export',
  geometry:    'Fetching model geometry',
  traj_load:   'Downloading trajectory',
  traj_frames: 'Building trajectory frames',
  session:     'Setting up render passes',
  capture:     'Rendering frames',
  encode:      'Encoding video',
  save:        'Writing file',
}

/**
 * Phases that hand the main thread to a single blocking call, so the tab really does
 * freeze for a stretch — no timer fires, so not even the heartbeat can tick through it.
 *
 * Measured in the app on VoltronCoreScad + oxDNA run 17: the ~50 MB trajectory response
 * body blocks `r.json()` for 7 s in a bead representation and 18 s with the surface rep
 * loaded. Nothing at this layer can shorten that (the fix would be parsing off-thread),
 * but a freeze the user was WARNED about is a wait; an unannounced one is a hang. The
 * hint is appended only once the phase has already gone quiet.
 */
export const PHASE_HINTS = {
  traj_load: 'the tab may stop responding while the data is unpacked',
  encode:    'the tab may stop responding while the file is assembled',
}

/**
 * Relative cost of each phase. These are deliberately coarse — their only job is
 * to keep the bar from spending 95% of the run in one slice. Measured against the
 * VoltronCoreScad / oxDNA-run-17 / surface / GIF workflow, which is the worst case.
 */
export const PHASE_WEIGHTS = {
  prepare:     1,
  geometry:    4,
  traj_load:  14,
  traj_frames: 24,
  session:     3,
  capture:    41,
  encode:     11,
  save:        2,
}

/** Canonical phase order. `planExportPhases` filters this, never reorders it. */
export const PHASE_ORDER = [
  'prepare', 'geometry', 'traj_load', 'traj_frames',
  'session', 'capture', 'encode', 'save',
]

/**
 * Build the phase list for one export run.
 *
 * Phases that cannot happen are dropped rather than left to be skipped, so their
 * weight is redistributed and the bar's pace matches the work actually queued.
 *
 * @param {object}  [spec]
 * @param {boolean} [spec.hasTrajectory]  animation references ≥1 trajectory keyframe
 * @param {boolean} [spec.hasHeavyFrames] a heavy rep (surface/atomistic) is visible,
 *                                        so trajectory frames must be prebuilt
 * @param {string}  [spec.format]         'gif' | 'webm' — names the encode phase
 * @returns {Array<{key:string,label:string,weight:number}>} weights summing to 1
 */
export function planExportPhases({
  hasTrajectory = false, hasHeavyFrames = false, format = 'webm',
} = {}) {
  const keys = PHASE_ORDER.filter((k) => {
    if (k === 'traj_load')   return hasTrajectory
    // The heavy prebuild is a no-op in a bead representation (oxdna_display's
    // prebuildHeavy returns immediately for kind 'cg'), so it earns no slice.
    if (k === 'traj_frames') return hasTrajectory && hasHeavyFrames
    return true
  })
  const total = keys.reduce((s, k) => s + PHASE_WEIGHTS[k], 0)
  return keys.map(k => ({
    key:    k,
    label:  k === 'encode'
      ? `Encoding ${format === 'gif' ? 'GIF' : 'WebM'}`
      : PHASE_LABELS[k],
    weight: PHASE_WEIGHTS[k] / total,
    hint:   PHASE_HINTS[k] ?? null,
  }))
}

/** `95_000` → `"1:35"`. Minutes:seconds, no hours (an export past an hour is a bug). */
export function elapsedText(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/**
 * Compose the status line shown above the bar.
 *
 * Always names the phase; adds an `x of y` count when the phase can count, and an
 * elapsed tail once the phase has been quiet for `stallMs` so the text still moves
 * during an opaque await (a trajectory download reports nothing until it lands).
 */
export function phaseStatusText({
  label, phaseIndex, phaseCount, done = null, total = null,
  idleMs = 0, stallMs = 2500, hint = null,
}) {
  let out = `Step ${phaseIndex + 1}/${phaseCount} · ${label}`
  if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
    out += ` ${Math.min(done, total)} of ${total}`
  }
  if (idleMs >= stallMs) {
    out += ` · still working, ${elapsedText(idleMs)} elapsed`
    if (hint) out += ` — ${hint}`
  }
  return out
}

/**
 * The monotonic phase accumulator. Pure apart from the injected clock.
 *
 * @param {object}   opts
 * @param {Array}    opts.phases     from `planExportPhases`
 * @param {function} [opts.onUpdate] ({key,label,text,fraction,phaseIndex,phaseCount,done,total})
 * @param {function} [opts.now]      ms clock, injectable for tests
 * @param {number}   [opts.stallMs]  quiet time before the elapsed tail appears
 */
export function createExportProgress({ phases, onUpdate = null, now = () => Date.now(), stallMs = 2500 } = {}) {
  if (!phases?.length) throw new Error('createExportProgress: phases required')

  // Prefix sums so overall = cum(i) + weight(i) * phaseFraction.
  const cum = []
  let acc = 0
  for (const p of phases) { cum.push(acc); acc += p.weight }

  let _i        = 0      // current phase index
  let _frac     = 0      // fraction within the current phase
  let _reported = 0      // last overall fraction emitted (monotonic clamp)
  let _done     = null
  let _total    = null
  let _lastMs   = now()  // last time anything actually moved
  let _finished = false

  const _indexOf = (key) => phases.findIndex(p => p.key === key)

  function _overall() {
    return Math.max(_reported, Math.min(1, cum[_i] + phases[_i].weight * _frac))
  }

  function _emit(idleMs = 0) {
    _reported = _overall()
    const ph = phases[_i]
    const text = _finished
      ? 'Done'
      : phaseStatusText({
          label: ph.label, phaseIndex: _i, phaseCount: phases.length,
          done: _done, total: _total, idleMs, stallMs, hint: ph.hint ?? null,
        })
    onUpdate?.({
      key: ph.key, label: ph.label, text, fraction: _reported,
      phaseIndex: _i, phaseCount: phases.length, done: _done, total: _total,
    })
  }

  /** Enter `key`. Never moves backwards — a late event from a finished phase is
   *  folded into the current one instead of rewinding the bar. */
  function begin(key) {
    const idx = _indexOf(key)
    if (idx < 0 || idx < _i) return false
    if (idx > _i) {
      // Everything between here and there is complete by definition: their work
      // either finished or never existed. Credit it so the bar never sticks.
      _i = idx
      _frac = 0
      _reported = Math.max(_reported, cum[idx])
    }
    _done = null; _total = null
    _lastMs = now()
    _emit()
    return true
  }

  /** Report countable progress inside `key` (entering it first if needed). */
  function tick(key, done, total) {
    const idx = _indexOf(key)
    if (idx < 0 || idx < _i) return false
    if (idx > _i) begin(key)
    _done  = Number.isFinite(done)  ? done  : null
    _total = Number.isFinite(total) ? total : null
    _frac  = _total > 0 ? Math.max(0, Math.min(1, _done / _total)) : _frac
    _lastMs = now()
    _emit()
    return true
  }

  /** Report an uncountable fraction (0–1) inside `key`. */
  function setFraction(key, t) {
    const idx = _indexOf(key)
    if (idx < 0 || idx < _i) return false
    if (idx > _i) begin(key)
    _frac = Math.max(0, Math.min(1, Number(t) || 0))
    _lastMs = now()
    _emit()
    return true
  }

  /** Re-emit the current status with an elapsed tail if the phase has gone quiet.
   *  Returns true when it actually emitted (i.e. the phase IS stalled). */
  function heartbeat() {
    if (_finished) return false
    const idle = now() - _lastMs
    if (idle < stallMs) return false
    _emit(idle)
    return true
  }

  function finish() {
    _finished = true
    _i = phases.length - 1
    _frac = 1
    _reported = 1
    _emit()
  }

  function snapshot() {
    return {
      key: phases[_i].key, phaseIndex: _i, phaseCount: phases.length,
      fraction: _reported, phaseFraction: _frac, done: _done, total: _total,
      idleMs: now() - _lastMs, finished: _finished,
    }
  }

  return { begin, tick, setFraction, heartbeat, finish, snapshot, phases }
}

/**
 * Map an animation-player bake event onto a phase key.
 *
 * The player tags its own events (`stage`), but older/foreign emitters only carry
 * a human `label`, so fall back to that before defaulting to the geometry phase —
 * a mis-attributed tick is still better than a silent one.
 */
export function bakeEventPhase(evt) {
  if (!evt) return null
  if (evt.stage && PHASE_WEIGHTS[evt.stage] != null) return evt.stage
  if (typeof evt.label === 'string') {
    if (/^loading trajectory/i.test(evt.label))   return 'traj_load'
    if (/trajectory frames/i.test(evt.label))     return 'traj_frames'
  }
  if (evt.type === 'baking' || evt.type === 'baking_progress') return 'geometry'
  return null
}

// ── Session: the singleton that owns the popup for one export run ─────────────

const _defaultUi = {
  show: showOpProgress, hide: hideOpProgress,
  label: setOpProgressLabel, fraction: setOpProgressFraction,
}
const _defaultTimer = {
  set:   (fn, ms) => setInterval(fn, ms),
  clear: (h)      => clearInterval(h),
}

let _active = null

/**
 * Open the export progress popup and take ownership of it for the whole run.
 *
 * While a session is live the animation panel MUST NOT open its own bake popup:
 * `showOpProgress` is ref-counted with a single shared header and cancel handler,
 * so a second shower silently replaces the export's header with "Rendering
 * Animation" and its Cancel button with the bake's — leaving the export
 * uncancellable for the hours-long part. `activeExportSession()` is that gate.
 *
 * @param {object}   opts
 * @param {string}   opts.header    popup header, e.g. 'Exporting Animation'
 * @param {Array}    opts.phases    from `planExportPhases`
 * @param {function} [opts.onCancel]
 * @param {function} [opts.onStatus] mirror of the status text, for a panel-local line
 * @param {object}   [opts.ui]      op_progress binding (injected in tests)
 * @param {object}   [opts.timer]   setInterval/clearInterval (injected in tests)
 * @param {function} [opts.now]
 * @param {number}   [opts.heartbeatMs]
 */
export function createExportSession({
  header, phases, onCancel = null, onStatus = null,
  ui = _defaultUi, timer = _defaultTimer, now = () => Date.now(),
  heartbeatMs = 1000, stallMs = 2500,
} = {}) {
  const prog = createExportProgress({
    phases,
    now,
    stallMs,
    onUpdate: (u) => {
      ui.fraction?.(u.fraction)
      ui.label?.(null, u.text)
      onStatus?.(u)
    },
  })

  ui.show?.(header ?? 'Exporting', 'Starting…', onCancel ? { onCancel } : {})

  // The heartbeat is what turns an opaque multi-minute await into something the
  // user can read as "working" — the trajectory download and the GIF byte-concat
  // both return control to us only once, at the end.
  const _h = timer.set?.(() => { prog.heartbeat() }, heartbeatMs)
  let _ended = false

  /** Feed an animation-player `baking*` event into the bar. */
  function handleBakeEvent(evt) {
    const key = bakeEventPhase(evt)
    if (!key) return false
    if (!prog.phases.some(p => p.key === key)) return false
    if (evt.type === 'baking') return prog.begin(key)
    return prog.tick(key, evt.done, evt.total)
  }

  function end() {
    if (_ended) return
    _ended = true
    timer.clear?.(_h)
    ui.hide?.()
  }

  return {
    begin: prog.begin, tick: prog.tick, setFraction: prog.setFraction,
    finish: prog.finish, snapshot: prog.snapshot, phases: prog.phases,
    heartbeat: prog.heartbeat, handleBakeEvent, end,
  }
}

/** Begin (and register) the process-wide export session. */
export function beginExportSession(opts) {
  _active?.end()
  _active = createExportSession(opts)
  return _active
}

/** The live export session, or null. Panels use this to stand down. */
export function activeExportSession() { return _active }

/** Close the live session (idempotent, safe when none is open). */
export function endExportSession() {
  const s = _active
  _active = null
  s?.end()
}
