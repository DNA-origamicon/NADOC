/**
 * Pure logic for the Job Wizard's first step — *where* the run executes.
 *
 * The wizard used to own only PROTOCOL parameters while the panel owned ENVIRONMENT.
 * That split broke down once the compute targets stopped being interchangeable: an
 * Alpine H200 and a local RTX are different enough in throughput and in queue latency
 * that the answer changes how you'd size the run, so the choice has to come *first*,
 * not after every protocol field is already set.
 *
 * Everything here is pure — no DOM, no fetch. The factory in
 * `md_job_wizard_target.js` owns the rendering and the network.
 */

/** The three compute targets, in the order the step presents them. */
export const TARGETS = [
  { id: 'local', label: 'This computer',
    blurb: 'Runs NAMD as a local subprocess. No queue, no allocation spend.' },
  { id: 'alpine', label: 'Alpine cluster',
    blurb: 'CU Research Computing. Needs a login (Duo) and spends SU.' },
  { id: 'runpod', label: 'RunPod',
    blurb: 'Rented cloud GPU, billed by the second.' },
]

export const TARGET_IDS = TARGETS.map(t => t.id)

/**
 * Targets that are not wired up yet — selectable-looking but blocked, with a reason.
 *
 * Empty now that RunPod has its own block in step 1. The mechanism stays: it is the general
 * escape hatch for a target that exists in the list before its UI does, and re-populating it
 * is a one-line change.
 */
export const UNWIRED_TARGETS = {}

/**
 * NAMD3 GPU-resident throughput of a local GPU relative to an A100.
 *
 * Mirrors the A100 anchor used by `backend/core/cluster_resources._GPU_SPEED_FACTOR`,
 * so a cluster partition's `speed_factor` and a local card land on one scale and can
 * be divided. Matched loosely on the reported name because vendors decorate it
 * ("NVIDIA GeForce RTX 4090", "Quadro RTX 6000"). Order matters: the first hit wins,
 * so longer/more specific keys must come first.
 */
const _LOCAL_GPU_FACTORS = [
  ['h200', 2.5], ['h100', 2.2], ['gh200', 2.6],
  ['a100', 1.0], ['rtx pro 6000', 2.5],   // measured == H200 (2026-08-07)
  ['5090', 1.5], ['4090', 1.1], ['4080', 0.75],
  ['3090', 0.65], ['3080', 0.5],
  ['a6000', 0.7], ['a5000', 0.5], ['a40', 0.6],
  ['l40', 1.4], ['v100', 0.45], ['mi100', 0.5],   // measured on Alpine al40 (2026-08-07)
  ['t4', 0.15], ['p100', 0.2],
]

/**
 * Local GPU speed relative to an A100, or `null` when the card is unrecognised.
 *
 * `null` is a real answer and must stay distinct from 1.0 — claiming an unknown GPU
 * is exactly A100-equivalent would put a confident wrong number next to every
 * partition in the comparison table.
 */
export function localGpuSpeedFactor(gpuName) {
  const name = String(gpuName || '').toLowerCase()
  if (!name) return null
  for (const [key, factor] of _LOCAL_GPU_FACTORS) {
    if (name.includes(key)) return factor
  }
  return null
}

/**
 * "≈2.5× this computer" for a partition, given its A100-relative speed factor.
 * Returns '' when the local card is unknown — no baseline, no comparison.
 */
export function relativeSpeedLabel(partitionSpeedFactor, localFactor) {
  if (localFactor == null || !isFinite(localFactor) || localFactor <= 0) return ''
  const pf = Number(partitionSpeedFactor)
  if (!isFinite(pf) || pf <= 0) return ''
  const ratio = pf / localFactor
  if (ratio >= 1) return `≈${ratio.toFixed(ratio >= 10 ? 0 : 1)}× this computer`
  return `≈${(1 / ratio).toFixed(ratio > 0.1 ? 1 : 0)}× slower than this computer`
}

