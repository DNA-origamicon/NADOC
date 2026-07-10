/**
 * chain_sim_model.js — PURE queue semantics for the Chain Simulations sidebar.
 *
 * A Chain Simulations *project* is an ordered list of queued stages (each an oxDNA or
 * NAMD relax/production run with its field/surface/anchors). This module owns the three
 * pure decisions the sidebar renders, with NO DOM / fetch / topology:
 *
 *   • stagePreflight  — per-stage ✓ / ⚠ / ✕ + the seed provenance note;
 *   • estimateStageSeconds / estimateTotalSeconds — a ROUGH best-effort ETA;
 *   • groupIntoChains — fold the flat queue into the backend `CreateChainRequest`
 *     payload(s) the Launch step POSTs to `/md/chains`.
 *
 * Three-Layer Law: a stage's field/anchors/surface are job-request annotations, never
 * `Design` edits. The stage-list mutators (add/remove/reorder) live in the shared
 * `stage_planner_model.js`; this module adds the chain-sim-specific semantics on top.
 */

// ── stage shape ──────────────────────────────────────────────────────────────────

/** One queued stage. `id` is caller-assigned (stable identity across reorders). */
export function newChainStage(overrides = {}) {
  return {
    id: null,
    engine: 'oxdna',            // 'oxdna' | 'namd'
    protocol: 'production',     // 'relax' | 'production'
    field: null,
    anchors: null,
    surface: null,
    run_target: 'local',        // 'local' | 'alpine'
    cluster_name: null,
    length_ns: null,
    steps: null,
    label: null,
    seed_job_id: null,          // an EXISTING completed job this stage chains off
    seed_job_name: null,        // that job's display name (captured at enqueue)
    seed_engine: null,          // that job's engine (for the seed-compatibility check)
    ...overrides,
  }
}

export function isRelax(stage) {
  return (stage?.protocol || '').toLowerCase() === 'relax'
}

function _hasField(st) {
  return !!(st?.field && Number(st.field.field_pN) > 0 && st.field.enabled !== false)
}
function _hasAnchors(st) {
  return !!(st?.anchors && st.anchors.length)
}

// Mirror of backend field_anchor.surface_opposes_field: a hard surface holds a field that
// presses (anti-parallel) into its plane within ~25° (cos 25° ≈ 0.906), so a deposition
// stage (field into the floor) needs no strand anchor. Keep in lockstep with the backend.
const _OPPOSE_COS = 0.906
function _unit(v) {
  if (!Array.isArray(v) || v.length !== 3) return null
  const n = Math.hypot(v[0], v[1], v[2])
  return n > 1e-12 ? [v[0] / n, v[1] / n, v[2] / n] : null
}
function _surfaceOpposesField(field, surface) {
  const f = _unit(field?.dir)
  const s = _unit(surface?.dir)
  if (!f || !s) return false
  return f[0] * s[0] + f[1] * s[1] + f[2] * s[2] <= -_OPPOSE_COS
}
/** A field with no strand anchor still needs holding unless a surface opposes it. */
function _fieldNeedsAnchor(st) {
  if (!_hasField(st) || _hasAnchors(st)) return false
  return !_surfaceOpposesField(st.field, st.surface)
}

/**
 * Can an engine seed a run from a job of `sourceEngine`?
 *   • same engine → a checkpoint restart;
 *   • NAMD ← oxDNA/mrDNA → a cross-engine atomistic rebuild from the coarse frame.
 * A coarse engine (oxDNA) can NOT rebuild from an atomistic (NAMD) frame.
 */
export function engineCanSeedFrom(targetEngine, sourceEngine) {
  if (!sourceEngine) return false
  if (targetEngine === sourceEngine) return true
  return targetEngine === 'namd' && (sourceEngine === 'oxdna' || sourceEngine === 'mrdna')
}

// ── preflight ──────────────────────────────────────────────────────────────────--

/**
 * Preflight one stage against the queue + the set of completed jobs.
 *
 * A production stage must seed from something: its immediate predecessor in the queue,
 * or (when it starts a fresh lineage) an existing completed job named by `seed_job_id`.
 * With neither → ✕ error. A stage whose field is enabled with no anchor, or an Alpine
 * stage with no cluster, is ⚠ warn. Everything else is ✓ ok. `seedFrom` names the
 * provenance so the row can read green with "seeds from …".
 *
 * @returns {{level:'ok'|'warn'|'error', reasons:string[], seedFrom:object|null}}
 */
