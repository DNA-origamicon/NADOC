/** Health-card tile states — why a NAMD metric is (or is not) on screen.
 *
 * The Health card used to decide "show a spinner" from the rendered value alone:
 * any tile reading "—" on an active job got one.  That conflated three completely
 * different situations, and the two that are not "in flight" spun forever:
 *
 *   - a value that IS being computed and will arrive        → spinner is right
 *   - a value nothing will ever compute for this run        → spinner is a lie
 *   - a value whose computation failed                      → spinner hides the error
 *
 * This module makes the distinction explicit and testable.  It is pure: no DOM, no
 * formatting, no fetching — it maps job/health/metrics data to a state per tile, and
 * the panel decides how to draw each state.  A spinner may ONLY be drawn for PENDING.
 *
 * One reason to change: the rules for when a health metric counts as pending.
 */

export const TILE_STATE = {
  VALUE:       'value',        // we have it — render it
  PENDING:     'pending',      // genuinely in flight — the ONLY state that may spin
  UNAVAILABLE: 'unavailable',  // will not be computed for this run — render "—" + why
  FAILED:      'failed',       // the computation errored — render "—" + the error
}

/** Fallback probe cadence (seconds) when the backend hasn't published one yet.
 *  Mirrors NADOC_INFLIGHT_HEALTH_INTERVAL_S's default, but the published value always
 *  wins — the UI must not be the source of truth for the runner's timing. */
export const DEFAULT_PROBE_INTERVAL_S = 300

/** How many intervals the probe may go without RUNNING before we call it stopped.  Two
 *  gives one whole missed cycle of slack. */
const PROBE_SILENT_INTERVALS = 2

/** How many intervals the probe may run without ever producing a SAMPLE before we stop
 *  claiming one is coming.  Much longer than PROBE_SILENT_INTERVALS on purpose: the
 *  first sample needs `safe_back + 1` trajectory frames, and at a production `dcdFreq`
 *  (one frame per ~100 ps) that is minutes of wall-clock even on a healthy run. */
const NO_SAMPLE_INTERVALS = 10

/** The tiles whose values come from a health sample rather than the NAMD log. */
const HEALTH_TILES = new Set(['basePairs', 'wcHealth', 'brokenBp', 'shellCharge'])

/** The two tiles that ride the per-frame diagnostics loop, and so depend on the
 *  sample's `diagnostics` provenance field rather than just on the value. */
const DIAGNOSTIC_TILES = new Set(['brokenBp', 'shellCharge'])

/** Pure: minutes-and-seconds phrasing for an overdue interval. */
function _ago(ms) {
  const min = Math.floor(ms / 60000)
  if (min >= 60) return `${Math.floor(min / 60)}h ${min % 60}m`
  if (min >= 1) return `${min} min`
  return `${Math.max(0, Math.round(ms / 1000))}s`
}

/** Pure: is this raw tile value present? `0` and `0.0` are real readings, so only
 *  null/undefined/NaN count as absent. */
export function hasValue(raw) {
  return raw !== null && raw !== undefined && !(typeof raw === 'number' && Number.isNaN(raw))
}

/** Pure: classify ONE tile.
 *
 *  @param {string} key      tile key (see mdHealthTileStates)
 *  @param {*}      raw      the tile's raw value (null when absent)
 *  @param {object} ctx      { job, health, probe, active, nowMs }
 *  @returns {{state: string, reason: string|null}}
 */
