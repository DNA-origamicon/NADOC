/** Ordered worker phases, not equally weighted fractions or invented timestamps. */
export function snupiDynamicsStages(job) {
  if (!job?.dynamics || (job.engine && job.engine !== 'snupi')) return null
  const remote = ['runpod', 'alpine'].includes(job.execution_target)
  const stages = [
    ...(remote ? [['deployment', 'Prepare remote solver']] : []),
    ['mesh', 'Build dynamics mesh'], ['stiffness', 'Assemble stiffness'],
    ['timestep', 'Calculate stable timestep'],
    ...(job.hydrodynamics ? [['friction', 'Build hydrodynamic friction']] : []),
    ['integration', 'Integrate dynamics'], ['analysis', 'Analyze and save results'],
    ...(remote ? [['download', 'Download results']] : []),
  ].map(([id, label]) => ({ id, label, status: 'pending', detail: '' }))
  if (job.status === 'completed') return stages.map(s => ({ ...s, status: 'done' }))
  const phase = String(job.phase || '').replace(/^(RunPod|Alpine)\s*·\s*/i, '').toLowerCase()
  let current = null
  if (remote && (job.remote?.downloading || phase === 'downloading results')) current = 'download'
  else if (['queued', 'preparing'].includes(job.status)) current = remote ? 'deployment' : null
  else if (phase.includes('analyzing dynamics trajectory')) current = 'analysis'
  else if (phase.startsWith('trajectory')) current = 'integration'
  else if (phase.includes('hydrodynamic friction') && job.hydrodynamics) current = 'friction'
  else if (phase.includes('stable dynamics timestep')) current = 'timestep'
  else if (phase.includes('stiffness')) current = 'stiffness'
  else if (phase === 'mesh' || phase === 'building dynamics mesh') current = 'mesh'
  else if (remote && /^(booting|staging|setting_up_environment|preparing solver)$/.test(phase)) current = 'deployment'
  const index = stages.findIndex(s => s.id === current)
  const terminal = ['failed', 'stopped'].includes(job.status)
  if (index < 0) {
    // Unknown legacy receipts cannot establish which scientific stage was reached.
    stages.unshift({ id: 'observation', label: 'Stage telemetry', status: terminal ? job.status : 'unknown',
      detail: job.phase || 'Waiting for worker phase' })
    return stages
  }
  for (let i = 0; i < index; i++) stages[i].status = 'done'
  const row = stages[index]
  row.status = terminal ? job.status : job.progress_last_known ? 'last-known' : job.status === 'queued' ? 'queued' : 'running'
  row.detail = job.phase || ''
  if (current === 'integration') {
    const step = job.current_step ?? job.step
    const total = job.total_steps || 60000
    row.detail = step != null && Number.isFinite(Number(step))
      ? `${Number(step).toLocaleString()} / ${Number(total).toLocaleString()} steps` : 'Waiting for step count'
    if (job.attempt) row.detail += ` · retry ${job.attempt}`
  }
  return stages
}

const statusStyle = {
  done: ['✓', 'Done', 'success'], running: ['◐', 'Running', 'warning'],
  pending: ['○', 'Pending', 'text-muted'], queued: ['○', 'Queued', 'text-muted'],
  failed: ['✗', 'Failed', 'danger'], stopped: ['■', 'Stopped', 'warning'],
  'last-known': ['◐', 'Last known · sync unavailable', 'warning'], unknown: ['?', 'Unknown', 'text-muted'],
}

/** Stateless renderer shared by engine selection and unified-job polling. */
export function renderSnupiDynamicsTimeline(element, job) {
  const stages = snupiDynamicsStages(job)
  if (!element || !stages) return false
  element.replaceChildren()
  for (const stage of stages) {
    const [symbol, status, color] = statusStyle[stage.status]
    const row = document.createElement('div')
    row.dataset.stage = stage.id
    row.dataset.status = stage.status
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:3px 0'
    if (stage.status === 'running') row.setAttribute('aria-current', 'step')
    row.title = [stage.label, status, stage.detail].filter(Boolean).join(' · ')
    const label = document.createElement('span')
    label.style.cssText = 'flex:1;min-width:0;color:var(--color-text-primary)'
    label.textContent = stage.label + (stage.detail && stage.id === 'integration' ? ` · ${stage.detail}` : '')
    const state = document.createElement('span')
    state.style.cssText = `flex-shrink:0;color:var(--color-${color})`
    state.textContent = `${symbol} ${status}`
    row.append(label, state)
    element.append(row)
  }
  return true
}
