/**
 * ui/md_submit_review.js — Phase 4 of the Alpine remote-execution backend.
 *
 * The "auto-with-review" submit card: given a PREPARED MD job, fetch the Phase-2
 * auto-recommended SLURM resources (`GET /md/jobs/{id}/remote-recommendation`),
 * show system size / protocol / total ns / partition / walltime / est. queue +
 * SU cost, let the user override the resources in an [edit] drawer, then submit
 * (`POST /md/jobs/{id}/submit-remote`).
 *
 * Factory: `initMdSubmitReview({ api, onSubmitted })` → `{ open, dispose }`.
 * `main.js` gets only an import + a one-line init.
 *
 * Pure helpers (`formatResourceSummary`, `reviewSubmitPayload`,
 * `alpineTargetDisabledReason`, `remoteJobBadge`) are exported for unit tests —
 * no DOM required.
 */

// ── Pure formatting/logic helpers (unit-tested) ───────────────────────────────

/** Pure: minutes → a short "~Nh Mm" / "~Nm" queue-time label. */
export function fmtQueueMinutes(min) {
  if (min == null || !isFinite(min)) return 'unknown'
  const m = Math.max(0, Math.round(min))
  if (m < 60) return `~${m} min`
  const h = Math.floor(m / 60)
  const rem = m % 60
  return rem ? `~${h} h ${rem} min` : `~${h} h`
}

/** Pure: nanoseconds → a compact string (3 sig-ish figures). */
export function fmtNs(ns) {
  if (ns == null || !isFinite(ns)) return '?'
  if (ns >= 100) return String(Math.round(ns))
  if (ns >= 10) return ns.toFixed(1)
  return ns.toFixed(2)
}

/**
 * Pure: turn the `GET /remote-recommendation` response (prepared:true) into the
 * display strings the card renders. Tolerant of missing fields.
 */
export function formatResourceSummary(rec) {
  const r = (rec && rec.resources) || {}
  const measured = !!r.measured
  const expected = r.expected_ns_per_day
  return {
    system:   `${Number(rec?.n_atoms ?? 0).toLocaleString()} atoms`,
    totalNs:  `${fmtNs(rec?.total_ns)} ns total`,
    partition: `${r.partition ?? '?'} (${r.kind ?? '?'})`,
    hardware: `${r.gpus ?? 0} GPU · ${r.cores ?? 0} core · ${r.mem_gb ?? 0} GB`,
    walltime: r.walltime ?? '?',
    qos:      r.qos ?? '?',
    throughput: expected != null
      ? `${Number(expected).toFixed(1)} ns/day ${measured ? '(measured)' : '(estimated)'}`
      : 'unknown',
    queue:    fmtQueueMinutes(r.est_queue_min),
    cost:     r.est_cost_su != null ? `${Math.round(r.est_cost_su).toLocaleString()} SU` : 'unknown',
    safety:   `${r.safety_factor ?? 1.5}× walltime headroom`,
    notes:    Array.isArray(r.notes) ? r.notes : (r.notes ? [String(r.notes)] : []),
  }
}

const _NUMERIC_OVERRIDE_KEYS = new Set(['gpus', 'cores', 'mem_gb'])

/**
 * Pure: build the `POST /submit-remote` body from the base auto-resources plus any
 * user edits. With no edits we send just `{cluster_name}` so the backend
 * auto-recommends (single source of truth). With edits we send the full merged
 * `resources` dict — the backend uses it verbatim.
 * `overrides` values that are '' / null / undefined are treated as "not changed".
 */
export function reviewSubmitPayload({ clusterName = 'alpine', baseResources = {}, overrides = {} } = {}) {
  const cleaned = {}
  for (const [k, v] of Object.entries(overrides)) {
    if (v === '' || v == null) continue
    if (_NUMERIC_OVERRIDE_KEYS.has(k)) {
      const n = Number(v)
      if (!isFinite(n)) continue
      cleaned[k] = n
    } else {
      cleaned[k] = v
    }
  }
  if (Object.keys(cleaned).length === 0) return { cluster_name: clusterName }
  return { cluster_name: clusterName, resources: { ...baseResources, ...cleaned } }
}

/**
 * Pure: why the Alpine run-target is disabled, or null when it's usable.
 * Drives the toggle's disabled state + tooltip.
 */
export function alpineTargetDisabledReason(clusterState) {
  if (clusterState === 'connected') return null
  if (clusterState === 'connecting') return 'Connecting to the cluster…'
  if (clusterState === 'expired') return 'Cluster session expired — reconnect first'
  return 'Connect to the Alpine cluster first (click the cluster chip)'
}