/** Human summary of the local hardware probe (`GET /md/optimize-advanced/hardware`). */
export function localHardwareSummary(hw) {
  if (!hw) return ''
  if (hw.summary) return hw.summary
  const bits = []
  if (hw.gpu_name) bits.push(hw.gpu_name)
  if (hw.vram_mb) bits.push(`${Math.round(hw.vram_mb / 1024)} GB VRAM`)
  if (hw.host_ram_mb) bits.push(`${Math.round(hw.host_ram_mb / 1024)} GB RAM`)
  if (hw.physical_cores) bits.push(`${hw.physical_cores} cores`)
  return bits.join(' · ')
}

/** Largest system this machine can hold, phrased for the step. '' when unknown. */
export function atomCapLabel(hw) {
  const cap = hw?.atom_cap
  if (!cap || !isFinite(cap)) return ''
  return cap >= 1e6
    ? `fits systems up to ~${(cap / 1e6).toFixed(1)}M atoms`
    : `fits systems up to ~${Math.round(cap / 1000)}k atoms`
}

/**
 * Can the user move on from this step?
 *
 * Deliberately strict for Alpine: a target that cannot actually accept the job is
 * worse than no choice at all, because the failure would otherwise surface after the
 * whole protocol is configured and the package built.
 */
export function targetReadiness(target, {
  clusterState = 'disconnected', partition = null,
} = {}) {
  if (!TARGET_IDS.includes(target)) return { ready: false, reason: 'Choose where this job runs.' }
  if (UNWIRED_TARGETS[target]) return { ready: false, reason: UNWIRED_TARGETS[target] }
  if (target === 'local') return { ready: true, reason: '' }
  // RunPod is advisory while the job is being designed. The first tab cannot know the final
  // protocol, solvated atom count, or package size yet, so a preview failure must not prevent
  // the user reaching those choices. The authoritative gate belongs to ▶ Rent & Run after
  // job creation, when the prepared PSF and manifest make all of those values concrete.
  if (target === 'runpod') return { ready: true, reason: '' }
  if (clusterState !== 'connected') {
    return { ready: false, reason: 'Sign in to Alpine to see availability and pick a node.' }
  }
  if (!partition) return { ready: false, reason: 'Pick a partition to run on.' }
  return { ready: true, reason: '' }
}

/**
 * The job-creation fields this step contributes.
 *
 * `cluster_name`/`partition` are cleared for non-Alpine targets rather than left
 * stale — a leftover partition on a local job would resurface at submit time.
 * `slurm_resources` carries only what the user edited (see `resourceOverrides`); an
 * empty edit set is sent as null so the backend keeps auto-recommending.
 */
export function targetPayloadFields(target, {
  partition = null, runpodGpuKey = null, runpodBudgetUsd = null, runpodVolumeId = null,
  runpodEstimatedCostUsd = null, runpodQuotedRateUsdPerHour = null,
  resources = null,
} = {}) {
  const edits = target === 'alpine' && resources && Object.keys(resources).length
    ? resources
    : null
  const isRunpod = target === 'runpod'
  return {
    execution_target: TARGET_IDS.includes(target) ? target : 'local',
    cluster_name: target === 'alpine' ? 'alpine' : null,
    partition: target === 'alpine' ? (partition || null) : null,
    slurm_resources: edits,
    // Cleared for every other target for the same reason `partition` is: a leftover card or
    // spend cap on a job the user re-pointed at the local GPU would resurface at launch.
    runpod_gpu_key: isRunpod ? (runpodGpuKey || null) : null,
    runpod_estimated_cost_usd: isRunpod && runpodEstimatedCostUsd != null
      ? Number(runpodEstimatedCostUsd) : null,
    runpod_quoted_rate_usd_per_hour: isRunpod && runpodQuotedRateUsdPerHour != null
      ? Number(runpodQuotedRateUsdPerHour) : null,
    runpod_budget_usd: isRunpod && runpodBudgetUsd != null ? Number(runpodBudgetUsd) : null,
    runpod_volume_id: isRunpod ? (runpodVolumeId || null) : null,
  }
}

