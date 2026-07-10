/**
 * stage_planner_model.js — PURE stage-list + chain-status helpers (originally the model
 * behind the removed "Plan Run" overlay; now the live consumer is the Chain Simulations
 * sidebar, which uses `chainStatusSummary` for its running-chain readout, while the
 * queue's own preflight/ETA/grouping live in `chain_sim_model.js`).  No DOM, no fetch, no
 * topology: it owns an ordered list of pipeline stages and turns it into the exact
 * `CreateChainRequest` payload the backend `POST /md/chains` route consumes (`MdPipeline`).
 *
 * A stage's `field` / `anchors` / `surface` are the same job-request force annotations
 * the per-engine launch cards emit (the shared efield_math / oxdna_floor_math payloads) —
 * never `Design` edits (Three-Layer Law: these are display/Physical job requests only).
 *
 * The model is a plain value object `{ rootJobId, rootEngine, stages: [stage] }`; every
 * mutator returns a NEW model (no in-place edits) so the UI can diff/re-render cleanly.
 */

/** One stage's default shape — mirrors backend `ChainStageRequest` field-for-field. */
export function newStage(overrides = {}) {
  return {
    engine: 'namd',
    protocol: 'production',
    field: null,
    anchors: null,
    surface: null,
    run_target: 'local',
    cluster_name: null,
    length_ns: null,
    steps: null,
    label: null,
    ...overrides,
  }
}

/** A fresh empty planner model. */
export function newPlan({ rootJobId = null, rootEngine = null, stages = [] } = {}) {
  return { rootJobId, rootEngine, stages: stages.map((s) => newStage(s)) }
}

function _clone(model) {
  return {
    rootJobId: model.rootJobId ?? null,
    rootEngine: model.rootEngine ?? null,
    stages: model.stages.map((s) => ({ ...s })),
  }
}

/** Append a stage (defaulted, or from `stage`) → new model. */
export function addStage(model, stage = {}) {
  const m = _clone(model)
  m.stages.push(newStage(stage))
  return m
}

/** Deep-copy the stage at `index` and insert the copy immediately after it (field sweep
 * seed: duplicate, then rotate the copy's field dir via `setStage`). No-op if out of range. */
export function duplicateStage(model, index) {
  const m = _clone(model)
  if (index < 0 || index >= m.stages.length) return m
  const src = m.stages[index]
  const copy = {
    ...src,
    field: src.field ? { ...src.field, dir: src.field.dir ? src.field.dir.slice() : src.field.dir } : src.field,
    anchors: src.anchors ? src.anchors.map((a) => (a && typeof a === 'object' ? { ...a } : a)) : src.anchors,
    surface: src.surface ? { ...src.surface } : src.surface,
  }
  m.stages.splice(index + 1, 0, copy)
  return m
}

/** Remove the stage at `index` → new model. No-op if out of range. */
export function removeStage(model, index) {
  const m = _clone(model)
  if (index < 0 || index >= m.stages.length) return m
  m.stages.splice(index, 1)
  return m
}

/** Move the stage at `from` to position `to` (clamped) → new model. */
export function reorderStage(model, from, to) {
  const m = _clone(model)
  if (from < 0 || from >= m.stages.length) return m
  const dst = Math.max(0, Math.min(to, m.stages.length - 1))
  const [s] = m.stages.splice(from, 1)
  m.stages.splice(dst, 0, s)
  return m
}

/** Shallow-merge `patch` into the stage at `index` → new model. No-op if out of range. */
export function setStage(model, index, patch = {}) {
  const m = _clone(model)
  if (index < 0 || index >= m.stages.length) return m
  m.stages[index] = { ...m.stages[index], ...patch }
  return m
}

/** Set the root job + engine the chain seeds from → new model. */
export function setRoot(model, rootJobId, rootEngine = null) {
  const m = _clone(model)
  m.rootJobId = rootJobId ?? null
  m.rootEngine = rootEngine ?? null
  return m
}

/**
 * Build the `CreateChainRequest` payload (== a valid P1 `MdPipeline` once parsed).
 * Emits every `ChainStageRequest` field so pydantic sees the canonical shape; a stage's
 * `field.enabled` sentinel from the Forces card is dropped (the backend only wants the
 * `{field_pN, dir}` descriptor, and a disabled field becomes `null`).
 */