export function stagePreflight(stages, index, { completedJobs = [] } = {}) {
  const st = stages[index]
  const reasons = []
  let seedFrom = null

  if (st.protocol === 'production') {
    // Precedence: continue the IN-QUEUE lineage (the predecessor stage) when there is a
    // compatible one; otherwise root a fresh lineage off an existing completed job
    // (`seed_job_id`). Neither → ✕.
    const prev = index > 0 ? stages[index - 1] : null
    if (prev && engineCanSeedFrom(st.engine, prev.engine)) {
      seedFrom = { kind: 'stage', ref: index - 1, label: `seeds from stage ${index} (${prev.protocol})` }
    } else if (st.seed_job_id) {
      const srcEngine = st.seed_engine || st.engine
      if (!engineCanSeedFrom(st.engine, srcEngine)) {
        reasons.push(`a ${st.engine} run cannot seed from a ${srcEngine} job`)
        return { level: 'error', reasons, seedFrom: null }
      }
      // If a live completed-job list is supplied, flag a seed job that no longer exists.
      if (completedJobs.length && !completedJobs.some((j) => j.job_id === st.seed_job_id)) {
        reasons.push('its seed job no longer exists — re-pick a completed job')
        return { level: 'error', reasons, seedFrom: null }
      }
      seedFrom = {
        kind: 'job', ref: st.seed_job_id,
        label: `seeds from job “${st.seed_job_name || st.seed_job_id}” (positions + velocities)`,
      }
    } else if (prev) {
      reasons.push(`a ${st.engine} run cannot seed from the preceding ${prev.engine} stage`)
      return { level: 'error', reasons, seedFrom: null }
    } else {
      reasons.push('a production run needs an upstream relax — queue a relax first, or seed it from a completed job')
      return { level: 'error', reasons, seedFrom: null }
    }
  }

  // Warnings apply to both relax and production stages.
  if (_fieldNeedsAnchor(st)) {
    reasons.push('an electric field with no anchor (and no surface to press into) drifts the whole structure')
  }
  if (st.run_target === 'alpine' && !st.cluster_name) {
    reasons.push('Alpine run target has no cluster selected')
  }
  return { level: reasons.length ? 'warn' : 'ok', reasons, seedFrom }
}

/** The worst preflight level across the whole queue ('ok' | 'warn' | 'error'). */
export function queuePreflightLevel(stages, ctx = {}) {
  let worst = 'ok'
  for (let i = 0; i < stages.length; i++) {
    const lvl = stagePreflight(stages, i, ctx).level
    if (lvl === 'error') return 'error'
    if (lvl === 'warn') worst = 'warn'
  }
  return worst
}

// ── ETA (rough best-effort) ──────────────────────────────────────────────────────

// Fallback throughput when nothing has been benchmarked/learned. Deliberately crude —
// the ETA is labelled "≈". A real OxdnaHardwareDefault.steps_per_s or a learned NAMD
// ns/day (passed in ctx) overrides these.
const _DEFAULT_OXDNA_STEPS_PER_S = 1.0e6   // small system, CUDA
const _DEFAULT_NAMD_NS_PER_DAY = 15.0      // small solvated origami, one GPU

/** A crude size taper: throughput falls off as the system grows past ~1000 nt/bp. */
function _sizeTaper(baseCount) {
  return 1 / (1 + Math.max(0, (baseCount || 0)) / 1000)
}

/** Total oxDNA steps a stage runs (its own `steps`, else a relax's 3-stage default). */
function _oxdnaSteps(st) {
  if (st.steps != null) return st.steps
  return st.protocol === 'relax' ? 2_100_000 : 2_000_000   // mc+md+equil ≈ 2.1e6
}

/** NAMD nanoseconds a stage runs (its own `length_ns`, else a modest default). */
function _namdNs(st) {
  if (st.length_ns != null) return st.length_ns
  return st.protocol === 'relax' ? 2.0 : 10.0
}

/**
 * Rough wall-clock seconds for one stage.
 * @param ctx.oxdnaStepsPerSec  measured oxDNA throughput (OxdnaHardwareDefault) or null
 * @param ctx.namdNsPerDay      measured/learned NAMD ns/day or null
 * @param ctx.baseCount         design size (nt/bp) for the size taper
 */
export function estimateStageSeconds(stage, ctx = {}) {
  const { oxdnaStepsPerSec = null, namdNsPerDay = null, baseCount = 0 } = ctx
  if (stage.engine === 'oxdna') {
    const sps = (oxdnaStepsPerSec || _DEFAULT_OXDNA_STEPS_PER_S) * _sizeTaper(baseCount)
    return _oxdnaSteps(stage) / Math.max(1, sps)
  }
  const perDay = (namdNsPerDay || _DEFAULT_NAMD_NS_PER_DAY) * _sizeTaper(baseCount)
  return (_namdNs(stage) / Math.max(1e-6, perDay)) * 86400
}