/**
 * The SLURM resources the first step lets you adjust, in the order they render.
 *
 * These used to live in the submit-review card that popped up AFTER the job was created,
 * which was both too late to reconsider the node and too early to attach anchors. They
 * belong next to the partition table: picking a node and sizing the request against it
 * is one decision, and the recommendation below is derived from the design already on
 * screen.
 */
export const RESOURCE_FIELDS = [
  { key: 'gpus', label: 'GPUs', type: 'number', min: 0, step: 1 },
  { key: 'cores', label: 'CPU cores', type: 'number', min: 1, step: 1 },
  { key: 'mem_gb', label: 'Memory', unit: 'GB', type: 'number', min: 1, step: 1 },
  { key: 'walltime', label: 'Wall time', type: 'text', placeholder: 'HH:MM:SS' },
  { key: 'qos', label: 'QoS', type: 'select' },
]

/**
 * Pure: what each resource control shows — the user's edit if there is one, else the
 * recommendation sized from this design.  `edited` marks which is which, so the UI can
 * say "recommended" vs "you set this" and the payload can send only the latter.
 */
export function resourceFieldValues(preview, edited = {}) {
  const rec = preview?.resources || {}
  const out = {}
  for (const f of RESOURCE_FIELDS) {
    const own = Object.prototype.hasOwnProperty.call(edited, f.key) ? edited[f.key] : null
    const recommended = rec[f.key]
    // Presence in `edited`, not a value comparison: typing the recommended number is
    // still a decision to PIN it, and it is what gets sent, so the chip must say so.
    const isEdited = own != null && own !== ''
    out[f.key] = {
      value: isEdited ? String(own) : (recommended == null ? '' : String(recommended)),
      recommended: recommended == null ? '' : String(recommended),
      edited: isEdited,
    }
  }
  return out
}

/**
 * Pure: the read-only context rows shown above the editable resources — the facts that
 * EXPLAIN the recommendation rather than being part of it.  The partition table above
 * already carries free GPUs, wait and relative speed, so those are not repeated.
 */
export function resourceContextRows(preview) {
  const r = preview?.resources
  if (!r) return []
  const rows = []
  if (preview.n_atoms) {
    rows.push(['System size', `${Number(preview.n_atoms).toLocaleString()} atoms${
      preview.n_atoms_source === 'estimated' ? ' (estimated — not solvated yet)' : ''}`])
  }
  if (preview.total_ns != null) rows.push(['Simulation', `${preview.total_ns} ns total`])
  if (r.expected_ns_per_day != null) {
    rows.push(['Throughput', `${Number(r.expected_ns_per_day).toFixed(1)} ns/day${
      r.measured ? ' (measured)' : ' (estimated)'}`])
  }
  if (r.est_cost_su != null) {
    rows.push(['Est. cost', `${Math.round(r.est_cost_su).toLocaleString()} SU`])
  }
  return rows
}

/** Pure: the recommendation's own caveats — headroom multiplier plus any notes. */
export function resourceNotes(preview) {
  const r = preview?.resources
  if (!r) return []
  const notes = Array.isArray(r.notes) ? [...r.notes] : (r.notes ? [String(r.notes)] : [])
  if (r.safety_factor) notes.unshift(`Wall time carries ${r.safety_factor}× headroom.`)
  return notes
}

/**
 * Rows for the Alpine partition table, newest-availability first.
 *
 * Takes the `/cluster/availability` response straight through — it already sorts by
 * time-to-result and carries wait provenance. Request-only hardware (gh200) is kept
 * but marked unselectable, so its existence is visible without being offered.
 */
