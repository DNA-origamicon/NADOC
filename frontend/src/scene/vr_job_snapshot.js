import { flattenJobTree } from '../ui/job_tree.js'

export const VR_JOB_SNAPSHOT_LIMIT = 64

const ENGINE_LABELS = {
  oxdna: 'oxDNA',
  lammps: 'LAMMPS',
  mrdna: 'mrDNA',
  cando: 'CanDo',
  snupi: 'SNUPI',
  blade: 'BLADE',
  namd: 'NAMD',
}

function _asciiText(value, fallback, maxLength) {
  const text = String(value ?? '')
    .normalize('NFKD')
    .replace(/[^\x20-\x7e]/g, '?')
    .replace(/\s+/g, ' ')
    .trim()
  return (text || fallback).slice(0, maxLength)
}

function _progressPermille(node) {
  const remoteTarget = node?.execution_target === 'alpine' ||
    node?.execution_target === 'runpod'
  const awaitingSubmission = node?.engine === 'namd' && remoteTarget &&
    node?.status === 'queued' && !node?.slurm_job_id && !node?.runpod_pod_id &&
    !node?.remote_submit_progress
  if (awaitingSubmission) return 0
  if (node?.remote_submit_progress?.fraction != null) {
    return Math.round(Math.max(0, Math.min(
      1, Number(node.remote_submit_progress.fraction) || 0,
    )) * 1000)
  }
  if (node?.status === 'completed' || node?.production_state === 'done') return 1000
  let fraction = Number(node?.progress_fraction)
  if (!Number.isFinite(fraction)) {
    if (node?.engine === 'lammps') {
      const total = Number(node.steps)
      fraction = total > 0 ? Number(node.current_step) / total : 0
    } else {
      const phases = node?.engine === 'namd' ? node.segments : node?.stages
      fraction = Array.isArray(phases) && phases.length
        ? phases.filter(phase => phase?.status === 'done').length / phases.length
        : 0
    }
  }
  return Math.round(Math.max(0, Math.min(1, fraction || 0)) * 1000)
}

function _jobLabel(node) {
  return _asciiText(
    node?.design_name || node?.name || node?.job_name || node?.job_id,
    'Unnamed run',
    48,
  )
}

/**
 * Project the canonical unified simulation-job nodes into a bounded native-VR
 * launch snapshot. This is display-only: the engine-qualified job identity is
 * retained for later intents, but no job action is exposed by this contract.
 */
export function buildVRJobSnapshot(
  nodes, limit = VR_JOB_SNAPSHOT_LIMIT, activeJob = null,
) {
  const boundedLimit = Math.max(0, Math.min(VR_JOB_SNAPSHOT_LIMIT, Number(limit) || 0))
  if (!Array.isArray(nodes) || boundedLimit === 0) return []

  const safeNodes = nodes.filter(node =>
    node && typeof node.job_id === 'string' && node.job_id &&
    typeof node.engine === 'string' && node.engine &&
    typeof node.status === 'string' && node.status)
  let flattened = flattenJobTree(safeNodes)
  const activeIndex = flattened.findIndex(({ job }) =>
    job.engine === activeJob?.engine && job.job_id === activeJob?.id)
  if (activeIndex > 0) {
    flattened = [flattened[activeIndex], ...flattened.filter((_, index) =>
      index !== activeIndex)]
  }
  return flattened.slice(0, boundedLimit).map(({ job, depth }) => {
    const engine = _asciiText(job.engine, 'unknown', 24).toLowerCase()
    const status = _asciiText(job.status, 'unknown', 32).toLowerCase()
    const progressPermille = _progressPermille(job)
    const engineLabel = ENGINE_LABELS[engine] || engine.toUpperCase()
    return {
      job_id: _asciiText(job.job_id, 'unknown', 128),
      parent_job_id: job.parent_job_id
        ? _asciiText(job.parent_job_id, '', 128) || null
        : null,
      engine,
      status,
      label: _jobLabel(job),
      status_text: _asciiText(
        `${engineLabel} - ${status} - ${(progressPermille / 10).toFixed(1)}%`,
        `${engineLabel} - ${status}`,
        96,
      ),
      depth: Math.max(0, Math.min(8, Number(depth) || 0)),
      progress_permille: progressPermille,
      viewable: job.viewable === true,
      stale: job.out_of_date === true,
      archived: job.archived === true,
    }
  })
}