/**
 * Pure: build the partition dropdown options from a recommendation response.
 * Returns `[{value, label, selected}]`, deduped, with the currently-recommended
 * partition marked selected (and injected if the profile list somehow omits it).
 */
export function partitionSelectOptions(rec) {
  const current = rec?.resources?.partition
  const list = Array.isArray(rec?.available_partitions) ? rec.available_partitions : []
  const seen = new Set()
  const opts = []
  for (const p of list) {
    if (!p || !p.name || seen.has(p.name)) continue
    seen.add(p.name)
    const model = p.gpu_model ? ` — ${p.gpu_model}` : ''
    opts.push({ value: p.name, label: `${p.name} (${p.kind || '?'})${model}`, selected: p.name === current })
  }
  if (current && !seen.has(current)) {
    opts.unshift({ value: current, label: String(current), selected: true })
  }
  return opts
}

/**
 * Pure: build the QoS dropdown options from a recommendation response.  Options are
 * the tiers valid for the recommended partition's kind (`available_qos`), labelled
 * with their walltime ceiling; the current QoS is marked selected (and injected if
 * the list omits it).
 */
export function qosSelectOptions(rec) {
  const current = rec?.resources?.qos
  const list = Array.isArray(rec?.available_qos) ? rec.available_qos : []
  const seen = new Set()
  const opts = []
  for (const q of list) {
    if (!q || !q.name || seen.has(q.name)) continue
    seen.add(q.name)
    const cap = q.max_walltime_h ? ` (≤${q.max_walltime_h} h)` : ''
    opts.push({ value: q.name, label: `${q.name}${cap}`, selected: q.name === current })
  }
  if (current && !seen.has(current)) {
    opts.unshift({ value: current, label: String(current), selected: true })
  }
  return opts
}

/** Pure: list-row badge text for a remote (Alpine) job, else ''. */
export function remoteJobBadge(job) {
  if (job?.execution_target !== 'alpine') return ''
  const parts = []
  if (job.slurm_job_id) parts.push(`SLURM ${job.slurm_job_id}`)
  const partition = job?.resources?.partition
  if (partition) parts.push(partition)
  return parts.length ? parts.join(' · ') : 'Alpine'
}

// ── Colours (match the dark theme used across MD UI) ──────────────────────────
const _C = {
  bg: '#0d1117', panel: '#161b22', border: '#30363d', dim: '#484f58',
  muted: '#8b949e', text: '#c9d1d9', ok: '#3fb950', warn: '#d29922', err: '#f85149',
}

/**
 * Factory. `api` is the client module (needs getMdRemoteRecommendation +
 * submitMdJobRemote). `onSubmitted(jobId, result)` fires after a successful submit
 * so the panel can refetch/select. `toast` is optional (falls back to no-op).
 */