export function estimateTotalSeconds(stages, ctx = {}) {
  return stages.reduce((s, st) => s + estimateStageSeconds(st, ctx), 0)
}

/** "≈ 2h 15m" / "≈ 3.4 days" — compact human duration. */
export function formatDuration(seconds) {
  if (!(seconds > 0)) return '≈ —'
  const m = seconds / 60, h = seconds / 3600, d = seconds / 86400
  if (d >= 1) return `≈ ${d.toFixed(d >= 10 ? 0 : 1)} day${d >= 2 ? 's' : ''}`
  if (h >= 1) return `≈ ${Math.floor(h)}h ${Math.round((h - Math.floor(h)) * 60)}m`
  if (m >= 1) return `≈ ${Math.round(m)}m`
  return `≈ ${Math.round(seconds)}s`
}

// ── launch grouping ──────────────────────────────────────────────────────────────

function _cleanField(field) {
  if (!field) return null
  if (field.enabled === false) return null
  if (!(Number(field.field_pN) > 0)) return null
  return { field_pN: Number(field.field_pN), dir: Array.isArray(field.dir) ? field.dir.slice() : field.dir }
}

/** A queue stage → the backend `ChainStageRequest` shape (drops UI-only fields). */
export function toChainStagePayload(st) {
  return {
    engine: st.engine,
    protocol: st.protocol,
    field: _cleanField(st.field),
    anchors: st.anchors ?? null,
    surface: st.surface ?? null,
    run_target: st.run_target || 'local',
    cluster_name: st.cluster_name ?? null,
    length_ns: st.length_ns ?? null,
    steps: st.steps ?? null,
    label: st.label ?? null,
  }
}

/**
 * Fold the flat queue into one or more `CreateChainRequest` payloads.
 *
 * A `relax` stage starts a NEW rootless chain (it CREATES the initial structure). A
 * `production` stage with a `seed_job_id` starts a chain ROOTED at that existing job;
 * otherwise it appends to the currently-open chain (seeded from its predecessor — the
 * pipeline handles same-engine restarts AND cross-engine oxDNA→NAMD rebuilds). Stages
 * that fail preflight are skipped (Launch is gated on a clean queue anyway).
 *
 * @returns {Array<{root_job_id:string|null, root_engine:string|null, stages:object[]}>}
 */
export function chainGroups(stages, { completedJobs = [] } = {}) {
  const groups = []
  let cur = null
  stages.forEach((st, i) => {
    const pf = stagePreflight(stages, i, { completedJobs })
    if (pf.level === 'error') { cur = null; return }
    if (st.protocol === 'relax') {
      // A relax CREATES the structure → a new rootless chain.
      cur = { root_job_id: null, root_engine: st.engine, stages: [st] }
      groups.push(cur)
    } else if (pf.seedFrom?.kind === 'stage' && cur) {
      // Continues the in-queue lineage → append to the open chain.
      cur.stages.push(st)
    } else if (pf.seedFrom?.kind === 'job') {
      // Roots a fresh chain off an existing completed job.
      cur = { root_job_id: st.seed_job_id, root_engine: st.seed_engine || st.engine, stages: [st] }
      groups.push(cur)
    }
  })
  return groups
}

/**
 * The `CreateChainRequest` payloads for the queue (one per lineage). Wraps
 * {@link chainGroups} + {@link toChainStagePayload}; kept as the launch entry point.
 */
export function groupIntoChains(stages, ctx = {}) {
  return chainGroups(stages, ctx).map((g) => ({
    root_job_id: g.root_job_id,
    root_engine: g.root_engine,
    stages: g.stages.map(toChainStagePayload),
  }))
}

// ── live per-stage run status (once a chain is launched) ─────────────────────────

// Chain-executor stage status → a display badge, reusing the job-list vocabulary so the
// queue rows read like the engine job list (queued / running / done / failed).
const _LIVE_BADGE = {
  pending: { symbol: '○', color: '#8b949e', label: 'queued' },
  running: { symbol: '⟳', color: '#e0a800', label: 'running' },
  done:    { symbol: '✓', color: '#3fb950', label: 'done' },
  failed:  { symbol: '✕', color: '#d9534f', label: 'failed' },
}

/** Badge for a launched stage's live status (`pending|running|done|failed`). */
export function liveStageBadge(status) {
  return _LIVE_BADGE[status] || _LIVE_BADGE.pending
}

/** A job's latest health sample (or null) — the pass/fail + reason the row dot shows. */
export function latestHealthSample(job) {
  const hs = job?.health_samples
  return (Array.isArray(hs) && hs.length) ? hs[hs.length - 1] : null
}