export function buildChainPayload(model) {
  return {
    root_job_id: model.rootJobId ?? null,
    root_engine: model.rootEngine ?? null,
    stages: model.stages.map((s) => ({
      engine: s.engine,
      protocol: s.protocol || 'production',
      field: _cleanField(s.field),
      anchors: s.anchors ?? null,
      surface: s.surface ?? null,
      run_target: s.run_target || 'local',
      cluster_name: s.cluster_name ?? null,
      length_ns: s.length_ns ?? null,
      steps: s.steps ?? null,
      label: s.label ?? null,
    })),
  }
}

/** A Forces-card field spec → the backend `{field_pN, dir}` descriptor, or null when off. */
function _cleanField(field) {
  if (!field) return null
  if (field.enabled === false) return null
  if (!(Number(field.field_pN) > 0)) return null
  return { field_pN: Number(field.field_pN), dir: Array.isArray(field.dir) ? field.dir.slice() : field.dir }
}

/** True when the model can be queued (a root + at least one stage). */
export function isQueueable(model) {
  return !!model.rootJobId && model.stages.length > 0
}

// ── active-selection index tracking (keep the editor pinned to the SAME stage across a
//    list edit, so subsequent edits land on the stage the user thinks is selected) ──────

/** Where the active stage lands after `removeStage(model, removed)` (newLength = post
 * length).  Removing a stage BEFORE the active one shifts it down; removing the active
 * one (or off the end) clamps into range; -1 when the list empties. */
export function activeIndexAfterRemove(active, removed, newLength) {
  if (active < 0 || newLength <= 0) return newLength > 0 ? active : -1
  let idx = active
  if (removed < active) idx--
  if (idx >= newLength) idx = newLength - 1
  return idx
}

/** Where the active stage lands after `reorderStage(model, from, to)`.  Moving the active
 * stage itself → it follows to `to`; moving a bystander across it shifts its index by the
 * same remove-then-insert transform the model applied. */
export function activeIndexAfterReorder(active, from, to) {
  if (active < 0) return -1
  if (active === from) return to
  let idx = active
  if (from < idx) idx--       // removing `from` (below active) shifts active down
  if (to <= idx) idx++        // inserting at/below active shifts it back up
  return idx
}

// ── live chain status vocabulary (drives the running-chain readout) ────────────────
const _STAGE_LABEL = { pending: 'queued', running: 'running', done: 'done', failed: 'failed' }

/**
 * Derive the "stage N of M / queued-behind / partial-failure" vocabulary from a chain
 * dict (the executor `ChainRun.to_dict` shape: {status, error, stages:[{index,status,...}]}).
 * Pure — the overlay renders whatever this returns.
 */
export function chainStatusSummary(chain) {
  const stages = chain?.stages ?? []
  const total = stages.length
  const doneCount = stages.filter((s) => s.status === 'done').length
  const failedIdx = stages.findIndex((s) => s.status === 'failed')
  const runningIdx = stages.findIndex((s) => s.status === 'running')
  // "current" = the running stage, else the first not-yet-done stage, else the last.
  let currentIdx = runningIdx
  if (currentIdx < 0) currentIdx = stages.findIndex((s) => s.status === 'pending')
  if (currentIdx < 0) currentIdx = total - 1

  let headline
  const status = chain?.status
  if (status === 'completed') headline = `Chain complete — ${total} of ${total} stages done.`
  else if (status === 'failed') {
    const at = failedIdx >= 0 ? failedIdx + 1 : currentIdx + 1
    headline = `Halted at stage ${at} of ${total} — ${doneCount} done, then failed. Resume to retry from the failed stage.`
  } else if (status === 'running') headline = `Running stage ${currentIdx + 1} of ${total} (${doneCount} done).`
  else headline = `Queued — ${total} stage${total === 1 ? '' : 's'} pending.`

  return {
    headline,
    // The backend's own actionable failure message (a 409 body / spawn error). Already
    // human-readable ("Open 'X' to continue this run") — surface it verbatim on failure
    // so the sidebar explains WHY it halted, not just that it did. null when healthy.
    error: status === 'failed' ? (chain?.error ?? null) : null,
    total,
    doneCount,
    currentIndex: currentIdx,
    failedIndex: failedIdx,
    resumable: status === 'failed',
    stageBadges: stages.map((s) => ({
      index: s.index,
      status: s.status,
      label: _STAGE_LABEL[s.status] || s.status,
      // a stage after the failed one is "queued behind" the halt (never spawned)
      queuedBehind: failedIdx >= 0 && s.index > failedIdx && s.status === 'pending',
    })),
  }
}