export function mdHealthTileState(key, raw, ctx) {
  const { job, health, probe, active, nowMs } = ctx

  // 1. We have it. Nothing else matters.
  if (hasValue(raw)) return { state: TILE_STATE.VALUE, reason: null }

  // 2. Nothing is running, so nothing will fill it in. A finished run that never
  //    measured this simply never measured it — that is not "computing".
  if (!active) {
    return { state: TILE_STATE.UNAVAILABLE, reason: 'not measured during this run' }
  }

  const fromHealth = HEALTH_TILES.has(key)
  if (!fromHealth) {
    // Log-derived (Temp / Pressure / Speed): NAMD prints its first ENERGY line only
    // after minimisation warms up, so absence early in a run is genuinely pending.
    return { state: TILE_STATE.PENDING, reason: null }
  }

  // 3. No probe will ever run for this segment — say so instead of spinning.
  if (probe && probe.enabled === false) {
    return {
      state: TILE_STATE.UNAVAILABLE,
      reason: probe.reason || 'health sampling is not running for this job',
    }
  }

  // 4. The last probe failed. Show the error rather than hiding it behind motion.
  if (probe?.last_error) {
    return { state: TILE_STATE.FAILED, reason: `health probe failed: ${probe.last_error}` }
  }

  // 5. The per-frame diagnostics tiles carry their own provenance, because a null here
  //    is ambiguous: old samples predate the fields entirely and must never spin.
  if (DIAGNOSTIC_TILES.has(key) && health) {
    const diag = health.diagnostics
    if (diag === null || diag === undefined) {
      return { state: TILE_STATE.UNAVAILABLE, reason: 'not recorded by this run' }
    }
    if (diag !== 'ok') {
      return { state: TILE_STATE.FAILED, reason: diag }
    }
    // diagnostics === 'ok' and still null → measured, and there was nothing to measure.
    return { state: TILE_STATE.UNAVAILABLE, reason: 'measured as none' }
  }

  // 6. Watchdogs. Two separate clocks, because "the probe died" and "the probe is
  //    running but has nothing to measure yet" are different situations with very
  //    different timescales. Both are bounded, so no tile can spin indefinitely.
  //
  //    NOTE both clocks are anchored on the PROBE, never on `job.created_at`. A resumed
  //    run can be many hours old with a probe that started seconds ago; anchoring on job
  //    age made every resume paint failed tiles the moment it came back.
  const intervalS = Number(probe?.interval_s) > 0
    ? Number(probe.interval_s)
    : DEFAULT_PROBE_INTERVAL_S
  const ms = (s) => (s != null ? s * 1000 : null)
  const lastTick = ms(probe?.last_tick_at) ?? ms(probe?.last_at)
  const startedAt = ms(probe?.started_at)

  // 6z. No probe has published anything at all. That is its own answer — say it rather
  //     than spinning forever (the original bug) or crying failure (a resumed run has a
  //     seconds-long window here before its runner publishes). A young job is still
  //     legitimately starting up.
  if (!probe) {
    const age = nowMs - (job?.created_at ?? 0) * 1000
    if (job?.created_at && age > NO_SAMPLE_INTERVALS * intervalS * 1000) {
      return {
        state: TILE_STATE.UNAVAILABLE,
        reason: 'health sampling has not reported for this run',
      }
    }
    return { state: TILE_STATE.PENDING, reason: null }
  }

  // 6a. The probe has stopped reporting at all.
  if (lastTick != null && nowMs > lastTick + PROBE_SILENT_INTERVALS * intervalS * 1000) {
    return {
      state: TILE_STATE.FAILED,
      reason: `health probe stopped reporting ${_ago(nowMs - lastTick)} ago`,
    }
  }

  // 6b. It is reporting, but no sample has ever landed for this segment.
  if (probe?.last_at == null && startedAt != null
      && nowMs > startedAt + NO_SAMPLE_INTERVALS * intervalS * 1000) {
    return {
      state: TILE_STATE.FAILED,
      reason: `no health sample in ${_ago(nowMs - startedAt)}`
            + (probe?.reason ? ` — ${probe.reason}` : ''),
    }
  }

  // 6c. Samples were arriving and then stopped.
  if (probe?.last_at != null
      && nowMs > ms(probe.last_at) + NO_SAMPLE_INTERVALS * intervalS * 1000) {
    return {
      state: TILE_STATE.FAILED,
      reason: `no health sample in ${_ago(nowMs - ms(probe.last_at))}`,
    }
  }

  // 7. Genuinely in flight. The probe's own note ("waiting for the first trajectory
  //    frames") is the most useful thing to show while it is.
  return { state: TILE_STATE.PENDING, reason: probe?.reason || null }
}

/** Pure: classify every Health-card tile at once.
 *
 *  `raws` supplies each tile's already-resolved raw value, so this module stays free of
 *  the panel's live/persisted precedence rules.  `active` is passed IN rather than
 *  derived here (the panel owns `mdJobIsActive`) so this module imports nothing —
 *  importing the panel would drag its whole DOM/browser surface into every consumer.
 *  Returns a map keyed the same way as `raws`.
 */
export function mdHealthTileStates({ job, health, probe, raws, nowMs, active }) {
  const ctx = {
    job,
    health,
    probe: probe ?? job?.health_probe ?? null,
    active: active ?? ['queued', 'preparing', 'running'].includes(job?.status),
    nowMs: nowMs ?? Date.now(),
  }
  const out = {}
  for (const [key, raw] of Object.entries(raws ?? {})) {
    out[key] = mdHealthTileState(key, raw, ctx)
  }
  return out
}