export function initMdSubmitReview({ api, onSubmitted = () => {}, toast = null } = {}) {
  let _overlay = null
  let _ctx = null   // { jobId, clusterName, editOpen } — kept across partition re-fetches

  const _notify = (msg, kind) => { try { toast?.(msg, kind) } catch { /* no-op */ } }

  function _teardownOverlay() {
    if (_overlay) { _overlay.remove(); _overlay = null }
  }

  function dispose() {
    _teardownOverlay()
    _ctx = null
  }

  async function open(jobId, { clusterName = 'alpine', mode = 'submit', parentId = null, count = 0, partition = null } = {}) {
    if (!jobId) return
    dispose()
    // `jobId` is the job to SIZE against (a replica child in ensemble mode); `parentId`
    // is what an ensemble submit posts to.  `partition` (ensemble) forces the initial
    // sizing partition (acpu by default).
    _ctx = { jobId, clusterName, editOpen: false, mode, parentId, count, partition }
    await _load(null)
  }

  /** Fetch the recommendation (optionally forcing a partition) and (re)render.
   *  Resume mode seeds the card with the job's CURRENT resources (`current:true`) so
   *  the user reviews/edits what they last ran, and skips the already-submitted gate.
   *  Ensemble mode forces the initial partition (acpu) so replicas size on CPU. */
  async function _load(partition) {
    if (!_ctx) return
    const { jobId, clusterName, mode } = _ctx
    const resume = mode === 'resume'
    const ensemble = mode === 'ensemble'
    const effPartition = partition ?? (ensemble ? (_ctx.partition || 'acpu') : null)
    const rec = await api.getMdRemoteRecommendation(jobId, { clusterName, partition: effPartition, current: resume && !partition }).catch(() => null)
    if (!_ctx) return   // disposed while awaiting
    if (!rec) {
      _notify(api.lastErrorMessage?.() ?? 'Could not load cluster recommendation', 'error')
      dispose()
      return
    }
    if (!rec.prepared) {
      _notify(rec.reason || 'Job is still preparing — try again once it finishes.', 'warn')
      dispose()
      return
    }
    if (rec.already_submitted && !resume && !ensemble) {
      _notify(`Already submitted to the cluster as SLURM ${rec.slurm_job_id}.`, 'warn')
      dispose()
      return
    }
    _render(rec)
  }

  function _row(label, value, valueColor = _C.text) {
    return (
      `<div style="display:flex;justify-content:space-between;gap:10px;padding:2px 0">` +
      `<span style="color:${_C.muted}">${label}</span>` +
      `<span style="color:${valueColor};font-family:var(--font-mono);text-align:right">${value}</span></div>`
    )
  }

  function _render(rec) {
    const { jobId, clusterName, mode, parentId, count } = _ctx
    const resume = mode === 'resume'
    const ensemble = mode === 'ensemble'
    const s = formatResourceSummary(rec)
    const r = rec.resources || {}
    const _optsHtml = (opts) => opts
      .map(o => `<option value="${o.value}"${o.selected ? ' selected' : ''}>${o.label}</option>`)
      .join('')
    const partOptsHtml = _optsHtml(partitionSelectOptions(rec))
    const qosOptsHtml = _optsHtml(qosSelectOptions(rec))

    _teardownOverlay()
    _overlay = document.createElement('div')
    _overlay.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:10000;display:flex;align-items:center;justify-content:center'
    const box = document.createElement('div')
    box.style.cssText =
      `background:${_C.bg};border:1px solid ${_C.border};border-radius:6px;padding:16px;width:360px;` +
      `max-height:90vh;overflow-y:auto;font-size:var(--text-xs);color:${_C.text}`
    box.innerHTML = `
      <div style="font-weight:600;font-size:13px;margin-bottom:10px">${ensemble ? `Ensemble production — ${count} replica${count === 1 ? '' : 's'}` : resume ? 'Resume from checkpoint — review' : 'Submit to Alpine — review'}</div>
      <div style="color:${_C.muted};margin-bottom:8px">${rec.design_name ?? jobId}</div>
      ${ensemble ? `<div style="color:${_C.muted};margin-bottom:8px;line-height:1.4">Each replica runs the same per-replica resources below (shown for one). All ${count} submit as independent SLURM jobs with distinct seeds.</div>` : ''}
      ${resume ? `<div style="color:${_C.warn};margin-bottom:8px;line-height:1.4">Resuming from the last checkpoint (skips completed segments; continues the interrupted one). Adjust walltime/resources below, then Resume.</div>` : ''}
      <div style="background:${_C.panel};border:1px solid ${_C.border};border-radius:4px;padding:8px;margin-bottom:8px">
        ${_row('System', s.system)}
        ${_row('Simulation', s.totalNs)}
        ${_row('Partition', s.partition)}
        ${_row('Hardware', s.hardware)}
        ${_row('Walltime', s.walltime)}
        ${_row('QoS', s.qos)}
        ${_row('Throughput', s.throughput)}
        ${_row('Est. queue', s.queue)}
        ${_row('Est. cost', s.cost, _C.warn)}
      </div>
      <div style="color:${_C.dim};margin-bottom:8px">${s.safety}</div>
      ${s.notes.length ? `<div style="color:${_C.muted};margin-bottom:8px;line-height:1.4">${s.notes.map(n => `• ${n}`).join('<br>')}</div>` : ''}

      <button id="mr-edit-toggle" style="background:none;border:none;color:#58a6ff;cursor:pointer;padding:0;margin-bottom:6px;font-size:var(--text-xs)">${_ctx.editOpen ? '▾' : '▸'} Edit resources</button>
      <div id="mr-edit" style="display:${_ctx.editOpen ? '' : 'none'};background:${_C.panel};border:1px solid ${_C.border};border-radius:4px;padding:8px;margin-bottom:8px">
        <div style="color:${_C.dim};margin-bottom:6px">Change the partition to re-size on it; blank a field = keep auto value.</div>
        <label style="display:block;color:${_C.muted};margin-bottom:1px">Partition</label>
        <select id="mr-partition" style="width:100%;margin-bottom:6px;background:${_C.bg};border:1px solid ${_C.border};color:${_C.text};border-radius:3px;padding:3px 5px">${partOptsHtml}</select>
        ${_editField('GPUs', 'mr-gpus', r.gpus, 'number')}
        ${_editField('Cores', 'mr-cores', r.cores, 'number')}
        ${_editField('Mem (GB)', 'mr-mem_gb', r.mem_gb, 'number')}
        ${_editField('Walltime', 'mr-walltime', r.walltime, 'text')}
        <label style="display:block;color:${_C.muted};margin-bottom:1px">QoS</label>
        <select id="mr-qos" style="width:100%;margin-bottom:6px;background:${_C.bg};border:1px solid ${_C.border};color:${_C.text};border-radius:3px;padding:3px 5px">${qosOptsHtml}</select>
      </div>

      <div id="mr-err" style="color:${_C.err};min-height:14px;margin-bottom:6px"></div>
      <div style="display:flex;gap:6px;justify-content:flex-end">
        <button id="mr-cancel" style="padding:4px 10px;background:${_C.panel};border:1px solid ${_C.border};color:${_C.text};border-radius:3px;cursor:pointer">Cancel</button>
        <button id="mr-go" style="padding:4px 10px;background:#12261a;border:1px solid #238636;color:${_C.ok};border-radius:3px;cursor:pointer;font-weight:600">${ensemble ? `Submit ${count} replica${count === 1 ? '' : 's'}` : resume ? 'Resume job' : 'Submit job'}</button>
      </div>`
    _overlay.appendChild(box)
    document.body.appendChild(_overlay)

    const errEl = box.querySelector('#mr-err')
    const editBody = box.querySelector('#mr-edit')
    const editToggle = box.querySelector('#mr-edit-toggle')
    editToggle.onclick = () => {
      const open = editBody.style.display !== 'none'
      editBody.style.display = open ? 'none' : ''
      editToggle.textContent = open ? '▸ Edit resources' : '▾ Edit resources'
      if (_ctx) _ctx.editOpen = !open
    }
    // Changing the partition re-sizes the whole request on the backend (kind/gpus/
    // cores/qos/gres re-derived) so we never ship a self-inconsistent set.
    box.querySelector('#mr-partition').onchange = (e) => {
      if (_ctx) _ctx.editOpen = true
      _load(e.target.value)
    }
    box.querySelector('#mr-cancel').onclick = dispose
    _overlay.onclick = (e) => { if (e.target === _overlay) dispose() }

    box.querySelector('#mr-go').onclick = async () => {
      errEl.textContent = ''
      const overrides = {
        partition: box.querySelector('#mr-partition').value.trim(),
        gpus:      box.querySelector('#mr-gpus').value.trim(),
        cores:     box.querySelector('#mr-cores').value.trim(),
        mem_gb:    box.querySelector('#mr-mem_gb').value.trim(),
        walltime:  box.querySelector('#mr-walltime').value.trim(),
        qos:       box.querySelector('#mr-qos').value.trim(),
      }
      const payload = reviewSubmitPayload({ clusterName, baseResources: r, overrides })
      const goBtn = box.querySelector('#mr-go')
      goBtn.disabled = true
      errEl.style.color = _C.muted
      errEl.textContent = ensemble ? `Submitting ${count} replicas…`
                        : resume ? 'Resuming from checkpoint…' : 'Staging package + submitting…'
      try {
        if (ensemble) {
          const result = await api.submitMdEnsemble(parentId, { ...payload, partition: _ctx.partition || 'acpu' })
          if (!result) throw new Error(api.lastErrorMessage?.() ?? 'Ensemble submit failed')
          const nSub = result.submitted?.length ?? 0
          const nErr = result.errors?.length ?? 0
          _notify(`Submitted ${nSub}/${nSub + nErr} replica${nSub === 1 ? '' : 's'} on Alpine${nErr ? ` (${nErr} failed)` : ''}`,
                  nErr ? 'warn' : 'ok')
          dispose()
          onSubmitted(parentId, result)
          return
        }
        const result = resume
          ? await api.resumeMdJobRemote(jobId, payload)
          : await api.submitMdJobRemote(jobId, payload)
        if (!result) throw new Error(api.lastErrorMessage?.() ?? (resume ? 'Resume failed' : 'Submit failed'))
        _notify(`${resume ? 'Resumed' : 'Submitted'} on Alpine as SLURM ${result.slurm_job_id}`, 'ok')
        dispose()
        onSubmitted(jobId, result)
      } catch (err) {
        goBtn.disabled = false
        errEl.style.color = _C.err
        errEl.textContent = err?.message || (ensemble ? 'Ensemble submit failed' : resume ? 'Resume failed' : 'Submit failed')
      }
    }
  }

  function _editField(label, id, value, type) {
    const v = value == null ? '' : String(value)
    return (
      `<label style="display:block;color:${_C.muted};margin-bottom:1px">${label}</label>` +
      `<input id="${id}" type="${type}" placeholder="${v}" ` +
      `style="width:100%;margin-bottom:6px;background:${_C.bg};border:1px solid ${_C.border};color:${_C.text};border-radius:3px;padding:3px 5px">`
    )
  }

  return { open, dispose }
}
