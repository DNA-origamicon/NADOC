/** Restart notices are independent of design-staleness warnings and job controls. */
export function restartSummary(event) {
  const label = { continued: 'Resumed from checkpoint', restarted: 'Restarted from the original seed',
    blocked: 'Stopped: checkpoint needs review', checking: 'Restart detected; checking recovery',
    unknown: 'Restart detected; recovery is unverified' }[event.mode] || 'Alpine restart'
  const details = [label]
  for (const segment of event.segments || []) {
    if (segment.mode === 'continued') {
      const ns = segment.checkpoint_step * (segment.timestep_fs || 0) / 1e6
      details.push(`${segment.segment}: continued at step ${segment.checkpoint_step}${ns ? ` (${ns.toFixed(3)} ns)` : ''}.`)
    }
    if (segment.error) details.push(segment.error)
  }
  for (const saved of event.evidence?.records || []) {
    details.push(`Preserved ${(saved.step * saved.timestep_fs / 1e6).toFixed(3)} ns in ${saved.frames} frames: ${saved.path}`)
  }
  if (event.mode === 'restarted') details.push('The restarted trajectory is separate. Same seed and initial state; statistical independence is unverified. The old restart checkpoint is unavailable.')
  if (event.inspection_error) details.push(`Inspection: ${event.inspection_error}`)
  return details.join('\n\n')
}

export async function acknowledgeRestarts(jobId, events) {
  const { _request } = await import('../api/client.js')
  return _request('POST', `/md/jobs/${encodeURIComponent(jobId)}/restart-acknowledgment`, {
    events: events.map(e => ({ id: e.id, revision: e.revision || 1 })),
  })
}

export function appendRestartNotice(row, model, { doc = document, acknowledge = acknowledgeRestarts } = {}) {
  if (!model.restartEvents?.length) return
  let events = model.restartEvents
  const button = doc.createElement('button')
  button.type = 'button'
  button.dataset.alpineRestart = model.jobId
  button.style.cssText = 'border:0;background:transparent;color:#e8ad50;cursor:pointer;padding:0 3px'
  function refresh() {
    const pending = !model.restartHistoryOnly && events.some(e => !e.acknowledged_at)
    button.textContent = pending ? '⚠' : 'ⓘ'
    button.title = pending ? 'Alpine restarted this job — review what happened' : model.restartHistoryOnly ? 'Alpine restart history' : 'Alpine restart history (acknowledged)'
    button.setAttribute('aria-label', button.title)
  }
  refresh()
  button.addEventListener('pointerdown', e => e.stopPropagation())
  button.addEventListener('click', e => {
    e.stopPropagation()
    const dialog = doc.createElement('dialog')
    dialog.dataset.alpineRestartDialog = model.jobId
    dialog.style.cssText = 'max-width:640px;background:#20262e;color:#eee;border:1px solid #657080;border-radius:8px;padding:20px'
    const heading = doc.createElement('h3')
    heading.textContent = 'Alpine restart history'
    dialog.append(heading)
    for (const event of events) {
      const text = doc.createElement('p')
      text.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere'
      const when = event.started_at ? new Date(event.started_at * 1000).toLocaleString() : event.scheduler?.start_time || 'Time unavailable'
      text.textContent = `${when} · Slurm ${event.slurm_job_id || 'unknown'} · restart ${event.restart_count}\n\n${restartSummary(event)}`
      dialog.append(text)
    }
    const error = doc.createElement('p')
    error.setAttribute('role', 'alert')
    dialog.append(error)
    const close = doc.createElement('button')
    close.textContent = 'Close'
    close.addEventListener('click', () => dialog.close())
    dialog.append(close)
    const pending = model.restartHistoryOnly ? [] : events.filter(e => !e.acknowledged_at)
    if (pending.length) {
      const accept = doc.createElement('button')
      accept.textContent = 'I understand'
      accept.style.marginLeft = '12px'
      accept.addEventListener('click', async () => {
        accept.disabled = true
        try {
          const result = await acknowledge(model.jobId, pending)
          if (!result?.ok) throw new Error('Acknowledgment was not saved. Please try again.')
          events = result.restart_events
          refresh()
          dialog.close()
        } catch (err) {
          error.textContent = err.message
          accept.disabled = false
        }
      })
      dialog.append(accept)
    }
    dialog.addEventListener('close', () => dialog.remove(), { once: true })
    doc.body.append(dialog)
    dialog.showModal()
  })
  row.append(button)
}