export function partitionChoices(availability, localFactor = null) {
  const rows = availability?.partitions || []
  return rows.map(r => ({
    partition: r.partition,
    gpuModel: r.gpu_model || r.gres_type || '',
    free: `${r.gpus_free ?? 0} / ${r.gpus_total ?? 0}`,
    migNote: (r.mig_total ?? 0) ? `+${r.mig_free ?? 0} MIG slices (not usable by this job)` : '',
    wait: r.request_only ? 'request access' : (r.wait_label || 'unknown'),
    waitBasis: r.wait_basis || '',
    speed: relativeSpeedLabel(r.speed_factor, localFactor),
    // Two partitions can be equally fast and differ ~30% in cost — that is the real
    // decision between ah200 and artxpro6000, so it belongs on screen.
    suPerNs: r.job_su_per_ns != null ? `${Math.round(r.job_su_per_ns)} SU/ns` : '',
    maxWalltimeH: r.max_walltime_h ?? null,
    selectable: !r.request_only && (r.gpus_total ?? 0) > 0,
    note: r.request_only ? 'Needs a CURC support request' : '',
  }))
}

/**
 * Which partition to preselect: the first selectable row, i.e. the one the backend
 * ranked fastest to a finished run. Never auto-picks unusable hardware.
 */
export function defaultPartition(choices) {
  return (choices || []).find(c => c.selectable)?.partition || null
}

const _esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

/** The headline numbers of a SLURM request, as label/value pairs for the plan step. */
export function slurmFacts(preview) {
  const r = preview?.resources
  if (!r) return []
  return [
    ['Partition', `${r.partition}${r.gres_type ? ` (${r.gres_type})` : ''}`],
    ['QoS', r.qos],
    ['Walltime', r.walltime],
    ['CPUs / GPUs', `${r.cores} cores · ${r.gpus} GPU${r.gpus === 1 ? '' : 's'}`],
    ['Memory', `${r.mem_gb} GB`],
    ['Throughput', `${r.expected_ns_per_day} ns/day${r.measured ? ' (measured)' : ' (estimated)'}`],
    ['Est. cost', `${Math.round(r.est_cost_su).toLocaleString()} SU`],
    ['System size', preview.n_atoms
      ? `${Number(preview.n_atoms).toLocaleString()} atoms${
          preview.n_atoms_source === 'estimated' ? ' (estimated — solvation not run yet)' : ''}`
      : '—'],
  ]
}

/**
 * The SLURM inspection block for the plan step.
 *
 * Shows the resolved request, then the literal sbatch text. The point is that the
 * user can read exactly what will be submitted while still deciding — the submit
 * review card comes far too late to change your mind about the protocol.
 */
export function renderSlurmDetails(preview, { busy = false, error = '' } = {}) {
  if (busy) return '<div style="font-size:11px;color:#8b949e">Sizing the SLURM request…</div>'
  if (error) return `<div style="font-size:11px;color:#f85149">${_esc(error)}</div>`
  if (!preview) return ''
  if (preview.sized === false) {
    return `<div style="font-size:11px;color:#8b949e">${_esc(preview.reason || 'Not sized.')}</div>`
  }
  const facts = slurmFacts(preview).map(([k, v]) =>
    `<div style="display:flex;justify-content:space-between;gap:12px;padding:2px 0">` +
    `<span style="color:#6e7681">${_esc(k)}</span>` +
    `<span style="color:#c9d1d9;text-align:right">${_esc(v)}</span></div>`).join('')
  const warnings = (preview.warnings || []).map(w =>
    `<div style="font-size:11px;color:#d29922;background:rgba(210,153,34,.1);` +
    `border:1px solid rgba(210,153,34,.35);border-radius:4px;padding:6px 8px;margin-top:8px">` +
    `⚠ ${_esc(w)}</div>`).join('')
  return (
    `<div style="display:grid;grid-template-columns:1fr 1.2fr;gap:16px;align-items:start">` +
    `<div style="font-size:11px">${facts}</div>` +
    `<pre style="margin:0;font-size:10px;line-height:1.5;color:#8b949e;background:#0d1117;` +
    `border:1px solid #21262d;border-radius:5px;padding:9px;overflow-x:auto;max-height:260px">` +
    `${_esc(preview.text || '')}</pre></div>${warnings}`
  )
}
